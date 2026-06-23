from __future__ import annotations

import json

_TOKEN_ERROR_CODES = {"ER004", "ER006", "ER012"}
_NOT_FOUND_CODE = "ER005"


class KapError(Exception):
    """Base class for all KAP CLI errors."""


class KapApiError(KapError):
    """A non-2xx response carrying a KAP error envelope {code, message}."""

    def __init__(self, status_code: int, code: str | None, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"KAP {code or '?'} (HTTP {status_code}): {message}")

    @property
    def is_token_error(self) -> bool:
        return self.code in _TOKEN_ERROR_CODES

    @property
    def is_not_found(self) -> bool:
        return self.code == _NOT_FOUND_CODE

    @classmethod
    def from_body(cls, status_code: int, body: str) -> "KapApiError":
        code: str | None = None
        message = body
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                code = parsed.get("code")
                msg = parsed.get("message")
                message = msg if msg is not None else body
        except (ValueError, TypeError):
            pass  # not JSON (HTML error page etc.) — keep the raw body
        return cls(status_code, code, message)


class KapConnectivityError(KapError):
    """Network-level failure reaching KAP (often an IP-allowlist / VPN problem)."""
