"""Offline tests for contabo-python (no network)."""
import os
from unittest.mock import MagicMock

import pytest

from contabo import Contabo
from contabo._api.dns import DnsAPI
from contabo.errors import ConfigurationError
from contabo.models import ZoneRecord


def _client_with_mock(**overrides):
    env = {"CONTABO_CLIENT_ID": "id", "CONTABO_CLIENT_SECRET": "s",
           "CONTABO_API_USER": "u@e.com", "CONTABO_API_PASSWORD": "p"}
    os.environ.update(env)
    c = Contabo()
    m = MagicMock()
    c._request = m
    c._get = MagicMock()
    c._post = MagicMock()
    c._patch = MagicMock()
    c._delete = MagicMock()
    c._paginated_list = MagicMock()
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def test_config_missing_raises():
    for k in ("CONTABO_CLIENT_ID", "CONTABO_CLIENT_SECRET", "CONTABO_API_USER", "CONTABO_API_PASSWORD"):
        os.environ.pop(k, None)
    with pytest.raises(ConfigurationError):
        Contabo()
    os.environ.update({"CONTABO_CLIENT_ID": "a", "CONTABO_CLIENT_SECRET": "b",
                       "CONTABO_API_USER": "c", "CONTABO_API_PASSWORD": "d"})


def test_builder_specs():
    c = _client_with_mock()
    b = c.dns.builder().a("@", "1.2.3.4").mx("@", "mail.example.com", priority=10).txt("x", "v")
    specs = b.specs()
    assert [s["type"] for s in specs] == ["A", "MX", "TXT"]
    assert specs[1]["prio"] == 10


def test_hostname_mapping():
    assert DnsAPI._hostname("@", "example.com") == "example.com"
    assert DnsAPI._hostname("www", "example.com") == "www.example.com"
    assert DnsAPI._hostname("WWW.Example.COM.", "example.com") == "www.example.com"
    assert DnsAPI._hostname("mail.example.com", "example.com") == "mail.example.com"


def test_record_normalization():
    r = ZoneRecord.model_validate({"recordId": 11, "name": "example.com",
                                   "type": "mx", "data": "mail.example.com", "ttl": 3600, "prio": 10})
    dto = r.to_dto()
    assert dto["id"] == 11 and dto["recordId"] == 11
    assert dto["content"] == "mail.example.com" and dto["data"] == "mail.example.com"
    assert dto["type"] == "MX"


def test_set_replaces_all_and_resolves_at():
    c = _client_with_mock()
    c._paginated_list.return_value = [
        {"recordId": 1, "name": "example.com", "type": "A", "data": "9.9.9.9", "ttl": 3600, "prio": 0}]
    created = []

    def fake_create(zone, name, rtype, content, **kw):
        created.append((zone, name, rtype, content))
        return ZoneRecord.model_validate({"recordId": len(created), "name": name,
                                          "type": rtype, "data": content, "ttl": 3600, "prio": 0})
    c.dns.create_record = fake_create
    deleted = []
    c.dns.bulk_delete = lambda z, ids: deleted.extend(ids)

    out = c.dns.set("example.com", c.dns.builder().a("@", "1.2.3.4").mx("@", "m.example.com"))
    assert deleted == [1]
    assert created[0][1] == "example.com"  # @ resolved
    assert len(out) == 2


def test_set_a_records_targets_only_a():
    c = _client_with_mock()
    c.dns.list_records = lambda z: [
        ZoneRecord.model_validate({"recordId": 1, "name": "example.com", "type": "A", "data": "9.9.9.9"}),
        ZoneRecord.model_validate({"recordId": 2, "name": "example.com", "type": "MX", "data": "m"}),
        ZoneRecord.model_validate({"recordId": 3, "name": "other.example.com", "type": "A", "data": "9.9.9.9"}),
    ]
    seen = {}
    c.dns.bulk_delete = lambda z, ids: seen.update(ids=ids)
    c.dns.create_record = lambda z, n, t, co, **kw: ZoneRecord.model_validate(
        {"recordId": 9, "name": n, "type": t, "data": co})
    out = c.dns.set_a_records("example.com", "example.com", "1.2.3.4")
    assert seen["ids"] == [1]
    assert [r.name for r in out] == ["example.com", "www.example.com"]


def test_pagination_and_401_retry():
    import httpx
    calls = {"n": 0}

    def handler(req: httpx.Request):
        calls["n"] += 1
        if req.url.path == "/v1/dns/zones" and calls["n"] == 1:
            return httpx.Response(401, json={"m": "expired"})
        return httpx.Response(200, json={"data": [{"zoneName": "example.com"}], "_pagination": {"totalPages": 1}})
    os.environ.update({"CONTABO_CLIENT_ID": "a", "CONTABO_CLIENT_SECRET": "b",
                       "CONTABO_API_USER": "c", "CONTABO_API_PASSWORD": "d"})
    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = Contabo(_http=http)
    c.authenticate = lambda: setattr(c, "_access_token", "tok") or setattr(c, "_token_expires_at", 9e9) or "tok"
    c._access_token, c._token_expires_at = "tok", 9e9
    zones = c.dns.list_zones()
    assert zones[0].zone_name == "example.com" and calls["n"] == 2
