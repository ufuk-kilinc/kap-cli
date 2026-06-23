import httpx
import pytest
import respx

from kap.client import KapClient
from kap.config import ResolvedConfig
from kap.errors import KapApiError, KapConnectivityError


class _StubAuth:
    """Token provider stub: returns sequential tokens, counts invalidations."""

    def __init__(self):
        self.tokens = ["tok1", "tok2"]
        self.i = 0
        self.invalidated = 0

    def get_token(self):
        return self.tokens[min(self.i, len(self.tokens) - 1)]

    def invalidate(self):
        self.invalidated += 1
        self.i += 1


def _client(auth=None):
    cfg = ResolvedConfig("test", "https://h", "key", 60)
    return KapClient(cfg, token_provider=auth or _StubAuth())


@respx.mock
def test_last_disclosure_index():
    respx.get("https://h/api/vyk/lastDisclosureIndex").mock(
        return_value=httpx.Response(200, json={"lastDisclosureIndex": 1234567})
    )
    assert _client().last_disclosure_index() == 1234567


@respx.mock
def test_disclosures_sends_params_and_raw_auth_header():
    route = respx.get("https://h/api/vyk/disclosures").mock(
        return_value=httpx.Response(200, json=[{"disclosureIndex": 1}])
    )
    out = _client().disclosures(100, disclosure_class="FR", company_id=42)
    assert out == [{"disclosureIndex": 1}]
    req = route.calls.last.request
    assert req.url.params["disclosureIndex"] == "100"
    assert req.url.params["disclosureClass"] == "FR"
    assert req.url.params["companyId"] == "42"
    assert req.headers["authorization"] == "tok1"   # RAW, no "Bearer "


@respx.mock
def test_er005_maps_to_empty_list():
    respx.get("https://h/api/vyk/members").mock(
        return_value=httpx.Response(404, json={"code": "ER005", "message": "nf"})
    )
    assert _client().members() == []


@respx.mock
def test_disclosure_detail_er005_maps_to_none():
    respx.get("https://h/api/vyk/disclosureDetail/9").mock(
        return_value=httpx.Response(404, json={"code": "ER005", "message": "nf"})
    )
    assert _client().disclosure_detail(9) is None


@respx.mock
def test_other_error_raises():
    respx.get("https://h/api/vyk/funds").mock(
        return_value=httpx.Response(403, json={"code": "ER001", "message": "denied"})
    )
    with pytest.raises(KapApiError) as ei:
        _client().funds()
    assert ei.value.code == "ER001"


@respx.mock
@pytest.mark.parametrize("code", ["ER004", "ER006", "ER012"])
def test_token_error_retries_once_then_succeeds(code):
    auth = _StubAuth()
    respx.get("https://h/api/vyk/funds").mock(
        side_effect=[
            httpx.Response(401, json={"code": code, "message": "bad token"}),
            httpx.Response(200, json=[{"a": 1}]),
        ]
    )
    out = _client(auth).funds()
    assert out == [{"a": 1}]
    assert auth.invalidated == 1


@respx.mock
@pytest.mark.parametrize("code", ["ER004", "ER006", "ER012"])
def test_token_error_twice_raises(code):
    auth = _StubAuth()
    respx.get("https://h/api/vyk/funds").mock(
        return_value=httpx.Response(401, json={"code": code, "message": "bad token"})
    )
    with pytest.raises(KapApiError):
        _client(auth).funds()
    assert auth.invalidated == 1


@respx.mock
def test_ca_event_status_joins_ref_ids():
    route = respx.get("https://h/api/vyk/caEventStatus").mock(
        return_value=httpx.Response(200, json=[])
    )
    _client().ca_event_status([1, 2, 3])
    assert route.calls.last.request.url.params["processRefId"] == "1,2,3"


@respx.mock
def test_download_attachment_unwraps_java_envelope():
    envelope = b"\xac\xed\x00\x05ur\x00\x02[B" + b"%PDF-1.7 real bytes"
    respx.get("https://h/api/vyk/downloadAttachment/abc").mock(
        return_value=httpx.Response(200, content=envelope)
    )
    out = _client().download_attachment("abc")
    assert out == b"%PDF-1.7 real bytes"


@respx.mock
def test_download_attachment_er005_returns_none():
    respx.get("https://h/api/vyk/downloadAttachment/abc").mock(
        return_value=httpx.Response(404, json={"code": "ER005", "message": "nf"})
    )
    assert _client().download_attachment("abc") is None


@respx.mock
def test_raw_returns_metadata_and_body():
    respx.get("https://h/api/vyk/members").mock(
        return_value=httpx.Response(200, text="[]", headers={"content-type": "application/json"})
    )
    out = _client().raw("api/vyk/members")
    assert out["status_code"] == 200
    assert out["is_success"] is True
    assert out["body"] == "[]"


def test_connect_timeout_raises_connectivity_error():
    cfg = ResolvedConfig("test", "https://h", "key", 60)

    def boom(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    transport = httpx.MockTransport(boom)
    http = httpx.Client(transport=transport)
    client = KapClient(cfg, token_provider=_StubAuth(), http=http)
    with pytest.raises(KapConnectivityError, match="allowlist"):
        client.members()
