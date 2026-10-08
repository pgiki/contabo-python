"""Main Contabo client. Mirrors namecheap-python client shape."""

from __future__ import annotations

import time
import uuid
from functools import cached_property
from typing import Any, Self

import httpx
from dotenv import load_dotenv

from ._api.audits import AuditsAPI
from ._api.dns import DnsAPI
from ._api.domains import DomainsAPI
from ._api.handles import HandlesAPI
from ._api.ptr import PtrAPI
from .config import Config
from .errors import ConfigurationError, ContaboAPIError
from .logging import logger, set_log_level


class Contabo:
    """The main Contabo client.

    Examples:
        >>> c = Contabo()  # loads CONTABO_* from environment
        >>> zone = c.dns.get_or_create_zone("example.com")
        >>> c.dns.set_a_records(zone.zone_name, "example.com", "1.2.3.4")
        >>> c.dns.set("example.com", c.dns.builder().a("@","1.2.3.4"))
    """

    TOKEN_URL = "https://auth.contabo.com/auth/realms/contabo/protocol/openid-connect/token"  # noqa: S105
    API_BASE = "https://api.contabo.com/v1"

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_user: str | None = None,
        api_password: str | None = None,
        default_ttl: int | None = None,
        token_refresh_buffer: int | None = None,
        timeout: float | None = None,
        log_level: str | None = None,
        _http: httpx.Client | None = None,
    ):
        try:
            self.config = Config.from_env(
                client_id=client_id,
                client_secret=client_secret,
                api_user=api_user,
                api_password=api_password,
                default_ttl=default_ttl or 3600,
                token_refresh_buffer=token_refresh_buffer or 60,
                timeout=timeout or 30.0,
                log_level=(log_level or "INFO"),
            )
            set_log_level(self.config.log_level)
        except Exception as e:
            raise ConfigurationError(
                "Failed to load configuration. Set CONTABO_CLIENT_ID, "
                "CONTABO_CLIENT_SECRET, CONTABO_API_USER, CONTABO_API_PASSWORD "
                "or pass them to Contabo()."
            ) from e
        self._http = _http or httpx.Client(timeout=self.config.timeout)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    @classmethod
    def from_env_file(cls, path: str = ".env") -> Self:
        load_dotenv(path)
        return cls()

    # -- sub-APIs (same shape as Namecheap: domains/dns/users...) --
    @cached_property
    def dns(self) -> DnsAPI:
        return DnsAPI(self)

    @cached_property
    def domains(self) -> DomainsAPI:
        return DomainsAPI(self)

    @cached_property
    def handles(self) -> HandlesAPI:
        return HandlesAPI(self)

    @cached_property
    def ptr(self) -> PtrAPI:
        return PtrAPI(self)

    @cached_property
    def audits(self) -> AuditsAPI:
        return AuditsAPI(self)

    # -- auth --
    def authenticate(self) -> str:
        resp = self._http.post(
            self.TOKEN_URL,
            data={
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "username": self.config.api_user,
                "password": self.config.api_password,
                "grant_type": "password",
            },
        )
        if resp.status_code != 200:
            raise ContaboAPIError(
                "Authentication failed",
                resp.status_code,
                resp.text,
                help="Check CONTABO_CLIENT_ID/SECRET/API_USER/API_PASSWORD in my.contabo.com → API.",
            )
        payload = resp.json()
        self._access_token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 3600))
        return self._access_token

    def _token(self) -> str:
        if self._access_token is None or time.time() >= self._token_expires_at - self.config.token_refresh_buffer:
            self.authenticate()
        assert self._access_token is not None
        return self._access_token

    def _headers(self) -> dict[str, str]:
        # No Content-Type on bodyless requests: Contabo rejects empty JSON bodies.
        return {"Authorization": f"Bearer {self._token()}", "x-request-id": str(uuid.uuid4())}

    def _request(self, method: str, path: str, *, params=None, json=None) -> dict:
        resp = self._http.request(method, f"{self.API_BASE}{path}", headers=self._headers(), params=params, json=json)
        # Single retry on expired token
        if resp.status_code == 401:
            logger.debug("401 — refreshing token and retrying once")
            self.authenticate()
            resp = self._http.request(
                method, f"{self.API_BASE}{path}", headers=self._headers(), params=params, json=json
            )
        if not 200 <= resp.status_code < 300:
            raise ContaboAPIError(f"API request failed: {method} {path}", resp.status_code, resp.text)
        if not resp.content:
            return {}
        return resp.json()

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, payload: dict) -> dict:
        return self._request("POST", path, json=payload)

    def _patch(self, path: str, payload: dict) -> dict:
        return self._request("PATCH", path, json=payload)

    def _delete(self, path: str) -> None:
        self._request("DELETE", path)

    def _paginated_list(self, path: str, extra: dict[str, Any] | None = None) -> list[dict]:
        rows: list[dict] = []
        page, size = 1, 100
        # Caller filters must not hijack pagination cursors (infinite loop).
        filt = {k: v for k, v in (extra or {}).items() if k not in ("page", "size")}
        while True:
            params: dict[str, Any] = {"page": page, "size": size}
            params.update(filt)
            body = self._get(path, params=params)
            chunk = list(body.get("data") or [])
            rows.extend(chunk)
            total = int((body.get("_pagination") or {}).get("totalPages") or 1)
            if page >= total or not chunk:
                break
            page += 1
        return rows

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Contabo(api_user={self.config.api_user!r})>"
