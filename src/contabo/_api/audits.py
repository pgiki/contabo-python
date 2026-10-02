"""Audit APIs (read-only history).

Endpoints: GET /v1/dns/zones/audits, GET /v1/dns/records/audits,
GET /v1/domains/audits, GET /v1/domains/handles/audits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import Contabo


class AuditsAPI:
    def __init__(self, client: Contabo):
        self._c = client

    def _list(self, path: str, **params: Any) -> list[dict]:
        return self._c._paginated_list(path, extra=params or None)

    def list_zones_audit(self, **params: Any) -> list[dict]:
        return self._list("/dns/zones/audits", **params)

    def list_records_audit(self, **params: Any) -> list[dict]:
        return self._list("/dns/records/audits", **params)

    def list_domains_audit(self, **params: Any) -> list[dict]:
        return self._list("/domains/audits", **params)

    def list_handles_audit(self, **params: Any) -> list[dict]:
        return self._list("/domains/handles/audits", **params)
