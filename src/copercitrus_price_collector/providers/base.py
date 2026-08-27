"""Provider interface contract."""

from __future__ import annotations

from typing import Protocol

from ..models import SearchResult


class PriceProvider(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[SearchResult]: ...
