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

## Models

Zones and records are Pydantic models: `zone.zone_name`,
`record.id / record.content / record.ttl / record.prio`. Use `r.to_dto()`
for a plain dict carrying both `id`/`recordId` and `content`/`data` keys.

## Quirks (cf. namecheap `1799 = Automatic`)

- No sandbox, no IP whitelist, no pricing/balance endpoints.
- Always send `x-request-id: uuid4`; never set `Content-Type` on bodyless requests.
- Prefer `DELETE .../records/bulk {recordIds}` — singular delete is unreliable.
- `recordId/data` normalized to `id/content`; zone identity is `zoneName`.
- No registrar nameserver switch — keep WHMCS path for NS changes.
