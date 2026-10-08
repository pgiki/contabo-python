"""Domain management — namecheap-style API on Contabo (and WHMCS)."""

from dotenv import load_dotenv

load_dotenv()

from contabo import Contabo, NotSupportedError

c = Contabo()

# Availability (one result per domain)
for result in c.domains.check("example.com", "my-new-idea12345.com"):
    print(result.domain, "available:", result.available, result.reason or "")

# Portfolio + details
for domain in c.domains.list():
    print(domain.domain, domain.status, domain.renewal_date)

info = c.domains.get_info("example.com")
print(info.domain, info.status, info.nameservers, (info.handles or {}))

# Contacts resolve handle IDs automatically
contacts = c.domains.get_contacts("example.com")
print(contacts.registrant.email)

# Register with existing handles (transfer with auth_code=...)
# created = c.domains.register(
#     "new-domain.com",
#     contact={"owner": "H1", "admin": "H1", "tech": "H1", "zone": "H1"},
#     nameservers=["ns1.contabo.net", "ns2.contabo.net"],
# )

# Unsupported on Contabo (no endpoint) — explicit, never silent
for op in ("renew", "lock", "set_contacts", "get_tld_list"):
    try:
        getattr(c.domains, op)("example.com", {}) if op == "set_contacts" else (
            getattr(c.domains, op)() if op == "get_tld_list" else getattr(c.domains, op)("example.com")
        )
    except NotSupportedError as e:
        print(f"{op}: {e} [{e.alternative}]")

# Same API over WHMCS (needs: pip install contabo-python[whmcs])
# from contabo import WhmcsDomains
# w = WhmcsDomains("https://billing.example.com", "identifier", "secret")
# print([r.domain for r in w.check("example.com")])
