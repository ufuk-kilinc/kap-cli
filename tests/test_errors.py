from kap.errors import KapApiError, KapConnectivityError, KapError


def test_from_body_parses_code_and_message():
    err = KapApiError.from_body(404, '{"code":"ER005","message":"not found"}')
    assert err.status_code == 404
    assert err.code == "ER005"
    assert err.message == "not found"
    assert err.is_not_found is True
    assert err.is_token_error is False


def test_token_error_codes():
    for code in ("ER004", "ER006", "ER012"):
        err = KapApiError.from_body(401, '{"code":"%s","message":"x"}' % code)
        assert err.is_token_error is True


def test_non_json_body_keeps_raw_message_and_null_code():
    err = KapApiError.from_body(500, "<html>boom</html>")
    assert err.code is None
    assert err.message == "<html>boom</html>"
    assert err.is_not_found is False


def test_is_a_kap_error():
    assert issubclass(KapApiError, KapError)
    assert issubclass(KapConnectivityError, KapError)


def test_str_includes_code_and_status():
    err = KapApiError.from_body(403, '{"code":"ER001","message":"denied"}')
    text = str(err)
    assert "ER001" in text and "403" in text and "denied" in text


def test_empty_message_string_is_preserved():
    err = KapApiError.from_body(404, '{"code":"ER005","message":""}')
    assert err.code == "ER005"
    assert err.message == ""


def test_response_error_is_a_kap_error():
    from kap.errors import KapError, KapResponseError

    err = KapResponseError(200, "bad shape")
    assert isinstance(err, KapError)
    assert err.status_code == 200
    assert "200" in str(err) and "bad shape" in str(err)
