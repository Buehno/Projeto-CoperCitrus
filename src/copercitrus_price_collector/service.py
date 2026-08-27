"""Price collection orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from .errors import ProviderError
from .models import CollectionRow, ProductInput
from .providers.base import PriceProvider


class CollectionService:
    def __init__(
        self,
        providers: Iterable[PriceProvider],
        result_limit: int,
        request_delay_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.providers = list(providers)
        self.result_limit = result_limit
        self.request_delay_seconds = request_delay_seconds
        self.sleeper = sleeper

    def collect(self, products: Iterable[ProductInput]) -> list[CollectionRow]:
        rows: list[CollectionRow] = []
        requests_made = 0
        for product in products:
            for provider in self.providers:
                if requests_made and self.request_delay_seconds:
                    self.sleeper(self.request_delay_seconds)
                requests_made += 1
                try:
                    results = provider.search(product.query, self.result_limit)
                except ProviderError as exc:
                    rows.append(CollectionRow.failed(product, provider.name, str(exc)))
                    continue
                except Exception:
                    rows.append(
                        CollectionRow.failed(
                            product,
                            provider.name,
                            "Falha inesperada; consulte os logs da execucao",
                        )
                    )
                    continue

                if not results:
                    rows.append(CollectionRow.empty(product, provider.name))
                    continue
                rows.extend(CollectionRow.success(product, item) for item in results)
        return rows
