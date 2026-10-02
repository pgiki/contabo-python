"""Quickstart — mirrors namecheap-python examples/quickstart.py."""
from dotenv import load_dotenv

load_dotenv()

from contabo import Contabo

c = Contabo()

# Zones
zone = c.dns.get_or_create_zone("example.com")
print("zone:", zone.zone_name)

# Point root + www at an IP
c.dns.set_a_records(zone.zone_name, "example.com", "1.2.3.4")

# Fluent builder (mirrors nc.dns.builder())
c.dns.set("example.com", c.dns.builder()
          .a("@", "1.2.3.4")
          .a("www", "1.2.3.4")
          .mx("@", "mail.example.com", priority=10)
          .txt("@", "v=spf1 mx ~all"))

# Email DNS (mirrors fikashop dns_email)
for r in c.dns.list_records(zone.zone_name):
    print(r.type, r.name, r.content)

# Domains + handles (Contabo-native)
print(c.domains.check("example.com"))
print([h.id for h in c.handles.list()])
