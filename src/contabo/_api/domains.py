"""Domain management, namecheap-style names over the Contabo API.

Method map (``namecheap.DomainsAPI`` → Contabo):
  check/list/get_info/get_contacts/register → native endpoints (adapted).
  renew/lock/unlock/set_contacts/get_tld_list → :class:`NotSupportedError`
  (no Contabo endpoint exists; each names the alternative).
  cancel/revoke_cancellation/get_auth_code/transfer-out → Contabo-native
  extras with no namecheap equivalent.
  suggest/pending → documented in the API sidebar but absent from the
  published OpenAPI spec; paths below are marked experimental and must be
  confirmed against a live account (probe live, degrade on 404/405).

Endpoints (verified via cntb OpenAPI unless noted):
  POST /v1/registries-domains/{domain}/check-availability
  GET /v1/domains (+ sld/tld/status/orderBy), POST /v1/domains,
  GET/PATCH /v1/domains/{domain}, POST .../cancel|revoke-cancellation,
  POST .../generate-auth-code, POST|DELETE .../transfer-out
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..errors import ContaboAPIError, NotSupportedError
from ..models import Contact, Domain, DomainCheck, DomainContacts, DomainHandles

if TYPE_CHECKING:
    from ..client import Contabo

logger = logging.getLogger(__name__)

# Unverified: present in the api.contabo.com sidebar, absent from cntb's
# OpenAPI spec. Confirm live before relying on these.
_SUGGEST_PATH = "/domains/suggest"
_PENDING_PATH = "/domains/pending"


def _seg(domain: str) -> str:
    return quote(domain.strip().rstrip(".").lower(), safe=".-")


class DomainsAPI:
    """Domain management operations (Contabo backend)."""

    def __init__(self, client: Contabo):
        self._c = client

    # -- availability --
    def check(self, *domains: str) -> list[DomainCheck]:
        """Check domain availability, one result per input domain.

        Raises:
            ContaboAPIError: On 402/403 — domain features require at least
                one other active Contabo product on the account.
        """
        out: list[DomainCheck] = []
        for raw in domains:
            name = raw.strip().rstrip(".").lower()
            if not name:
                continue
            try:
                body = self._c._post(f"/registries-domains/{_seg(name)}/check-availability", {})
            except ContaboAPIError as e:
                if e.status_code in (402, 403):
                    raise ContaboAPIError(
                        f"Domain check refused for {name}: account needs at least "
                        "one other active Contabo product.",
                        e.status_code,
                        e.response_text,
                    ) from e
                raise
            data = body.get("data", [])
            row = data[0] if data and isinstance(data[0], dict) else {}
            out.append(
                DomainCheck(
                    domain=name,
                    available=bool(row.get("available", False)),
                    reason=row.get("reason") or row.get("message"),
                )
            )
        return out

    # -- listing / info --
    def list(self, **filters: Any) -> list[Domain]:
        """List domains in your account.

        Accepts Contabo filters (``sld``, ``tld``, ``status``, ``orderBy``);
        results across all pages are collected.
        """
        rows = self._c._paginated_list("/domains", extra=filters or None)
        return [Domain.model_validate(r) for r in rows]

    def get_info(self, domain: str) -> Domain:
        """Detailed info about a domain (status, dates, nameservers, handles)."""
        body = self._c._get(f"/domains/{_seg(domain)}")
        rows = body.get("data") or []
        if not rows:
            raise ContaboAPIError(f"Domain not found: {domain}", 404, "")
        return Domain.model_validate(rows[0])

    get = get_info  # alias mirroring the thin client this replaces

    # -- contacts (via handles) --
    def get_contacts(self, domain: str) -> DomainContacts:
        """Contacts for the four roles, resolving handle IDs via HandlesAPI."""
        info = self.get_info(domain)
        handles = info.handles or DomainHandles()
        resolved: dict[str, Contact] = {}
        for role, handle_id in handles.role_ids().items():
            if not handle_id:
                resolved[role] = Contact()
                continue
            try:
                handle = self._c.handles.get(handle_id)
            except ContaboAPIError as e:
                if e.status_code == 404:
                    resolved[role] = Contact()
                    continue
                raise
            resolved[role] = Contact.model_validate(
                {
                    "firstName": handle.first_name or "",
                    "lastName": handle.last_name or "",
                    "email": handle.email or "",
                }
            )
        return DomainContacts(
            registrant=resolved["owner"],
            tech=resolved["tech"],
            admin=resolved["admin"],
            aux_billing=resolved["zone"],
        )

    def set_contacts(self, domain: str, contact: Contact | dict[str, Any]) -> bool:
        """Not supported: Contabo has no set-contacts endpoint (use handles)."""
        raise NotSupportedError(
            f"set_contacts({domain}) has no Contabo endpoint.",
            alternative="Update the domain's handles (owner/admin/tech/zone) instead.",
        )

    def get_tld_list(self) -> list:
        """Not supported: Contabo publishes 300+ TLDs but no TLD-list endpoint."""
        raise NotSupportedError(
            "get_tld_list() has no Contabo endpoint.",
            alternative="See https://contabo.com/en/domains for supported TLDs.",
        )

    # -- registration / transfer --
    def register(
        self,
        domain: str,
        *,
        contact: DomainHandles | Contact | dict[str, Any],
        nameservers: list[str] | None = None,
        auth_code: str | None = None,
        years: int = 1,
        whois_protection: bool = True,
    ) -> Domain:
        """Register a new domain or transfer one in (charges the account).

        ``contact`` is handle IDs (``DomainHandles`` or an
        owner/admin/tech/zone dict) or a ``Contact``/contact-fields dict,
        in which case one handle per role is created first.
        ``auth_code`` transfers an existing domain in (it must be unlocked
        with privacy disabled at the losing registrar). ``years`` and
        ``whois_protection`` are accepted for namecheap parity but Contabo
        has no equivalent and they are ignored (warned, never silent).
        """
        name = domain.strip().rstrip(".").lower()
        if years != 1:
            logger.warning("Contabo has no registration-period option; ignoring years=%s", years)
        if not whois_protection:
            logger.warning("Contabo has no WhoisGuard toggle; ignoring whois_protection=False")
        handles = self._resolve_handles(contact)
        payload: dict[str, Any] = {
            "domain": name,
            "handles": {
                "owner": handles.owner,
                "admin": handles.admin,
                "tech": handles.tech,
                "zone": handles.zone,
            },
            # Nameserver entries follow the cntb shape: one entry per
            # hostname; dicts pass through verbatim for ipV4/ipV6 glue.
            "nameservers": [
                ns if isinstance(ns, dict) else {"hostname": [ns]}
                for ns in (nameservers or [])
            ],
        }
        if auth_code:
            payload["authCode"] = auth_code
        body = self._c._post("/domains", payload)
        rows = body.get("data") or []
        return Domain.model_validate(rows[0] if rows else {"domainName": name})

    def _resolve_handles(self, contact: DomainHandles | Contact | dict[str, Any]) -> DomainHandles:
        if isinstance(contact, DomainHandles):
            handles = contact
        elif isinstance(contact, dict) and set(contact) <= {"owner", "admin", "tech", "zone"}:
            handles = DomainHandles.model_validate(contact)
        else:
            data = contact.model_dump(by_alias=True) if isinstance(contact, Contact) else dict(contact)
            handle_ids: dict[str, str] = {}
            for role in ("owner", "admin", "tech", "zone"):
                created = self._c.handles.create(dict(data))
                handle_ids[role] = str(created.id)
            handles = DomainHandles.model_validate(handle_ids)
        missing = [role for role, hid in handles.role_ids().items() if not hid]
        if missing:
            raise ValueError(f"Missing handle IDs for roles: {', '.join(missing)}")
        return handles

    def renew(self, domain: str, *, years: int = 1) -> dict[str, Any]:
        """Not supported: Contabo has no domain-renewal endpoint."""
        raise NotSupportedError(
            f"renew({domain}) has no Contabo endpoint.",
            alternative="Renew in the Contabo Customer Control Panel.",
        )

    def lock(self, domain: str) -> bool:
        """Not supported: Contabo has no registrar-lock endpoint."""
        raise NotSupportedError(
            f"lock({domain}) has no Contabo endpoint.",
            alternative="Manage transfer locks in the Control Panel.",
        )

    def unlock(self, domain: str) -> bool:
        """Not supported: Contabo has no registrar-lock endpoint."""
        raise NotSupportedError(
            f"unlock({domain}) has no Contabo endpoint.",
            alternative="Manage transfer locks in the Control Panel.",
        )

    # -- experimental (unverified paths; probe live, degrade) --
    def suggest(self, domain: str, **params: Any) -> list[dict]:
        """Suggest domains (experimental: path unconfirmed against live API)."""
        body = self._c._get(_SUGGEST_PATH, params={"domain": domain, **params})
        return list(body.get("data") or [])

    def pending(self, **params: Any) -> list[dict]:
        """Pending domain actions (experimental: path unconfirmed against live API)."""
        body = self._c._get(_PENDING_PATH, params=params or None)
        return list(body.get("data") or [])

    # -- Contabo-native extras (no namecheap equivalent) --
    def create(self, payload: dict[str, Any]) -> Domain:
        """Raw ``POST /v1/domains`` (create or transfer); prefers ``register``."""
        body = self._c._post("/domains", payload)
        rows = body.get("data") or []
        return Domain.model_validate(rows[0] if rows else payload)

    def update(self, domain: str, payload: dict[str, Any]) -> Domain:
        """``PATCH /v1/domains/{domain}``."""
        body = self._c._patch(f"/domains/{_seg(domain)}", payload)
        rows = body.get("data") or []
        return Domain.model_validate(rows[0] if rows else {"domainName": domain})

    def cancel(self, domain: str, payload: dict[str, Any] | None = None) -> dict:
        """``POST /v1/domains/{domain}/cancel``."""
        return self._c._post(f"/domains/{_seg(domain)}/cancel", payload or {})

    def revoke_cancellation(self, domain: str) -> dict:
        """``POST /v1/domains/{domain}/revoke-cancellation``."""
        return self._c._post(f"/domains/{_seg(domain)}/revoke-cancellation", {})

    def get_auth_code(self, domain: str) -> dict:
        """``POST /v1/domains/{domain}/generate-auth-code``."""
        return self._c._post(f"/domains/{_seg(domain)}/generate-auth-code", {})

    def confirm_transfer_out(self, domain: str) -> dict:
        """``POST /v1/domains/{domain}/transfer-out``."""
        return self._c._post(f"/domains/{_seg(domain)}/transfer-out", {})

    def revoke_transfer_out(self, domain: str) -> None:
        """``DELETE /v1/domains/{domain}/transfer-out``."""
        self._c._delete(f"/domains/{_seg(domain)}/transfer-out")
