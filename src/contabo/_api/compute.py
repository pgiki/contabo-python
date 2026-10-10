"""Compute (Cloud VPS / VDS) API.

Endpoints (https://api.contabo.com/, ``cntb`` OpenAPI):
  GET/POST /v1/compute/instances
  GET/PATCH /v1/compute/instances/{instanceId}
  PUT /v1/compute/instances/{instanceId} (reinstall)
  GET /v1/compute/instances/{instanceId}/products (upgrade targets)
  POST /v1/compute/instances/{instanceId}/upgrade
  POST /v1/compute/instances/{instanceId}/cancel
  POST /v1/compute/instances/{instanceId}/actions/start|restart|stop|shutdown|rescue|resetPassword
  GET /v1/compute/instances/audits, GET /v1/compute/actions/audits
  GET/POST /v1/compute/images, GET/PATCH/DELETE /v1/compute/images/{imageId}
  GET/POST /v1/compute/snapshots, GET/PATCH/DELETE .../{snapshotId}, POST .../{id}/revert

Storage VPS and Dedicated/Bare-Metal are NOT exposed via this API
(Control Panel only) — this module covers Cloud VPS / VPS Plus / VDS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import ComputeInstance, Image, Snapshot

if TYPE_CHECKING:
    from ..client import Contabo

VALID_PERIODS = (1, 3, 6, 12)
VALID_ACTIONS = ("start", "restart", "stop", "shutdown", "rescue", "resetPassword")


class ComputeAPI:
    def __init__(self, client: Contabo):
        self._c = client

    # -- instances --
    def list_instances(self, **filters: Any) -> list[ComputeInstance]:
        rows = self._c._paginated_list("/compute/instances", extra=filters or None)
        return [ComputeInstance.model_validate(r) for r in rows]

    def get_instance(self, instance_id: str | int) -> ComputeInstance:
        body = self._c._get(f"/compute/instances/{instance_id}")
        data = (body.get("data") or [{}])[0]
        return ComputeInstance.model_validate(data)

    def create_instance(
        self,
        *,
        product_id: str,
        image_id: str,
        region: str = "EU",
        period: int = 1,
        display_name: str | None = None,
        ssh_keys: list[str] | None = None,
        root_password: str | None = None,
        user_data: str | None = None,
        add_ons: list[Any] | None = None,
    ) -> ComputeInstance:
        if period not in VALID_PERIODS:
            raise ValueError(f"period must be one of {VALID_PERIODS}")
        payload: dict[str, Any] = {
            "productId": product_id,
            "imageId": image_id,
            "region": region,
            "period": period,
        }
        if display_name:
            payload["displayName"] = display_name
        if ssh_keys:
            payload["sshKeys"] = ssh_keys
        if root_password:
            payload["rootPassword"] = root_password
        if user_data:
            payload["userData"] = user_data
        if add_ons:
            payload["addOns"] = add_ons
        body = self._c._post("/compute/instances", payload)
        data = (body.get("data") or [{}])[0]
        return ComputeInstance.model_validate(data)

    def update_instance(self, instance_id: str | int, *, display_name: str) -> ComputeInstance:
        body = self._c._patch(
            f"/compute/instances/{instance_id}", {"displayName": display_name}
        )
        data = (body.get("data") or [{}])[0]
        return ComputeInstance.model_validate(data)

    def reinstall(
        self,
        instance_id: str | int,
        *,
        image_id: str,
        ssh_keys: list[str] | None = None,
        root_password: str | None = None,
        user_data: str | None = None,
    ) -> ComputeInstance:
        payload: dict[str, Any] = {"imageId": image_id}
        if ssh_keys is not None:
            payload["sshKeys"] = ssh_keys
        if root_password:
            payload["rootPassword"] = root_password
        if user_data:
            payload["userData"] = user_data
        body = self._c._put(f"/compute/instances/{instance_id}", payload)
        data = (body.get("data") or [{}])[0]
        return ComputeInstance.model_validate(data)

    def list_upgrade_options(self, instance_id: str | int) -> list[dict[str, Any]]:
        body = self._c._get(f"/compute/instances/{instance_id}/products")
        return list(body.get("data") or [])

    def upgrade(self, instance_id: str | int, *, product_id: str) -> dict[str, Any]:
        return self._c._post(
            f"/compute/instances/{instance_id}/upgrade", {"productId": product_id}
        )

    def cancel(self, instance_id: str | int) -> dict[str, Any]:
        """Cancel an instance. Sets ``cancelDate`` — irreversible via API."""
        return self._c._post(f"/compute/instances/{instance_id}/cancel", {})

    def instance_action(
        self, instance_id: str | int, action: str, **params: Any
    ) -> dict[str, Any]:
        if action not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {VALID_ACTIONS}")
        return self._c._post(
            f"/compute/instances/{instance_id}/actions/{action}", params or {}
        )

    def start(self, instance_id: str | int) -> dict[str, Any]:
        return self.instance_action(instance_id, "start")

    def restart(self, instance_id: str | int) -> dict[str, Any]:
        return self.instance_action(instance_id, "restart")

    def stop(self, instance_id: str | int) -> dict[str, Any]:
        return self.instance_action(instance_id, "stop")

    def reset_password(
        self, instance_id: str | int, *, root_password: str
    ) -> dict[str, Any]:
        return self.instance_action(
            instance_id, "resetPassword", rootPassword=root_password
        )

    def list_instance_audits(self, **filters: Any) -> list[dict[str, Any]]:
        return self._c._paginated_list(
            "/compute/instances/audits", extra=filters or None
        )

    def list_action_audits(self, **filters: Any) -> list[dict[str, Any]]:
        return self._c._paginated_list(
            "/compute/actions/audits", extra=filters or None
        )

    # -- images / snapshots (phase-2 upsells) --
    def list_images(self, **filters: Any) -> list[Image]:
        rows = self._c._paginated_list("/compute/images", extra=filters or None)
        return [Image.model_validate(r) for r in rows]

    def list_snapshots(self, **filters: Any) -> list[Snapshot]:
        rows = self._c._paginated_list("/compute/snapshots", extra=filters or None)
        return [Snapshot.model_validate(r) for r in rows]

    def revert_snapshot(self, snapshot_id: str | int) -> dict[str, Any]:
        return self._c._post(f"/compute/snapshots/{snapshot_id}/revert", {})
