"""Contabo API SDK errors. Mirrors namecheap-python error shape."""

from __future__ import annotations


class ContaboError(Exception):
    """Base error for all Contabo SDK failures."""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        response_text: str = "",
        help: str | None = None,  # noqa: A002 - mirrors namecheap-python
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_text = response_text
        self.help = help

    def __str__(self) -> str:
        base = f"{self.message} (HTTP {self.status_code}: {self.response_text})"
        if self.help:
            return f"{base}\n💡 Tip: {self.help}"
        return base


# Alias matching the previous integrated client's exception name.
class ContaboAPIError(ContaboError):
    """Raised on non-2xx Contabo API responses (legacy name)."""


class ConfigurationError(ContaboError):
    """Raised when credentials/config are missing or invalid."""

    def __init__(self, message: str):
        super().__init__(message, status_code=0, response_text="")
