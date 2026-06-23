from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["test", "production"]


@dataclass(frozen=True)
class ResolvedConfig:
    env: Environment
    base_url: str
    api_key: str
    token_refresh_skew_seconds: int


class Settings(BaseSettings):
    """KAP CLI configuration, loaded from environment / .env (prefix KAP_)."""

    model_config = SettingsConfigDict(
        env_prefix="KAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    active_env: str = "test"
    test_base_url: str = "https://vykapipreprod.mkk.com.tr"
    test_api_key: str = ""
    prod_base_url: str = "https://kapdatafeed.kap.org.tr"
    prod_api_key: str = ""
    token_refresh_skew_seconds: int = 60

    def resolve(self, env_override: str | None = None) -> ResolvedConfig:
        env = (env_override or self.active_env).strip().lower()
        if env == "test":
            name, base_url, api_key, key_var = (
                "test", self.test_base_url, self.test_api_key, "KAP_TEST_API_KEY",
            )
        elif env in ("production", "prod"):
            name, base_url, api_key, key_var = (
                "production", self.prod_base_url, self.prod_api_key, "KAP_PROD_API_KEY",
            )
        else:
            raise ValueError(f"Unknown env '{env}' (use 'test' or 'production').")

        if not api_key:
            raise ValueError(
                f"Missing API key for env '{name}'. Set {key_var} in your .env file."
            )

        return ResolvedConfig(
            env=name,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            token_refresh_skew_seconds=max(0, self.token_refresh_skew_seconds),
        )


def load_config(env_override: str | None = None) -> ResolvedConfig:
    return Settings().resolve(env_override)
