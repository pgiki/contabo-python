"""DNS API. Port of integrated `contabo_dns.py` to httpx + Pydantic.

Endpoints (https://api.contabo.com/, cntb OpenAPI):
  GET/POST /v1/dns/zones, GET/DELETE /v1/dns/zones/{zone}
  GET/POST /v1/dns/zones/{zone}/records, PATCH /v1/dns/zones/{zone}/records/{id}
  DELETE /v1/dns/zones/{zone}/records/{id}, DELETE .../records/bulk {recordIds}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..models import Zone, ZoneRecord

if TYPE_CHECKING:
    from ..client import Contabo


def _seg(zone_name: str) -> str:
    return quote(str(zone_name).strip().rstrip("."), safe=".-")


class DnsBuilder:
    """Fluent record builder. Mirrors `nc.dns.builder()`.

    Example:
        api.set("example.com", api.builder().a("@","1.2.3.4").mx("@","mail.example.com"))
    """

    def __init__(self, default_ttl: int = 3600):
        self.default_ttl = default_ttl
        self._specs: list[dict[str, Any]] = []

    def _add(self, name: str, rtype: str, content: str, ttl: int | None = None, **kw: Any):
        self._specs.append({
            "name": name, "type": rtype.upper(), "content": content,
            "ttl": int(ttl) if ttl is not None else self.default_ttl, **kw,
        })
        return self

    def a(self, name: str, ip: str, ttl: int | None = None):
        return self._add(name, "A", ip, ttl)

    def aaaa(self, name: str, ip: str, ttl: int | None = None):
        return self._add(name, "AAAA", ip, ttl)

    def cname(self, name: str, target: str, ttl: int | None = None):
        return self._add(name, "CNAME", target, ttl)

    def mx(self, name: str, host: str, priority: int = 10, ttl: int | None = None):
        return self._add(name, "MX", host, ttl, prio=priority)

    def txt(self, name: str, value: str, ttl: int | None = None):
        return self._add(name, "TXT", value, ttl)

    def srv(self, name: str, target: str, port: int, weight: int = 0, prio: int = 0, ttl: int | None = None):
        return self._add(name, "SRV", target, ttl, prio=prio, port=str(port), weight=str(weight))

    def caa(self, name: str, value: str, flag: int = 0, tag: str = "issue", ttl: int | None = None):
        return self._add(name, "CAA", value, ttl, flag=str(flag), tag=tag)

    def ns(self, name: str, target: str, ttl: int | None = None):
        return self._add(name, "NS", target, ttl)

    def specs(self) -> list[dict[str, Any]]:
        return list(self._specs)


class DnsAPI:
    def __init__(self, client: Contabo):
        self._c = client

    # -- zones --
    def list_zones(self) -> list[Zone]:
        rows = self._c._paginated_list("/dns/zones")
        return [Zone.model_validate(z) for z in rows]

    def list_zones_raw(self) -> list[dict]:
        return self._c._paginated_list("/dns/zones")

    def get_zone(self, domain: str) -> Zone | None:
        z = str(domain).strip().rstrip(".")
        if not z:
            return None
        from ..errors import ContaboAPIError

        try:
            body = self._c._get(f"/dns/zones/{_seg(z)}")
        except ContaboAPIError as exc:
            if exc.status_code == 404:
                return None
            raise
        rows = body.get("data") or []
        return Zone.model_validate(rows[0]) if rows else None

    def create_zone(self, domain: str) -> Zone:
        z = str(domain).strip().rstrip(".")
        data = self._c._post("/dns/zones", {"zoneName": z}).get("data", [])
        return Zone.model_validate(data[0]) if data else Zone.model_validate({"zoneName": z})

    def get_or_create_zone(self, domain: str, auto_ns: bool = True) -> Zone:  # noqa: ARG002
        return self.get_zone(domain) or self.create_zone(domain)

    def delete_zone(self, zone_name: str) -> None:
        self._c._delete(f"/dns/zones/{_seg(zone_name)}")

    # -- records --
    def list_records(self, zone_name: str) -> list[ZoneRecord]:
        raw = self._c._paginated_list(f"/dns/zones/{_seg(zone_name)}/records")
        return [ZoneRecord.model_validate(r) for r in raw]

    def list_records_raw(self, zone_name: str) -> list[dict]:
        """Dict rows with `id`+`content` keys normalized."""
        return [r.to_dto() for r in self.list_records(zone_name)]

    def get(self, zone_name: str) -> list[ZoneRecord]:
        return self.list_records(zone_name)

    def create_record(self, zone_name: str, name: str, record_type: str, content: str,
                      ttl: int | None = None, *, prio: int = 0,
                      port=None, weight=None, flag=None, tag: str | None = None) -> ZoneRecord:
        ttl_use = int(ttl if ttl is not None else self._c.config.default_ttl)
        payload: dict[str, Any] = {"name": name, "type": record_type.upper(),
                                   "ttl": ttl_use, "prio": int(prio), "data": content}
        for k, v in (("port", port), ("weight", weight), ("flag", flag)):
            if v is not None and str(v) != "":
                payload[k] = str(v)
        if tag:
            payload["tag"] = tag
        data = self._c._post(f"/dns/zones/{_seg(zone_name)}/records", payload).get("data", [])
        if not data:
            return ZoneRecord.model_validate({"recordId": 0, "name": name,
                                              "type": record_type.upper(), "data": content,
                                              "ttl": ttl_use, "prio": prio})
        return ZoneRecord.model_validate(data[0])

    def update_record(self, zone_name: str, record_id: str | int, *, content=None,
                      ttl=None, prio=None, record_type=None, port=None,
                      weight=None, flag=None, tag=None) -> ZoneRecord:
        payload: dict[str, Any] = {}
        if content is not None:
            payload["data"] = content
        if ttl is not None:
            payload["ttl"] = int(ttl)
        if prio is not None:
            payload["prio"] = int(prio)
        if record_type is not None:
            payload["type"] = record_type.upper()
        for k, v in (("port", port), ("weight", weight), ("flag", flag)):
            if v is not None and str(v) != "":
                payload[k] = str(v)
        if tag is not None:
            payload["tag"] = tag
        if not payload:
            raise ValueError("No fields to update.")
        data = self._c._patch(f"/dns/zones/{_seg(zone_name)}/records/{int(record_id)}", payload).get("data", [])
        if not data:
            return ZoneRecord.model_validate({"recordId": int(record_id), **payload})
        return ZoneRecord.model_validate(data[0])

    def bulk_delete(self, zone_name: str, record_ids: list[int]) -> None:
        if not record_ids:
            return
        self._c._request("DELETE", f"/dns/zones/{_seg(zone_name)}/records/bulk",
                         json={"recordIds": [int(i) for i in record_ids]})

    def delete_record(self, zone_name: str, record_id: str | int) -> None:
        self.bulk_delete(zone_name, [int(record_id)])

    def delete(self, zone_name: str, record_id: str | int) -> None:
        self.delete_record(zone_name, record_id)

    def add(self, zone_name: str, name: str, record_type: str, content: str, **kw) -> ZoneRecord:
        return self.create_record(zone_name, name, record_type, content, **kw)

    def delete_records_by_type(self, zone_name: str, record_type: str, name: str | None = None) -> int:
        target = record_type.upper()
        tname = name.rstrip(".") if name else None
        ids = [r.id for r in self.list_records(zone_name)
               if r.type.upper() == target and (tname is None or r.name.rstrip(".") == tname)]
        self.bulk_delete(zone_name, ids)
        return len(ids)

    def set_a_records(self, zone_name: str, domain: str, ip: str, include_www: bool = True,
                      include_wildcard: bool = False, ttl: int | None = None) -> list[ZoneRecord]:
        domain = domain.rstrip(".")
        names = [domain] + (["www." + domain] if include_www else []) + (["*." + domain] if include_wildcard else [])
        targets = {n.rstrip(".") for n in names}
        stale = [r.id for r in self.list_records(zone_name)
                 if r.type.upper() == "A" and r.name.rstrip(".") in targets]
        self.bulk_delete(zone_name, stale)
        return [self.create_record(zone_name, n, "A", ip, ttl=ttl) for n in names]

    # -- builder --
    def builder(self, default_ttl: int | None = None) -> DnsBuilder:
        return DnsBuilder(default_ttl if default_ttl is not None else self._c.config.default_ttl)

    def set(self, zone_name: str, builder: DnsBuilder, *, fqdn: str | None = None) -> list[ZoneRecord]:
        """Replace zone records with builder specs (namecheap `dns.set` equivalent).

        `@` and relative labels resolve against `fqdn or zone_name`.
        """
        base = (fqdn or zone_name).strip().rstrip(".").lower()
        existing = self.list_records(zone_name)
        self.bulk_delete(zone_name, [r.id for r in existing])
        created = []
        for s in builder.specs():
            host = self._hostname(s["name"], base)
            created.append(self.create_record(zone_name, host, s["type"], s["content"],
                                              ttl=s.get("ttl"), prio=s.get("prio", 0),
                                              port=s.get("port"), weight=s.get("weight"),
                                              flag=s.get("flag"), tag=s.get("tag")))
        return created

    @staticmethod
    def _hostname(name: str, fqdn: str) -> str:
        raw = (name or "").strip().rstrip(".")
        if not raw or raw == "@":
            return fqdn
        low = raw.lower()
        if low == fqdn or low.endswith("." + fqdn):
            return low
        return f"{low}.{fqdn}"

    def export(self, zone_name: str) -> list[dict]:
        return [r.to_dto() for r in self.list_records(zone_name)]
