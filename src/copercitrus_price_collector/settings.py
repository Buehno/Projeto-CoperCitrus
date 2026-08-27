"""Environment-based application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import ConfigurationError


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} deve ser numerico") from exc


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} deve ser inteiro") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    serpapi_key: str | None
    shopee_app_id: str | None
    shopee_app_secret: str | None
    google_location: str
    timeout_seconds: float
    max_retries: int
    request_delay_seconds: float
    result_limit: int

    @classmethod
    def from_env(cls) -> Settings:
        settings = cls(
            serpapi_key=os.getenv("SERPAPI_KEY") or None,
            shopee_app_id=os.getenv("SHOPEE_APP_ID") or None,
            shopee_app_secret=os.getenv("SHOPEE_APP_SECRET") or None,
            google_location=os.getenv(
                "GOOGLE_LOCATION", "Sao Paulo, State of Sao Paulo, Brazil"
            ),
            timeout_seconds=_float_env("HTTP_TIMEOUT_SECONDS", 30.0),
            max_retries=_int_env("HTTP_MAX_RETRIES", 3),
            request_delay_seconds=_float_env("REQUEST_DELAY_SECONDS", 1.0),
            result_limit=_int_env("RESULT_LIMIT", 5),
        )
        if settings.timeout_seconds <= 0:
            raise ConfigurationError("HTTP_TIMEOUT_SECONDS deve ser maior que zero")
        if settings.max_retries < 0:
            raise ConfigurationError("HTTP_MAX_RETRIES nao pode ser negativo")
        if settings.request_delay_seconds < 0:
            raise ConfigurationError("REQUEST_DELAY_SECONDS nao pode ser negativo")
        if not 1 <= settings.result_limit <= 20:
            raise ConfigurationError("RESULT_LIMIT deve estar entre 1 e 20")
        return settings
