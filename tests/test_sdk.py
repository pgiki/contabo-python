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


def test_record_null_prio_ttl_coerced_to_defaults():
    # The live API returns explicit nulls for inapplicable fields
    # (e.g. TXT records carry ``prio: null``) — must not raise.
    r = ZoneRecord.model_validate({"recordId": 12, "name": "example.com",
                                   "type": "TXT", "data": "v=spf1 ~all",
                                   "ttl": None, "prio": None})
    dto = r.to_dto()
    assert dto["ttl"] == 3600
    assert dto["prio"] == 0


def test_ptr_update_sends_ptr_field():
    # The API rejects ``hostname`` with 400; the field name must be ``ptr``.
    c = _client_with_mock()
    c._request = MagicMock(return_value={"data": []})
    c.ptr.update("203.0.113.10", "mail.example.com")
    c._request.assert_called_once_with(
        "PUT", "/dns/ptrs/203.0.113.10", json={"ptr": "mail.example.com"}
    )


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


def _domains_client(handler):
    import httpx

    os.environ.update({"CONTABO_CLIENT_ID": "a", "CONTABO_CLIENT_SECRET": "b",
                       "CONTABO_API_USER": "c", "CONTABO_API_PASSWORD": "d"})
    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = Contabo(_http=http)
    c._access_token, c._token_expires_at = "tok", 9e9
    return c


def test_domains_check_parses_availability():
    import httpx
    c = _domains_client(lambda req: httpx.Response(200, json={"data": [{"available": True}]}))
    out = c.domains.check("free-domain-xyz123.com", "taken.com")
    assert [r.available for r in out] == [True, True]
    assert out[0].domain == "free-domain-xyz123.com"


def test_domains_check_refused_is_clear():
    import httpx
    c = _domains_client(lambda req: httpx.Response(402, json={"message": "pay up"}))
    try:
        c.domains.check("example.com")
        raise AssertionError("expected ContaboAPIError")
    except Exception as e:
        assert "at least" in str(e) and "one other active" in str(e)


def test_domains_get_info_full_shape():
    import httpx
    payload = {"data": [{
        "domainName": "example.com", "status": "active",
        "nameservers": ["ns1.contabo.net"],
        "handles": {"owner": "H1", "admin": "H1", "tech": "H2", "zone": "H2"},
        "domainDetails": {"sld": "example", "tld": "com", "domainPuny": "example.com"},
        "registrationDate": "2024-01-01", "renewalDate": "2025-01-01",
    }]}
    c = _domains_client(lambda req: httpx.Response(200, json=payload))
    d = c.domains.get_info("example.com")
    assert d.domain == "example.com" and d.status == "active"
    assert d.nameservers == ["ns1.contabo.net"]
    assert d.handles.owner == "H1" and d.details.fqdn == "example.com"


def test_domains_get_contacts_resolves_handles():
    import httpx
    def handler(req):
        path = req.url.path
        if path.endswith("/domains/example.com"):
            return httpx.Response(200, json={"data": [{
                "domainName": "example.com",
                "handles": {"owner": "H1", "admin": "", "tech": "", "zone": ""},
            }]})
        if path.endswith("/domains/handles/H1"):
            return httpx.Response(200, json={"data": [{
                "handleId": "H1", "first_name": "John", "last_name": "Doe",
                "email": "john@example.com",
            }]})
        return httpx.Response(404, json={})
    c = _domains_client(handler)
    contacts = c.domains.get_contacts("example.com")
    assert contacts.registrant.first_name == "John"
    assert contacts.registrant.email == "john@example.com"
    assert contacts.tech.first_name == ""


def test_domains_unsupported_raise():
    from contabo import NotSupportedError
    c = _client_with_mock()
    for fn in (lambda: c.domains.renew("example.com"),
               lambda: c.domains.lock("example.com"),
               lambda: c.domains.unlock("example.com"),
               lambda: c.domains.set_contacts("example.com", {}),
               lambda: c.domains.get_tld_list()):
        try:
            fn()
            raise AssertionError("expected NotSupportedError")
        except NotSupportedError as e:
            assert e.alternative


def test_domains_register_builds_payload():
    import json

    import httpx
    seen = {}

    def handler(req):
        if req.url.path == "/v1/domains/handles" and req.method == "POST":
            body = json.loads(req.content)
            return httpx.Response(201, json={"data": [{"handleId": "HX", **body}]})
        if req.url.path == "/v1/domains" and req.method == "POST":
            seen.update(json.loads(req.content))
            return httpx.Response(201, json={"data": [{"domainName": "new.com", "status": "pending"}]})
        return httpx.Response(404, json={})
    c = _domains_client(handler)
    d = c.domains.register(
        "new.com",
        contact={"firstName": "J", "lastName": "D", "email": "j@d.com", "country": "US",
                 "address1": "s", "city": "c", "phone": "+1", "stateProvince": "s", "postalCode": "1"},
        nameservers=["ns1.contabo.net"],
    )
    assert d.domain == "new.com"
    assert seen["handles"] == {"owner": "HX", "admin": "HX", "tech": "HX", "zone": "HX"}
    assert seen["nameservers"] == [{"hostname": ["ns1.contabo.net"]}]


def _whmcs_backend(monkeypatch, stub):
    """Build WhmcsDomains with a stubbed whmcspy module (no extra needed)."""
    import sys
    import types
    from unittest.mock import MagicMock

    from contabo._api import whmcs as whmcs_mod

    fake_client = MagicMock()
    fake_client.call.side_effect = lambda action, **kw: stub(action, **kw)
    for method in ("add_client", "add_order", "update_client_domain",
                   "get_clients_domains", "get_tld_pricing"):
        getattr(fake_client, method).side_effect = (
            lambda *a, _m=method, **kw: stub(_m, *a, **kw)
        )
    fake_module = types.ModuleType("whmcspy")
    fake_module.WHMCS = MagicMock(return_value=fake_client)

    class _WhmcsError(Exception):
        pass

    fake_exc = types.ModuleType("whmcspy.exceptions")
    fake_exc.Error = _WhmcsError
    fake_exc.MissingPermission = _WhmcsError
    monkeypatch.setitem(sys.modules, "whmcspy", fake_module)
    monkeypatch.setitem(sys.modules, "whmcspy.exceptions", fake_exc)
    return whmcs_mod.WhmcsDomains("https://billing.test", "id", "s"), fake_client


def test_whmcs_check_parses_whois(monkeypatch):
    def stub(action, **kw):
        assert action == "DomainWhois"
        return {"status": "available"} if kw["domain"] == "free.test" else {"status": "registered"}
    backend, _ = _whmcs_backend(monkeypatch, stub)
    out = backend.check("free.test", "taken.test")
    assert [(r.domain, r.available) for r in out] == [("free.test", True), ("taken.test", False)]


def test_whmcs_register_creates_client_then_orders(monkeypatch):
    def stub(action, *a, **kw):
        if action == "add_client":
            return {"clientid": 42}
        if action == "add_order":
            assert kw["clientid"] == 42
            assert kw["nameserver1"] == "ns1.test"
            assert kw["eppcode"] == "auth123"
            return {"orderid": 7}
        raise AssertionError(action)
    backend, _ = _whmcs_backend(monkeypatch, stub)
    d = backend.register(
        "new.test",
        contact={"firstName": "J", "lastName": "D", "email": "j@d.com", "address1": "s",
                 "city": "c", "stateProvince": "s", "postalCode": "1", "country": "US",
                 "phone": "+1"},
        nameservers=["ns1.test"],
        auth_code="auth123",
    )
    assert d.domain == "new.test" and d.status == "pending"


def test_whmcs_unsupported_raise(monkeypatch):
    from contabo import NotSupportedError
    backend, _ = _whmcs_backend(monkeypatch, lambda action, *a, **kw: {})
    for fn in (lambda: backend.suggest("x.test"),
               lambda: backend.pending(),
               lambda: backend.lock("x.test"),
               lambda: backend.get_tld_list()):
        try:
            fn()
            raise AssertionError("expected NotSupportedError")
        except NotSupportedError:
            pass


def test_whmcs_add_client_int_return(monkeypatch):
    """Real whmcspy add_client returns a bare int, not a payload dict."""
    def stub(action, *a, **kw):
        if action == "GetClients":
            return {"clients": {"client": []}}
        if action == "add_client":
            return 99
        raise AssertionError(action)
    backend, _ = _whmcs_backend(monkeypatch, stub)
    assert backend.ensure_client({"email": "nobody@test"}) == 99
