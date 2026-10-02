"""Client configuration. Mirrors namecheap Config.from_env pattern."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Config(BaseModel):
    """Contabo OAuth2 credentials + client options."""

    model_config = ConfigDict(str_strip_whitespace=True)

    client_id: str = Field(description="OAuth2 client ID")
    client_secret: str = Field(description="OAuth2 client secret")
    api_user: str = Field(description="Contabo login email (API user)")
    api_password: str = Field(description="Contabo API password (set in control panel)")
    default_ttl: int = Field(default=3600, description="Default TTL for new records")
    token_refresh_buffer: int = Field(default=60, description="Refresh seconds before expiry")
    timeout: float = Field(default=30.0, description="HTTP timeout seconds")
    log_level: str = Field(default="INFO")

    @field_validator("client_id", "client_secret", "api_user", "api_password")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty")
        return v

    @classmethod
    def from_env(cls, **overrides: Any) -> Config:
        """Load from CONTABO_* env vars with explicit overrides.

        SDK does not read `.env` implicitly — use `Contabo.from_env_file()`.
        """

        def get(key: str, env: str, default: Any = None) -> Any:
            if key in overrides and overrides[key] is not None:
                return overrides[key]
            return os.environ.get(env, default)

        return cls(
            client_id=get("client_id", "CONTABO_CLIENT_ID", ""),
            client_secret=get("client_secret", "CONTABO_CLIENT_SECRET", ""),
            api_user=get("api_user", "CONTABO_API_USER", ""),
            api_password=get("api_password", "CONTABO_API_PASSWORD", ""),
            default_ttl=int(get("default_ttl", "CONTABO_DEFAULT_TTL", 3600)),
            token_refresh_buffer=int(get("token_refresh_buffer", "CONTABO_TOKEN_BUFFER", 60)),
            timeout=float(get("timeout", "CONTABO_TIMEOUT", 30.0)),
            log_level=str(get("log_level", "CONTABO_LOG_LEVEL", "INFO")).upper(),
        )
