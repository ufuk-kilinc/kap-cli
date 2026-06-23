from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import httpx

from kap.errors import KapApiError


def parse_jwt_expiry(jwt: str) -> int | None:
    """Return the `exp` claim (unix seconds) from a JWT, without verifying its signature."""
    try:
        parts = jwt.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)  # restore base64 padding
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        return int(exp) if exp is not None else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


class TokenProvider:
    """Mints the KAP JWT and caches it on disk so each CLI process reuses it."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        env: str,
        skew_seconds: int = 60,
        cache_dir: Path | None = None,
        http: httpx.Client | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._env = env
        self._skew = max(0, skew_seconds)
        self._cache_dir = cache_dir or (Path.home() / ".kap")
        self._cache_path = self._cache_dir / f"token-{env}.json"
        self._http = http or httpx.Client(timeout=30.0)

    def get_token(self) -> str:
        cached = self._read_cache()
        if cached and not self._is_expiring(cached["expires_at"]):
            return cached["token"]
        return self._mint()

    def invalidate(self) -> None:
        try:
            self._cache_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ── internals ────────────────────────────────────────────────────────────
    def _is_expiring(self, expires_at: int) -> bool:
        return time.time() >= (expires_at - self._skew)

    def _mint(self) -> str:
        resp = self._http.get(
            f"{self._base_url}/auth/generateToken", params={"apiKey": self._api_key}
        )
        if not resp.is_success:
            raise KapApiError.from_body(resp.status_code, resp.text)
        token = (resp.json() or {}).get("token")
        if not token:
            raise KapApiError(resp.status_code, None, f"generateToken returned no token: {resp.text}")
        # Fail safe on an unparseable exp: assume 1h so we re-mint soon.
        exp = parse_jwt_expiry(token) or int(time.time()) + 3600
        self._write_cache(token, exp)
        return token

    def _read_cache(self) -> dict | None:
        try:
            data = json.loads(self._cache_path.read_text())
            if isinstance(data, dict) and "token" in data and "expires_at" in data:
                return data
        except (OSError, ValueError):
            pass
        return None

    def _write_cache(self, token: str, expires_at: int) -> None:
        payload = json.dumps({"token": token, "expires_at": expires_at}).encode("utf-8")
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Create the token file with restrictive perms atomically — no window
            # where it is world-readable. The mode arg is ignored on Windows.
            fd = os.open(self._cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
        except OSError:
            pass  # cache is an optimization; never fail the call over it
