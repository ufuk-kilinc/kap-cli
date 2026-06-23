from __future__ import annotations

from typing import Any, Literal, TypedDict

import httpx

from kap.auth import TokenProvider
from kap.config import ResolvedConfig
from kap.errors import KapApiError, KapConnectivityError, KapResponseError

# A parsed JSON object from the KAP API. The upstream payloads are variable and
# polymorphic, so we intentionally don't model each one — but every consumer
# treats list rows and detail bodies as JSON objects, so this is the honest type.
JsonObj = dict[str, Any]

_PDF_MARKER = b"%PDF"


class RawResponse(TypedDict):
    """The fixed-shape envelope returned by ``KapClient.raw`` (authored here, not upstream)."""

    service: str
    status_code: int
    is_success: bool
    content_type: str | None
    body: str

_CONNECTIVITY_HINT = (
    "Could not connect to KAP. You may not be on an allowlisted IP — MKK silently "
    "drops non-allowlisted source IPs (TCP timeout, not 401). Check your VPN / egress "
    "IP, or ask MKK (kapdestek@mkk.com.tr) to allowlist it."
)


class KapClient:
    """Typed-ish client over the KAP /api/vyk/* endpoints (returns parsed JSON)."""

    def __init__(
        self,
        config: ResolvedConfig,
        token_provider: TokenProvider | None = None,
        http: httpx.Client | None = None,
    ):
        self._config = config
        self._auth = token_provider or TokenProvider(
            config.base_url, config.api_key, config.env, config.token_refresh_skew_seconds
        )
        self._http = http or httpx.Client(base_url=config.base_url, timeout=60.0)

    # ── public endpoints ──────────────────────────────────────────────────────
    def last_disclosure_index(self) -> int:
        resp = self._get("api/vyk/lastDisclosureIndex")
        data = self._json(resp) or {}
        if isinstance(data, dict):
            for key, value in data.items():
                if key.lower() == "lastdisclosureindex":
                    return int(value)
        raise KapResponseError(resp.status_code, f"unexpected lastDisclosureIndex response: {data}")

    def disclosures(
        self,
        index: int,
        *,
        disclosure_type: str | None = None,
        disclosure_class: str | None = None,
        company_id: str | int | None = None,
    ) -> list[JsonObj]:
        params: dict[str, str | int] = {"disclosureIndex": index}
        if disclosure_type:
            params["disclosureType"] = disclosure_type
        if disclosure_class:
            params["disclosureClass"] = disclosure_class
        if company_id is not None:
            params["companyId"] = company_id
        return self._get_list("api/vyk/disclosures", params)

    def disclosure_detail(
        self, index: int, file_type: Literal["data", "html"] = "data", sub_report: str | None = None
    ) -> JsonObj | None:
        params: dict[str, str] = {"fileType": file_type}
        if sub_report:
            params["subReportList"] = sub_report
        try:
            return self._json(self._get(f"api/vyk/disclosureDetail/{index}", params))
        except KapApiError as exc:
            if exc.is_not_found:
                return None
            raise

    def download_attachment(self, attachment_id: str) -> bytes | None:
        if not attachment_id or not attachment_id.strip():
            raise ValueError("attachment_id is required.")
        try:
            resp = self._get(f"api/vyk/downloadAttachment/{attachment_id}")
        except KapApiError as exc:
            if exc.is_not_found:
                return None
            raise
        # KAP wraps the file in a Java-serialized byte[] envelope; the real PDF
        # starts at the %PDF marker. No marker → it isn't the PDF we expect, and
        # we must NOT silently save non-PDF bytes to a .pdf file.
        raw = resp.content
        start = raw.find(_PDF_MARKER)
        if start < 0:
            raise KapResponseError(
                resp.status_code,
                f"attachment '{attachment_id}' is not a PDF "
                f"(content-type={resp.headers.get('content-type')}, {len(raw)} bytes, no %PDF marker)",
            )
        return raw[start:]

    def members(self) -> list[JsonObj]:
        return self._get_list("api/vyk/members")

    def funds(self) -> list[JsonObj]:
        return self._get_list("api/vyk/funds")

    def fund_detail(self, fund_id: int) -> list[JsonObj]:
        return self._get_list(f"api/vyk/fundDetail/{fund_id}")

    def member_securities(self) -> list[JsonObj]:
        return self._get_list("api/vyk/memberSecurities")

    def blocked_disclosures(self) -> list[JsonObj]:
        return self._get_list("api/vyk/blockedDisclosures")

    def ca_event_status(self, ref_ids: list[int]) -> list[JsonObj]:
        if not ref_ids:
            raise ValueError("At least one processRefId is required.")
        joined = ",".join(str(r) for r in ref_ids)
        return self._get_list("api/vyk/caEventStatus", {"processRefId": joined})

    def raw(self, path: str, query: dict[str, str] | None = None) -> RawResponse:
        """Diagnostic passthrough: GET any relative path and return the raw response
        metadata + body. Unlike the typed methods, this does NOT retry on token
        errors and does NOT raise on non-2xx — the status code and body are returned
        as-is for inspection."""
        resp = self._send(path.lstrip("/"), query)
        return {
            "service": path,
            "status_code": resp.status_code,
            "is_success": resp.is_success,
            "content_type": resp.headers.get("content-type"),
            "body": resp.text,
        }

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "KapClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── internals ────────────────────────────────────────────────────────────
    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """GET with raw-token auth + retry-once on token error; raises on non-2xx."""
        for attempt in range(2):
            resp = self._send(path, params)
            if resp.is_success:
                return resp
            err = KapApiError.from_body(resp.status_code, resp.text)
            if err.is_token_error and attempt == 0:
                self._auth.invalidate()
                continue
            raise err
        raise err  # pragma: no cover

    def _send(self, path: str, params: dict | None) -> httpx.Response:
        token = self._auth.get_token()
        try:
            return self._http.get(path, params=params, headers={"Authorization": token})
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise KapConnectivityError(_CONNECTIVITY_HINT) from exc

    def _get_list(self, path: str, params: dict | None = None) -> list[JsonObj]:
        try:
            return self._json(self._get(path, params)) or []
        except KapApiError as exc:
            if exc.is_not_found:
                return []
            raise

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        """Parse a 2xx body as JSON, surfacing a non-JSON body as a KapResponseError."""
        try:
            return resp.json()
        except ValueError as exc:
            raise KapResponseError(
                resp.status_code, f"expected a JSON body but got: {resp.text[:200]}"
            ) from exc
