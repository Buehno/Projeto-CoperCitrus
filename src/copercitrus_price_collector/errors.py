"""Domain exceptions used by the collector."""

class PriceCollectorError(Exception):
    """Base error exposed to the CLI."""


class ConfigurationError(PriceCollectorError):
    """Raised when a selected provider is not configured."""


class SpreadsheetError(PriceCollectorError):
    """Raised for invalid input workbooks."""


class ProviderError(PriceCollectorError):
    """Raised when an upstream provider returns an invalid response."""


class ProviderHttpError(ProviderError):
    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
