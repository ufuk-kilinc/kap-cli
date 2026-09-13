import pytest
from kap.config import Settings, ResolvedConfig


def _settings(**kw):
    # _env_file=None: ignore any real .env on disk during tests
    defaults = dict(test_api_key="", prod_api_key="", _env_file=None)
    defaults.update(kw)
    return Settings(**defaults)


def test_resolve_refuses_test_even_when_its_key_is_configured():
    with pytest.raises(ValueError, match="Production KAP API"):
        _settings(active_env="test", test_api_key="tkey").resolve()


def test_resolve_production_aliases():
    for name in ("production", "prod"):
        cfg = _settings(active_env=name, prod_api_key="pkey").resolve()
        assert cfg.env == "production"
        assert cfg.base_url == "https://kapdatafeed.kap.org.tr"
        assert cfg.api_key == "pkey"


def test_production_override_beats_active_env():
    cfg = _settings(active_env="test", prod_api_key="pkey").resolve("production")
    assert cfg.env == "production"


def test_missing_api_key_raises_with_helpful_message():
    with pytest.raises(ValueError, match="KAP_PROD_API_KEY"):
        _settings(active_env="production", prod_api_key="").resolve()


def test_unknown_env_raises():
    with pytest.raises(ValueError, match="Production KAP API"):
        _settings(active_env="staging").resolve()


@pytest.mark.parametrize("base_url", [
    "http://kapdatafeed.kap.org.tr",
    "https://evil.example",
    "https://kapdatafeed.kap.org.tr/unexpected-path",
])
def test_resolve_refuses_non_production_destination(base_url):
    with pytest.raises(ValueError, match="Production KAP API"):
        _settings(active_env="production", prod_base_url=base_url, prod_api_key="k").resolve()
