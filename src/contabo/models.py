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

    @field_validator("prio", "ttl", mode="before")
    @classmethod
    def _empty_to_default(cls, v: Any, info) -> Any:
        # The API returns explicit nulls for inapplicable fields (e.g. TXT
        # records carry ``prio: null``); coerce to the field defaults.
        if v in (None, ""):
            return 0 if info.field_name == "prio" else 3600
        return v

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
    """Availability result (`POST /v1/registries-domains/{domain}/check-availability`)."""

    domain: str = ""
    available: bool = False
    reason: str | None = None


class DomainDetails(ContaboModel):
    """SLD/TLD breakdown of a domain name."""

    sld: str = Field(alias="sld", default="")
    tld: str = Field(alias="tld", default="")
    domain_puny: str = Field(alias="domainPuny", default="")

    @property
    def fqdn(self) -> str:
        if self.sld and self.tld:
            return f"{self.sld}.{self.tld}"
        return self.domain_puny


class DomainHandles(ContaboModel):
    """Contact-handle IDs attached to a domain (owner/admin/tech/zone)."""

    owner: str = ""
    admin: str = ""
    tech: str = ""
    zone: str = ""

    def role_ids(self) -> dict[str, str]:
        return {"owner": self.owner, "admin": self.admin, "tech": self.tech, "zone": self.zone}


class Domain(ContaboModel):
    """Registered domain (`GET /v1/domains`, `GET /v1/domains/{domain}`)."""

    domain: str = Field(alias="domainName", default="")
    status: str | None = None
    tenant_id: str | None = Field(default=None, alias="tenantId")
    customer_id: str | None = Field(default=None, alias="customerId")
    nameservers: list[str] = Field(default_factory=list)
    handles: DomainHandles | None = None
    details: DomainDetails | None = Field(default=None, alias="domainDetails")
    registration_date: str | None = Field(default=None, alias="registrationDate")
    renewal_date: str | None = Field(default=None, alias="renewalDate")
    termination_date: str | None = Field(default=None, alias="terminationDate")
    cancel_date: str | None = Field(default=None, alias="cancelDate")
    dnssec_keys: list[str] = Field(default_factory=list, alias="dnssecKeys")
    transfer_out_confirmation: bool | None = Field(
        default=None, alias="transferOutConfirmation"
    )


class Handle(ContaboModel):
    """Contact handle (`/v1/domains/handles`). Replaces whoisguard/contacts."""

    id: str | int = Field(alias="handleId", default="")
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None


class Contact(ContaboModel):
    """Registrant-style contact (namecheap-style fields).

    Used for ``register()``/``set_contacts()`` input across backends:
    Contabo resolves/creates handles from it, WHMCS maps it to
    AddClient/AddContact params.
    """

    first_name: str = Field(alias="firstName", default="")
    last_name: str = Field(alias="lastName", default="")
    organization: str | None = Field(default=None, alias="organization")
    address1: str = Field(alias="address1", default="")
    address2: str | None = Field(default=None, alias="address2")
    city: str = Field(alias="city", default="")
    state_province: str = Field(default="", alias="stateProvince")
    postal_code: str = Field(default="", alias="postalCode")
    country: str = Field(alias="country", default="")
    phone: str = Field(alias="phone", default="")
    email: str = Field(alias="email", default="")


class DomainContacts(ContaboModel):
    """Contacts for the four domain roles."""

    registrant: Contact = Field(default_factory=Contact)
    tech: Contact = Field(default_factory=Contact)
    admin: Contact = Field(default_factory=Contact)
    aux_billing: Contact = Field(default_factory=Contact)


class EmailForward(ContaboModel):
    """Helper for fikashop-style email setup (client-side, no Contabo endpoint)."""

    mailbox: str
    forward_to: str = Field(alias="forwardTo", default="")
