"""Orquestracao de uma coleta completa, com registro opcional no PostgreSQL.

CLI e API usam este modulo para que as duas entradas gravem exatamente o mesmo
conjunto de dados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .browser import BrowserRpa
from .database import Database, RunTotals, totals_from_rows
from .errors import ConfigurationError
from .models import CollectionRow, ProductInput
from .providers import GoogleShoppingProvider, PriceProvider, ShopeeProvider
from .service import CollectionService
from .settings import Settings

KNOWN_PROVIDERS = ("google", "shopee")


@dataclass(slots=True)
class CollectionOutcome:
    rows: list[CollectionRow]
    totals: RunTotals
    coleta_id: int | None = None
    parametros: dict[str, Any] = field(default_factory=dict)


def parse_providers(raw: str | Sequence[str]) -> list[str]:
    """Normaliza a lista de fontes e falha em nomes desconhecidos."""

    if isinstance(raw, str):
        items = [item.strip().casefold() for item in raw.split(",") if item.strip()]
    else:
        items = [str(item).strip().casefold() for item in raw if str(item).strip()]

    unknown = sorted(set(items) - set(KNOWN_PROVIDERS))
    if unknown:
        raise ConfigurationError(f"Fonte desconhecida: {', '.join(unknown)}")
    if not items:
        raise ConfigurationError("Selecione ao menos uma fonte")
    # preserva a ordem canonica e remove duplicatas
    return [name for name in KNOWN_PROVIDERS if name in items]


def build_providers(selected: Sequence[str], browser: BrowserRpa) -> list[PriceProvider]:
    providers: list[PriceProvider] = []
    if "google" in selected:
        providers.append(GoogleShoppingProvider(browser))
    if "shopee" in selected:
        providers.append(ShopeeProvider(browser))
    if not providers:
        raise ConfigurationError("Selecione ao menos uma fonte")
    return providers


def execute_collection(
    products: Sequence[ProductInput],
    settings: Settings,
    *,
    providers: Sequence[str],
    limit: int,
    delay: float,
    database: Database | None = None,
    origem: str = "cli",
    extra_parametros: dict[str, Any] | None = None,
) -> CollectionOutcome:
    """Roda a coleta e, se houver banco, registra a execucao ponta a ponta.

    A coleta nunca e abortada por falha de gravacao: o Excel/resposta continua
    valido mesmo se o PostgreSQL estiver indisponivel.
    """

    selected = parse_providers(providers)
    parametros: dict[str, Any] = {
        "providers": selected,
        "limit": limit,
        "delay": delay,
        "headless": settings.headless,
        "browser_channel": settings.browser_channel,
    }
    if extra_parametros:
        parametros.update(extra_parametros)

    coleta_id: int | None = None
    if database is not None:
        coleta_id = database.start_run(
            origem=origem,
            total_produtos=len(products),
            parametros=parametros,
        )

    try:
        with BrowserRpa(settings) as browser:
            provider_objects = build_providers(selected, browser)
            rows = CollectionService(provider_objects, limit, delay).collect(products)
    except Exception as exc:
        if database is not None and coleta_id is not None:
            database.finish_run(
                coleta_id,
                status="FALHOU",
                totals=RunTotals(total_produtos=len(products)),
                erro=str(exc),
            )
        raise

    totals = totals_from_rows(rows, len(products))

    if database is not None and coleta_id is not None:
        database.save_rows(coleta_id, rows)
        database.finish_run(coleta_id, status="CONCLUIDA", totals=totals)

    return CollectionOutcome(
        rows=rows,
        totals=totals,
        coleta_id=coleta_id,
        parametros=parametros,
    )
