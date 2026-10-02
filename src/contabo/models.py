"""Pydantic models for Contabo API responses. Mirrors namecheap models.py."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RecordType = Literal["A", "AAAA", "CAA", "CNAME", "MX", "NS", "SRV", "TXT", "PTR"]


class ContaboModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="allow")


class Zone(ContaboModel):
    """DNS zone (`GET /v1/dns/zones`)."""

    zone_name: str = Field(alias="zoneName")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    customer_id: str | None = Field(default=None, alias="customerId")


class ZoneRecord(ContaboModel):
    """DNS record. API uses `recordId`/`data`; SDK exposes `id`/`content` too."""

    id: int = Field(alias="recordId")
    name: str = ""
    type: str = "A"
    content: str = Field(default="", alias="data")
    ttl: int = 3600
    prio: int = 0
    port: str | None = None
    weight: str | None = None
    flag: str | None = None
    tag: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return str(v).upper() if v else v

    @field_validator("port", "weight", "flag", "tag", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> Any:
        return None if v in (None, "") else v

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> ZoneRecord:
        return cls.model_validate(raw)

    def to_dto(self) -> dict[str, Any]:
        """Plain dict with both `id`/`recordId` and `content`/`data` keys."""
        return {
            "id": self.id,
            "recordId": self.id,
            "name": self.name.rstrip("."),
            "type": self.type.upper(),
            "content": self.content,
            "data": self.content,
            "ttl": int(self.ttl or 3600),
            "prio": int(self.prio or 0),
            "port": self.port,
            "weight": self.weight,
            "flag": self.flag,
            "tag": self.tag,
        }


class PtrRecord(ContaboModel):
    ip_address: str = Field(alias="ipAddress", default="")
    hostname: str = ""


class DomainCheck(ContaboModel):
    """Result of `POST /v1/registries-domains/{domain}/check-availability`."""

    domain: str = ""
    available: bool = False


class Domain(ContaboModel):
    domain: str = Field(alias="domainName", default="")
    status: str | None = None


class Handle(ContaboModel):
    """Contact handle (`/v1/domains/handles`). Replaces whoisguard/contacts."""

    id: str | int = Field(alias="handleId", default="")
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None


class EmailForward(ContaboModel):
    """Helper for fikashop-style email setup (client-side, no Contabo endpoint)."""

    mailbox: str
    forward_to: str = Field(alias="forwardTo", default="")
