"""Domain management, namecheap-style names over WHMCS (whmcspy).

Same class shape and models as :class:`DomainsAPI` (Contabo backend) so
callers can swap backends without code changes. WHMCS-native errors
(``whmcspy.Error`` / ``MissingPermission``) are translated to
:class:`ContaboAPIError` — one ``except`` path for all backends.

Availability parsing reuses the same heuristics fikashop has run in
production (``DomainWhois`` status normalization).
"""

from __future__ import annotations

import logging
from typing import Any

from ..errors import ContaboAPIError, NotSupportedError
from ..models import Contact, Domain, DomainCheck, DomainContacts

logger = logging.getLogger(__name__)


def _translate_errors(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        from whmcspy import exceptions as whmcs_exceptions

        try:
            return func(*args, **kwargs)
        except (whmcs_exceptions.Error, whmcs_exceptions.MissingPermission) as e:
            raise ContaboAPIError(f"WHMCS API error: {e}", 0, "") from e

    return wrapper


def _normalize_whois_status(payload: dict[str, Any]) -> str | None:
    """Vendor WHOIS payload → ``available`` | ``unavailable`` | None."""
    candidates = [
        payload.get("status"),
        payload.get("domainstatus"),
        payload.get("availability"),
        payload.get("domain_status"),
    ]
    raw = next((str(v).strip().lower() for v in candidates if v not in (None, "") and str(v).strip()), "")
    if not raw:
        return None
    if raw in {"available", "unavailable"}:
        return raw
    if any(x in raw for x in ("not available", "unavailable", "taken", "registered", "exists")):
        return "unavailable"
    if any(x in raw for x in ("available", "free")):
        return "available"
    return None


def _client_id(created: Any) -> int:
    """whmcspy ``add_client`` returns a bare ``clientid`` int (not a payload)."""
    if isinstance(created, dict):
        return int(created.get("clientid", 0))
    return int(created)


def _contact_from_row(row: dict[str, Any]) -> Contact:
    return Contact.model_validate(
        {
            "firstName": row.get("firstname") or row.get("first_name") or "",
            "lastName": row.get("lastname") or row.get("last_name") or "",
            "organization": row.get("companyname") or row.get("company") or row.get("organisation"),
            "address1": row.get("address1") or "",
            "address2": row.get("address2"),
            "city": row.get("city") or "",
            "stateProvince": row.get("state") or row.get("state_province") or "",
            "postalCode": row.get("postcode") or row.get("postal_code") or "",
            "country": row.get("country") or "",
            "phone": row.get("phonenumber") or row.get("phone") or "",
            "email": row.get("email") or "",
        }
    )


class WhmcsDomains:
    """Namecheap-style domain API backed by WHMCS.

    Requires the ``whmcs`` extra (``pip install contabo-python[whmcs]``).
    """

    def __init__(self, api_url: str, identifier: str, secret: str, *, timeout: float = 30.0):
        try:
            from whmcspy import WHMCS
        except ImportError as e:
            raise ImportError(
                "WhmcsDomains needs the whmcs extra: pip install contabo-python[whmcs]"
            ) from e
        base = (api_url or "").rstrip("/")
        if base and not base.rsplit("/", 1)[-1].endswith("api.php"):
            base = f"{base}/includes/api.php"
        self._w = WHMCS(base, identifier or "", secret or "")
        self.timeout = timeout

    # -- availability --
    @_translate_errors
    def check(self, *domains: str) -> list[DomainCheck]:
        out: list[DomainCheck] = []
        for raw in domains:
            name = raw.strip().rstrip(".").lower()
            if not name:
                continue
            payload = self._w.call("DomainWhois", domain=name)
            status = _normalize_whois_status(payload if isinstance(payload, dict) else {})
            out.append(
                DomainCheck(
                    domain=name,
                    available=status == "available",
                    reason=None if status else "whois status inconclusive",
                )
            )
        return out

    # -- listing / info --
    @_translate_errors
    def list(self, client_id: int | None = None, **params: Any) -> list[Domain]:
        """List domains for a WHMCS client (``client_id`` required by WHMCS)."""
        if client_id is None:
            raise ValueError("list() requires client_id on the WHMCS backend.")
        payload = self._w.get_clients_domains(clientid=int(client_id), **params)
        rows = payload.get("domains", {}).get("domain", []) if isinstance(payload, dict) else []
        if isinstance(rows, dict):
            rows = [rows]
        return [
            Domain.model_validate(
                {
                    "domainName": r.get("domain") or r.get("domainname") or "",
                    "status": r.get("status"),
                    "registrationDate": r.get("registrationdate"),
                    "renewalDate": r.get("nextduedate") or r.get("expirydate"),
                    "nameservers": [ns for ns in [r.get(f"nameserver{i}") for i in range(1, 6)] if ns],
                }
            )
            for r in rows
            if isinstance(r, dict)
        ]

    @_translate_errors
    def get_info(self, domain: str, **params: Any) -> Domain:
        name = domain.strip().rstrip(".").lower()
        payload = self._w.call("DomainWhois", domain=name, **params)
        data = payload if isinstance(payload, dict) else {}
        return Domain.model_validate(
            {
                "domainName": name,
                "status": data.get("status") or data.get("domainstatus"),
                "registrationDate": data.get("registrationdate") or data.get("created"),
                "renewalDate": data.get("expirydate") or data.get("expiry"),
                "nameservers": [ns for ns in [data.get(f"nameserver{i}") for i in range(1, 6)] if ns],
            }
        )

    get = get_info

    # -- contacts --
    @_translate_errors
    def get_contacts(self, domain: str, *, client_id: int | None = None) -> DomainContacts:
        """Contacts for a domain's WHMCS client (``client_id`` required)."""
        if client_id is None:
            raise ValueError("get_contacts() requires client_id on the WHMCS backend.")
        clients = self._w.call("GetClients", clientid=int(client_id))
        rows = (clients.get("clients", {}) or {}).get("client", [])
        row = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else {})
        registrant = _contact_from_row(row if isinstance(row, dict) else {})
        contacts = self._w.call("GetContacts", clientid=int(client_id))
        crows = (contacts.get("contacts", {}) or {}).get("contact", [])
        crows = crows if isinstance(crows, list) else ([crows] if isinstance(crows, dict) else [])
        tech = _contact_from_row(crows[0]) if crows else Contact()
        return DomainContacts(registrant=registrant, tech=tech, admin=tech, aux_billing=Contact())

    @_translate_errors
    def set_contacts(
        self, domain: str, contact: Contact | dict[str, Any], *, client_id: int | None = None
    ) -> bool:
        """Update the WHMCS client record + first contact (``client_id`` required)."""
        if client_id is None:
            raise ValueError("set_contacts() requires client_id on the WHMCS backend.")
        data = contact.model_dump(by_alias=True) if isinstance(contact, Contact) else dict(contact)
        params = {
            "firstname": data.get("firstName", ""),
            "lastname": data.get("lastName", ""),
            "companyname": data.get("organization") or "",
            "address1": data.get("address1", ""),
            "city": data.get("city", ""),
            "state": data.get("stateProvince", ""),
            "postcode": data.get("postalCode", ""),
            "country": data.get("country", ""),
            "phonenumber": data.get("phone", ""),
            "email": data.get("email", ""),
        }
        self._w.call("UpdateClient", clientid=int(client_id), **{k: v for k, v in params.items() if v})
        return True

    def get_tld_list(self) -> list:
        raise NotSupportedError(
            "get_tld_list() has no WHMCS endpoint.",
            alternative="Derive TLDs from GetTLDPricing keys.",
        )

    # -- registration / transfer / renewal --
    @_translate_errors
    def register(
        self,
        domain: str,
        *,
        contact: Contact | dict[str, Any],
        client_id: int | None = None,
        nameservers: list[str] | None = None,
        auth_code: str | None = None,
        years: int = 1,
        whois_protection: bool = True,
        **kwargs: Any,
    ) -> Domain:
        """Register (or transfer, with ``auth_code``) via ``AddOrder``.

        Without ``client_id`` a client is created from ``contact`` first.
        ``whois_protection`` maps to the ``idprotection`` order flag.
        """
        name = domain.strip().rstrip(".").lower()
        data = contact.model_dump(by_alias=True) if isinstance(contact, Contact) else dict(contact)
        if client_id is None:
            password = kwargs.pop("password", None) or data.get("phone", "")
            created = self._w.add_client(
                data.get("firstName", ""),
                data.get("lastName", ""),
                data.get("email", ""),
                data.get("address1", ""),
                data.get("city", ""),
                data.get("stateProvince", ""),
                data.get("postalCode", ""),
                data.get("country", ""),
                data.get("phone", ""),
                password,
            )
            client_id = _client_id(created)
        params: dict[str, Any] = {"regperiod": int(years)}
        for i, ns in enumerate(nameservers or [], start=1):
            params[f"nameserver{i}"] = ns
        if auth_code:
            params["eppcode"] = auth_code
            params["domaintype"] = "transfer"
        if whois_protection:
            params["idprotection"] = True
        params.update(kwargs)
        raw = self._w.add_order(clientid=int(client_id), domains=[name], **params)
        order_id = raw.get("orderid") if isinstance(raw, dict) else None
        logger.info("WHMCS AddOrder for %s → order %s", name, order_id)
        return Domain.model_validate({"domainName": name, "status": "pending"})

    @_translate_errors
    def renew(self, domain: str, *, domain_id: int | None = None, **params: Any) -> dict[str, Any]:
        """Renew via ``UpdateClientDomain`` (verified live before relying)."""
        if domain_id is None:
            raise ValueError("renew() requires domain_id (WHMCS domainid) on this backend.")
        return self._w.update_client_domain(domain_id, **params)

    def lock(self, domain: str) -> bool:
        raise NotSupportedError(
            f"lock({domain}) is unverified on WHMCS (registrar lock varies by TLD).",
            alternative="Use the WHMCS admin or UpdateClientDomain if supported.",
        )

    def unlock(self, domain: str) -> bool:
        raise NotSupportedError(
            f"unlock({domain}) is unverified on WHMCS (registrar lock varies by TLD).",
            alternative="Use the WHMCS admin or UpdateClientDomain if supported.",
        )

    def suggest(self, domain: str, **params: Any) -> list[dict]:
        raise NotSupportedError(
            "WHMCS has no domain-suggest endpoint.",
            alternative="Use the Contabo backend suggest() (experimental).",
        )

    def pending(self, **params: Any) -> list[dict]:
        raise NotSupportedError(
            "WHMCS has no pending-actions endpoint.",
            alternative="Use the Contabo backend pending() (experimental).",
        )

    # -- client management (no namecheap equivalent; ported from fikashop) --
    @_translate_errors
    def ensure_client(
        self, contact: Contact | dict[str, Any], *, password: str | None = None
    ) -> int:
        """Find client by email or create it; returns ``clientid``."""
        data = contact.model_dump(by_alias=True) if isinstance(contact, Contact) else dict(contact)
        email = (data.get("email") or "").strip().lower()
        if email:
            found = self._w.call("GetClients", search=email)
            rows = (found.get("clients", {}) or {}).get("client", [])
            rows = rows if isinstance(rows, list) else ([rows] if isinstance(rows, dict) else [])
            for row in rows:
                if str(row.get("email", "")).strip().lower() == email:
                    return int(row.get("id", 0))
        created = self._w.add_client(
            data.get("firstName", ""),
            data.get("lastName", ""),
            data.get("email", ""),
            data.get("address1", ""),
            data.get("city", ""),
            data.get("stateProvince", ""),
            data.get("postalCode", ""),
            data.get("country", ""),
            data.get("phone", ""),
            password if password is not None else data.get("phone", ""),
        )
        return _client_id(created)

    @_translate_errors
    def ensure_contact(self, client_id: int, contact: Contact | dict[str, Any]) -> int:
        """Find contact by email or create it; returns ``contactid``."""
        data = contact.model_dump(by_alias=True) if isinstance(contact, Contact) else dict(contact)
        email = (data.get("email") or "").strip().lower()
        existing = self._w.call("GetContacts", clientid=int(client_id))
        rows = (existing.get("contacts", {}) or {}).get("contact", [])
        rows = rows if isinstance(rows, list) else ([rows] if isinstance(rows, dict) else [])
        for row in rows:
            if email and str(row.get("email", "")).strip().lower() == email:
                cid = row.get("id") or row.get("contactid")
                if cid:
                    return int(cid)
        created = self._w.call(
            "AddContact",
            clientid=int(client_id),
            firstname=data.get("firstName", ""),
            lastname=data.get("lastName", ""),
            companyname=data.get("organization") or "",
            email=data.get("email", ""),
            address1=data.get("address1", ""),
            city=data.get("city", ""),
            state=data.get("stateProvince", ""),
            postcode=data.get("postalCode", ""),
            country=data.get("country", ""),
            phonenumber=data.get("phone", ""),
        )
        return int(created.get("contactid", 0))

    # -- low-level domain ops (used by registrar integrations) --
    @_translate_errors
    def call(self, action: str, **params: Any) -> Any:
        """Raw ``WHMCS.call(action, **params)`` with translated errors."""
        return self._w.call(action, **params)

    @_translate_errors
    def whois(self, domain: str, **params: Any) -> dict[str, Any]:
        """Raw ``DomainWhois`` payload for ``domain``."""
        payload = self._w.call("DomainWhois", domain=domain.strip().rstrip(".").lower(), **params)
        return payload if isinstance(payload, dict) else {}

    @_translate_errors
    def update_nameservers(self, domain: str, nameservers: list[str], **params: Any) -> dict[str, Any]:
        """``DomainUpdateNameservers`` for ``domain`` (plus optional ``domainid``)."""
        body: dict[str, Any] = {
            f"ns{i}": ns for i, ns in enumerate(nameservers, start=1)
        }
        body.update(params)
        payload = self._w.call(
            "DomainUpdateNameservers", domain=domain.strip().rstrip(".").lower(), **body
        )
        return payload if isinstance(payload, dict) else {}

    @_translate_errors
    def tld_pricing(self, currency_id: int = 1) -> dict[str, Any]:
        """Raw ``GetTLDPricing`` payload."""
        payload = self._w.call("GetTLDPricing", currencyid=int(currency_id))
        return payload if isinstance(payload, dict) else {}
