"""Provider interface contract."""

from __future__ import annotations

from typing import Protocol

from ..models import ProductInput, SearchResult


class PriceProvider(Protocol):
    name: str

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]: ...
