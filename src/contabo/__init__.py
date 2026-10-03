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
)
from .models import (
    Contact,
    Domain,
    DomainCheck,
    DomainContacts,
    DomainDetails,
    DomainHandles,
    EmailForward,
    Handle,
    PtrRecord,
    Zone,
    ZoneRecord,
)

__version__ = "0.3.0"
__all__ = [
    "ConfigurationError",
    "Contabo",
    "ContaboAPIError",
    "ContaboError",
    "Config",
    "Contact",
    "Domain",
    "DomainCheck",
    "DomainContacts",
    "DomainDetails",
    "DomainHandles",
    "EmailForward",
    "Handle",
    "NotSupportedError",
    "PtrRecord",
    "Zone",
    "ZoneRecord",
]


def __getattr__(name: str):
    """Lazy backends needing optional extras (keeps the base install light)."""
    if name == "WhmcsDomains":
        from ._api.whmcs import WhmcsDomains
        return WhmcsDomains
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
