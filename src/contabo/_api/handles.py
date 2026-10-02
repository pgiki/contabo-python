"""Handles API — contact handles. Replaces whoisguard/contacts.

Endpoints:
  GET/POST /v1/domains/handles, GET/PUT/DELETE /v1/domains/handles/{id}
  PATCH /v1/domains/handles/{id}/default
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import Handle

if TYPE_CHECKING:
    from ..client import Contabo


class HandlesAPI:
    def __init__(self, client: Contabo):
        self._c = client

    def list(self, **params: Any) -> list[Handle]:
        rows = self._c._paginated_list("/domains/handles", extra=params or None)
        return [Handle.model_validate(r) for r in rows]

    def get(self, handle_id: str | int) -> Handle:
        body = self._c._get(f"/domains/handles/{handle_id}")
        rows = body.get("data") or []
        return Handle.model_validate(rows[0] if rows else {"handleId": handle_id})

    def create(self, payload: dict[str, Any]) -> Handle:
        body = self._c._post("/domains/handles", payload)
        rows = body.get("data") or []
        return Handle.model_validate(rows[0] if rows else payload)

    def update(self, handle_id: str | int, payload: dict[str, Any]) -> Handle:
        body = self._c._request("PUT", f"/domains/handles/{handle_id}", json=payload)
        rows = body.get("data") or []
        return Handle.model_validate(rows[0] if rows else {"handleId": handle_id, **payload})

    def delete(self, handle_id: str | int) -> None:
        self._c._delete(f"/domains/handles/{handle_id}")

    def set_default(self, handle_id: str | int) -> Handle:
        body = self._c._patch(f"/domains/handles/{handle_id}/default", {})
        rows = body.get("data") or []
        return Handle.model_validate(rows[0] if rows else {"handleId": handle_id})
