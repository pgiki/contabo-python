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
from .errors import ConfigurationError, ContaboAPIError, ContaboError
from .models import (
    Domain,
    DomainCheck,
    EmailForward,
    Handle,
    PtrRecord,
    Zone,
    ZoneRecord,
)

__version__ = "0.1.0"
__all__ = [
    "ConfigurationError",
    "Contabo",
    "ContaboAPIError",
    "ContaboError",
    "Config",
    "Domain",
    "DomainCheck",
    "EmailForward",
    "Handle",
    "PtrRecord",
    "Zone",
    "ZoneRecord",
]
