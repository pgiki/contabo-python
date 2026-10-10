"""contabo-python — a friendly Python SDK for the Contabo API.

Example:
    >>> from contabo import Contabo
    >>> c = Contabo()  # auto-loads CONTABO_* from environment
    >>> zone = c.dns.get_or_create_zone("example.com")
    >>> c.dns.set_a_records(zone.zone_name, "example.com", "1.2.3.4")
"""

from __future__ import annotations

from .client import Contabo
from .config import Config
from .errors import (
    ConfigurationError,
    ContaboAPIError,
    ContaboError,
    NotSupportedError,
    PricingError,
)
from .models import (
    ComputeInstance,
    Contact,
    Domain,
    DomainCheck,
    DomainContacts,
    DomainDetails,
    DomainHandles,
    EmailForward,
    Handle,
    Image,
    IpConfig,
    PtrRecord,
    Snapshot,
    Zone,
    ZoneRecord,
)
from .pricing import (
    ContaboStorefrontPricing,
    PricingConfig,
    VpsPrice,
)

__version__ = "0.5.0"
__all__ = [
    "ComputeInstance",
    "ConfigurationError",
    "Contabo",
    "ContaboAPIError",
    "ContaboError",
    "Config",
    "Contact",
    "ContaboStorefrontPricing",
    "Domain",
    "DomainCheck",
    "DomainContacts",
    "DomainDetails",
    "DomainHandles",
    "EmailForward",
    "Handle",
    "Image",
    "IpConfig",
    "NotSupportedError",
    "PricingConfig",
    "PricingError",
    "PtrRecord",
    "Snapshot",
    "VpsPrice",
    "Zone",
    "ZoneRecord",
]


def __getattr__(name: str):
    """Lazy backends needing optional extras (keeps the base install light)."""
    if name == "WhmcsDomains":
        from ._api.whmcs import WhmcsDomains  # noqa: PLC0415  # optional whmcs extra; PEP 562 lazy export

        return WhmcsDomains
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
