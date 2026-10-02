"""Logging setup. Mirrors namecheap-python logging with rich fallback."""

from __future__ import annotations

import logging

try:
    from rich.logging import RichHandler

    _handler = RichHandler(rich_tracebacks=True, show_time=False)
    logging.basicConfig(handlers=[_handler], level=logging.INFO, force=True)
except Exception:  # pragma: no cover - rich optional at runtime
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("contabo")


def set_log_level(level: str) -> None:
    logger.setLevel(level.upper())
