"""Configuracoes do Chromium e dos limites operacionais do RPA."""

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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "sim"}:
        return True
    if normalized in {"0", "false", "no", "nao", "não"}:
        return False
    raise ConfigurationError(f"{name} deve ser true ou false")


@dataclass(frozen=True, slots=True)
class Settings:
    headless: bool
    browser_channel: str | None
    browser_user_data_dir: str | None
    browser_cdp_url: str | None
    browser_timeout_seconds: float
    slow_mo_ms: int
    request_delay_seconds: float
    result_limit: int

    @classmethod
    def from_env(cls) -> Settings:
        settings = cls(
            headless=_bool_env("RPA_HEADLESS", True),
            browser_channel=os.getenv("RPA_BROWSER_CHANNEL") or None,
            browser_user_data_dir=os.getenv("RPA_BROWSER_USER_DATA_DIR") or None,
            browser_cdp_url=os.getenv("RPA_BROWSER_CDP_URL") or None,
            browser_timeout_seconds=_float_env("RPA_BROWSER_TIMEOUT_SECONDS", 45.0),
            slow_mo_ms=_int_env("RPA_SLOW_MO_MS", 0),
            request_delay_seconds=_float_env("REQUEST_DELAY_SECONDS", 2.0),
            result_limit=_int_env("RESULT_LIMIT", 5),
        )
        if settings.browser_timeout_seconds <= 0:
            raise ConfigurationError(
                "RPA_BROWSER_TIMEOUT_SECONDS deve ser maior que zero"
            )
        if settings.slow_mo_ms < 0:
            raise ConfigurationError("RPA_SLOW_MO_MS nao pode ser negativo")
        if settings.request_delay_seconds < 0:
            raise ConfigurationError("REQUEST_DELAY_SECONDS nao pode ser negativo")
        if not 1 <= settings.result_limit <= 20:
            raise ConfigurationError("RESULT_LIMIT deve estar entre 1 e 20")
        return settings
