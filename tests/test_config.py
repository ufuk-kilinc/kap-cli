import pytest
from kap.config import Settings, ResolvedConfig


def _settings(**kw):
    # _env_file=None: ignore any real .env on disk during tests
    defaults = dict(test_api_key="", prod_api_key="", _env_file=None)
    defaults.update(kw)
    return Settings(**defaults)


def test_resolve_test_env_returns_test_url_and_key():
    cfg = _settings(active_env="test", test_api_key="tkey").resolve()
    assert isinstance(cfg, ResolvedConfig)
    assert cfg.env == "test"
    assert cfg.base_url == "https://vykapipreprod.mkk.com.tr"
    assert cfg.api_key == "tkey"


def test_resolve_production_aliases():
    for name in ("production", "prod"):
        cfg = _settings(active_env=name, prod_api_key="pkey").resolve()
        assert cfg.env == "production"
        assert cfg.base_url == "https://kapdatafeed.kap.org.tr"
        assert cfg.api_key == "pkey"


def test_env_override_beats_active_env():
    cfg = _settings(active_env="test", prod_api_key="pkey").resolve("production")
    assert cfg.env == "production"


def test_missing_api_key_raises_with_helpful_message():
    with pytest.raises(ValueError, match="KAP_TEST_API_KEY"):
        _settings(active_env="test", test_api_key="").resolve()


def test_unknown_env_raises():
    with pytest.raises(ValueError, match="Unknown env"):
        _settings(active_env="staging").resolve()


def test_base_url_trailing_slash_stripped():
    cfg = _settings(active_env="test", test_base_url="https://x/", test_api_key="k").resolve()
    assert cfg.base_url == "https://x"
