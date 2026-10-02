"""PTR records API.

Endpoints: GET/POST /v1/dns/ptrs, GET/PUT/DELETE /v1/dns/ptrs/{ip}.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..models import PtrRecord

if TYPE_CHECKING:
    from ..client import Contabo


class PtrAPI:
    def __init__(self, client: Contabo):
        self._c = client

    def list(self, **params: Any) -> list[PtrRecord]:
        rows = self._c._paginated_list("/dns/ptrs", extra=params or None)
        return [PtrRecord.model_validate(r) for r in rows]

    def get(self, ip: str) -> PtrRecord:
        body = self._c._get(f"/dns/ptrs/{quote(ip, safe=':.')}")
        rows = body.get("data") or []
        return PtrRecord.model_validate(rows[0] if rows else {"ipAddress": ip})

    def create(self, ip: str, hostname: str) -> PtrRecord:
        body = self._c._post("/dns/ptrs", {"ipAddress": ip, "hostname": hostname})
        rows = body.get("data") or []
        return PtrRecord.model_validate(rows[0] if rows else {"ipAddress": ip, "hostname": hostname})

    def update(self, ip: str, hostname: str) -> PtrRecord:
        body = self._c._request("PUT", f"/dns/ptrs/{quote(ip, safe=':.')}", json={"hostname": hostname})
        rows = body.get("data") or []
        return PtrRecord.model_validate(rows[0] if rows else {"ipAddress": ip, "hostname": hostname})

    def delete(self, ip: str) -> None:
        self._c._delete(f"/dns/ptrs/{quote(ip, safe=':.')}")
