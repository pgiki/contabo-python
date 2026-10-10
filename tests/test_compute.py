"""Offline tests for Contabo compute (VPS/VDS) API — no network."""

import json
import os

import httpx
import pytest

from contabo import ComputeInstance, Contabo


def _compute_client(handler):
    os.environ.update(
        {
            "CONTABO_CLIENT_ID": "a",
            "CONTABO_CLIENT_SECRET": "b",
            "CONTABO_API_USER": "c",
            "CONTABO_API_PASSWORD": "d",
        }
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = Contabo(_http=http)
    c._access_token, c._token_expires_at = "tok", 9e9
    return c


def test_create_instance_builds_payload():
    seen = {}

    def handler(req: httpx.Request):
        if req.url.path == "/v1/compute/instances" and req.method == "POST":
            seen.update(json.loads(req.content))
            return httpx.Response(
                201,
                json={
                    "data": [
                        {
                            "instanceId": "abc-123",
                            "displayName": "web-1",
                            "status": "provisioning",
                            "productId": "V153",
                            "cpuCores": 4,
                            "ramMb": 6144,
                            "diskMb": 102400,
                            "region": "EU",
                        }
                    ]
                },
            )
        return httpx.Response(404, json={})

    c = _compute_client(handler)
    inst = c.compute.create_instance(
        product_id="V153",
        image_id="img-1",
        region="EU",
        period=1,
        display_name="web-1",
        root_password="secret-12345678",
    )
    assert isinstance(inst, ComputeInstance)
    assert inst.instance_id == "abc-123"
    assert seen["productId"] == "V153"
    assert seen["imageId"] == "img-1"
    assert seen["region"] == "EU"
    assert seen["period"] == 1
    assert seen["displayName"] == "web-1"


def test_create_instance_rejects_bad_period():
    c = _compute_client(lambda req: httpx.Response(404, json={}))
    with pytest.raises(ValueError):
        c.compute.create_instance(product_id="V153", image_id="i", period=2)


def test_instance_action_and_cancel_paths():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        return httpx.Response(200, json={"data": [{}]})

    c = _compute_client(handler)
    c.compute.stop("inst-1")
    c.compute.start("inst-1")
    c.compute.cancel("inst-1")
    assert ("POST", "/v1/compute/instances/inst-1/actions/stop") in calls
    assert ("POST", "/v1/compute/instances/inst-1/actions/start") in calls
    assert ("POST", "/v1/compute/instances/inst-1/cancel") in calls
    with pytest.raises(ValueError):
        c.compute.instance_action("inst-1", "explode")


def test_reinstall_uses_put():
    seen = {}

    def handler(req: httpx.Request):
        seen["method"] = req.method
        seen["path"] = req.url.path
        seen.update(json.loads(req.content))
        return httpx.Response(
            200, json={"data": [{"instanceId": "i1", "status": "installing"}]}
        )

    c = _compute_client(handler)
    out = c.compute.reinstall("i1", image_id="img-9")
    assert seen["method"] == "PUT"
    assert seen["path"] == "/v1/compute/instances/i1"
    assert seen["imageId"] == "img-9"
    assert out.status == "installing"


def test_list_instances_paginates():
    def handler(req: httpx.Request):
        page = int(req.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"instanceId": "a", "status": "running"}],
                    "_pagination": {"totalPages": 2},
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [{"instanceId": "b", "status": "running"}],
                "_pagination": {"totalPages": 2},
            },
        )

    c = _compute_client(handler)
    rows = c.compute.list_instances()
    assert [r.instance_id for r in rows] == ["a", "b"]
