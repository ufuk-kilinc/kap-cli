from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["test", "production"]
PRODUCTION_KAP_ORIGIN = "https://kapdatafeed.kap.org.tr"

# Config is read from the user's home config (~/.kap/.env) plus real environment
# variables (which take priority). We deliberately do NOT read a .env from the
# current working directory: an installed `kap` is run from anywhere, and loading
# a cwd .env would let any untrusted directory (a cloned repo, a downloads folder)
# redirect KAP_*_BASE_URL and exfiltrate the API key. Dev overrides use real env
# vars (e.g. `set KAP_ACTIVE_ENV=test`), which are not attacker-controlled by cwd.
_HOME_ENV = Path.home() / ".kap" / ".env"


@dataclass(frozen=True)
class ResolvedConfig:
    env: Environment
    base_url: str
    api_key: str
    token_refresh_skew_seconds: int


def require_production_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "kapdatafeed.kap.org.tr"
        or parsed.port is not None
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Every KAP API operation must use the Production KAP API origin "
            f"{PRODUCTION_KAP_ORIGIN}/."
        )
    return normalized


class Settings(BaseSettings):
    """KAP CLI configuration, loaded from environment / .env (prefix KAP_)."""

    model_config = SettingsConfigDict(
        env_prefix="KAP_",
        env_file=str(_HOME_ENV),  # home only — never an untrusted cwd .env (see note above)
        env_file_encoding="utf-8",
        extra="ignore",
    )

    active_env: str = "production"
    test_base_url: str = "https://vykapipreprod.mkk.com.tr"
    test_api_key: str = ""
    prod_base_url: str = "https://kapdatafeed.kap.org.tr"
    prod_api_key: str = ""
    token_refresh_skew_seconds: int = 60

    def resolve(self, env_override: str | None = None) -> ResolvedConfig:
        env = (env_override or self.active_env).strip().lower()
        if env in ("production", "prod"):
            name, base_url, api_key, key_var = (
                "production", self.prod_base_url, self.prod_api_key, "KAP_PROD_API_KEY",
            )
        else:
            raise ValueError(
                f"Every KAP API operation must use the Production KAP API; got '{env}'."
            )

        base_url = require_production_base_url(base_url)

        if not api_key:
            raise ValueError(
                f"Missing API key for env '{name}'. Set {key_var} in your .env file."
            )

        return ResolvedConfig(
            env=name,
            base_url=base_url,
            api_key=api_key,
            token_refresh_skew_seconds=max(0, self.token_refresh_skew_seconds),
        )


def load_config(env_override: str | None = None) -> ResolvedConfig:
    return Settings().resolve(env_override)
