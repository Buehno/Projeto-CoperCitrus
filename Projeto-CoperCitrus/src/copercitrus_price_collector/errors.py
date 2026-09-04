"""Domain exceptions used by the collector."""

class PriceCollectorError(Exception):
    """Base error exposed to the CLI."""


class ConfigurationError(PriceCollectorError):
    """Raised when a selected provider is not configured."""


class SpreadsheetError(PriceCollectorError):
    """Raised for invalid input workbooks."""


class ProviderError(PriceCollectorError):
    """Raised when a marketplace cannot be collected."""


class BrowserBlockedError(ProviderError):
    """Raised when the marketplace presents a CAPTCHA or automation block."""
