import base64
import json
import time

import httpx
import pytest
import respx

from kap.auth import TokenProvider, parse_jwt_expiry
from kap.errors import KapApiError, KapResponseError


def _make_jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": exp}).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def test_parse_jwt_expiry_reads_exp():
    assert parse_jwt_expiry(_make_jwt(1893456000)) == 1893456000


def test_parse_jwt_expiry_returns_none_on_garbage():
    assert parse_jwt_expiry("not-a-jwt") is None


@respx.mock
def test_get_token_mints_and_sends_apikey(tmp_path):
    token = _make_jwt(int(time.time()) + 10_000)
    route = respx.get("https://h/auth/generateToken").mock(
        return_value=httpx.Response(200, json={"token": token})
    )
    tp = TokenProvider("https://h", "secret", "test", cache_dir=tmp_path)
    assert tp.get_token() == token
    assert route.called
    assert route.calls.last.request.url.params["apiKey"] == "secret"


@respx.mock
def test_token_is_cached_on_disk_and_reused(tmp_path):
    token = _make_jwt(int(time.time()) + 10_000)
    route = respx.get("https://h/auth/generateToken").mock(
        return_value=httpx.Response(200, json={"token": token})
    )
    TokenProvider("https://h", "secret", "test", cache_dir=tmp_path).get_token()
    # a brand-new provider (fresh process) must reuse the cached token, not re-mint
    again = TokenProvider("https://h", "secret", "test", cache_dir=tmp_path).get_token()
    assert again == token
    assert route.call_count == 1
    assert (tmp_path / "token-test.json").exists()


@respx.mock
def test_expiring_token_is_reminted(tmp_path):
    stale = _make_jwt(int(time.time()) + 5)   # within default 60s skew → treated as expired
    fresh = _make_jwt(int(time.time()) + 10_000)
    respx.get("https://h/auth/generateToken").mock(
        side_effect=[
            httpx.Response(200, json={"token": stale}),
            httpx.Response(200, json={"token": fresh}),
        ]
    )
    tp1 = TokenProvider("https://h", "secret", "test", cache_dir=tmp_path)
    assert tp1.get_token() == stale
    tp2 = TokenProvider("https://h", "secret", "test", cache_dir=tmp_path)
    assert tp2.get_token() == fresh   # stale one was within skew, so re-minted


@respx.mock
def test_invalidate_forces_remint(tmp_path):
    t1 = _make_jwt(int(time.time()) + 10_000)
    t2 = _make_jwt(int(time.time()) + 20_000)
    respx.get("https://h/auth/generateToken").mock(
        side_effect=[httpx.Response(200, json={"token": t1}),
                     httpx.Response(200, json={"token": t2})]
    )
    tp = TokenProvider("https://h", "secret", "test", cache_dir=tmp_path)
    assert tp.get_token() == t1
    tp.invalidate()
    assert tp.get_token() == t2


@respx.mock
def test_mint_failure_raises_kap_api_error(tmp_path):
    respx.get("https://h/auth/generateToken").mock(
        return_value=httpx.Response(403, json={"code": "ER001", "message": "denied"})
    )
    tp = TokenProvider("https://h", "secret", "test", cache_dir=tmp_path)
    with pytest.raises(KapApiError) as ei:
        tp.get_token()
    assert ei.value.code == "ER001"


@respx.mock
def test_mint_non_json_body_raises_response_error(tmp_path):
    respx.get("https://h/auth/generateToken").mock(
        return_value=httpx.Response(200, text="<html>gateway</html>")
    )
    tp = TokenProvider("https://h", "secret", "test", cache_dir=tmp_path)
    with pytest.raises(KapResponseError):
        tp.get_token()


@respx.mock
def test_mint_missing_token_raises_response_error(tmp_path):
    respx.get("https://h/auth/generateToken").mock(
        return_value=httpx.Response(200, json={"notToken": "x"})
    )
    tp = TokenProvider("https://h", "secret", "test", cache_dir=tmp_path)
    with pytest.raises(KapResponseError):
        tp.get_token()
