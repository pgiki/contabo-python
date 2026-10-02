"""Domains API. Contabo-native (no fake Namecheap parity).

Endpoints (cntb OpenAPI):
  POST /v1/registries-domains/{domain}/check-availability
  GET /v1/domains, POST /v1/domains, GET/PATCH /v1/domains/{domain}
  POST /v1/domains/{domain}/cancel, POST .../revoke-cancellation
  POST /v1/domains/{domain}/generate-auth-code
  POST/DELETE /v1/domains/{domain}/transfer-out
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..models import Domain, DomainCheck

if TYPE_CHECKING:
    from ..client import Contabo


class DomainsAPI:
    def __init__(self, client: Contabo):
        self._c = client

    def check(self, *domains: str) -> list[DomainCheck]:
        out: list[DomainCheck] = []
        for d in domains:
            name = d.strip().rstrip(".")
            body = self._c._post(f"/registries-domains/{quote(name, safe='.-')}/check-availability", {})
            data = body.get("data", [])
            if data and isinstance(data[0], dict) and "available" in data[0]:
                out.append(DomainCheck.model_validate({"domain": name, **data[0]}))
            else:
                out.append(DomainCheck(domain=name, available=False))
        return out

    def suggest(self, domain: str, **params: Any) -> list[dict]:
        body = self._c._get(f"/registries-domains/{quote(domain.strip().rstrip('.'), safe='.-')}/suggest",
                            params=params or None)
        return list(body.get("data") or [])

    def list(self, **params: Any) -> list[Domain]:
        rows = self._c._paginated_list("/domains", extra=params or None)
        return [Domain.model_validate(r) for r in rows]

    def get(self, domain: str) -> Domain:
        body = self._c._get(f"/domains/{quote(domain.strip().rstrip('.'), safe='.-')}")
        rows = body.get("data") or []
        return Domain.model_validate(rows[0] if rows else {"domainName": domain})

    get_info = get  # namecheap-style alias

    def create(self, payload: dict[str, Any]) -> Domain:
        body = self._c._post("/domains", payload)
        rows = body.get("data") or []
        return Domain.model_validate(rows[0] if rows else payload)

    register = create  # namecheap-style alias (create or transfer)

    def update(self, domain: str, payload: dict[str, Any]) -> Domain:
        body = self._c._patch(f"/domains/{quote(domain.strip().rstrip('.'), safe='.-')}", payload)
        rows = body.get("data") or []
        return Domain.model_validate(rows[0] if rows else {"domainName": domain})

    def cancel(self, domain: str, payload: dict[str, Any] | None = None) -> dict:
        return self._c._post(f"/domains/{quote(domain.strip().rstrip('.'), safe='.-')}/cancel", payload or {})

    def revoke_cancellation(self, domain: str) -> dict:
        return self._c._post(f"/domains/{quote(domain.strip().rstrip('.'), safe='.-')}/revoke-cancellation", {})

    def get_auth_code(self, domain: str) -> dict:
        return self._c._post(f"/domains/{quote(domain.strip().rstrip('.'), safe='.-')}/generate-auth-code", {})

    def confirm_transfer_out(self, domain: str) -> dict:
        return self._c._post(f"/domains/{quote(domain.strip().rstrip('.'), safe='.-')}/transfer-out", {})

    def revoke_transfer_out(self, domain: str) -> None:
        self._c._delete(f"/domains/{quote(domain.strip().rstrip('.'), safe='.-')}/transfer-out")
