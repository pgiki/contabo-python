# contabo-python

A friendly Python SDK for the [Contabo API](https://api.contabo.com/) — same structure as [`namecheap-python`](https://github.com/adriangalilea/namecheap-python): `Contabo().dns/.domains/.handles/.ptr/.audits`, Pydantic models, fluent DNS builder, env auto-config.

Requires Python 3.12+.

```bash
pip install contabo-python
```

```python
from contabo import Contabo
c = Contabo()  # CONTABO_CLIENT_ID/SECRET/API_USER/API_PASSWORD
zone = c.dns.get_or_create_zone("example.com")
c.dns.set("example.com", c.dns.builder()
  .a("@", "1.2.3.4").mx("@", "mail.example.com", priority=10)
  .txt("@", "v=spf1 mx ~all"))
```

## Config

| Env | Description |
|---|---|
| `CONTABO_CLIENT_ID` / `CONTABO_CLIENT_SECRET` | OAuth2 client (my.contabo.com → API) |
| `CONTABO_API_USER` | Login email |
| `CONTABO_API_PASSWORD` | API password (set separately in panel) |
| `CONTABO_DEFAULT_TTL` | Default TTL (3600) |
| `CONTABO_LOG_LEVEL` | Logging level |

SDK never reads `.env` implicitly — use `Contabo.from_env_file(".env")`.

## fikashop migration

```python
# before
from domains.services.dns.contabo_dns import ContaboDNS
contabo = ContaboDNS.from_env()
zone = contabo.get_or_create_zone(domain.fqdn)
contabo.set_a_records(zone["zoneName"], domain.fqdn, ip)

# after
from contabo import Contabo
contabo = Contabo()  # same CONTABO_* env vars
zone = contabo.dns.get_or_create_zone(domain.fqdn)
contabo.dns.set_a_records(zone.zone_name, domain.fqdn, ip)
```

`list_records()` now returns Pydantic `ZoneRecord` models — use `r.to_dto()`
for the legacy `{id, recordId, content, data, ...}` dict shape.

## Quirks (cf. namecheap `1799 = Automatic`)

- No sandbox, no IP whitelist, no pricing/balance endpoints.
- Always send `x-request-id: uuid4`; never set `Content-Type` on bodyless requests.
- Prefer `DELETE .../records/bulk {recordIds}` — singular delete is unreliable.
- `recordId/data` normalized to `id/content`; zone identity is `zoneName`.
- No registrar nameserver switch — keep WHMCS path for NS changes.
