"""Input and output data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class ProductInput:
    row_number: int
    produto: str
    marca: str | None = None
    modelo: str | None = None
    sku: str | None = None
    quantidade_solicitada: str | None = None

    @property
    def query(self) -> str:
        values = [self.produto, self.marca, self.modelo, self.sku]
        seen: set[str] = set()
        parts: list[str] = []
        for value in values:
            if not value:
                continue
            normalized = value.strip().casefold()
            if normalized and normalized not in seen:
                parts.append(value.strip())
                seen.add(normalized)
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class SearchResult:
    provider: str
    rank: int
    title: str
    description: str
    price_min: float | None
    price_max: float | None
    currency: str
    purchase_url: str
    brand: str | None = None
    package_quantity: str | None = None
    similarity_score: float = 0.0
    match_type: str = "DIVERGENTE"
    seller: str | None = None
    rating: float | None = None
    review_count: int | None = None
    sold_count: int | None = None
    image_url: str | None = None

    @property
    def possible_similar(self) -> bool:
        return self.match_type == "SIMILAR"


@dataclass(frozen=True, slots=True)
class CollectionRow:
    product: ProductInput
    provider: str
    status: str
    collected_at: datetime
    result: SearchResult | None = None
    error: str | None = None

    @classmethod
    def success(cls, product: ProductInput, result: SearchResult) -> CollectionRow:
        return cls(
            product=product,
            provider=result.provider,
            status="OK",
            result=result,
            collected_at=datetime.now(timezone.utc),
        )

    @classmethod
    def empty(cls, product: ProductInput, provider: str) -> CollectionRow:
        return cls(
            product=product,
            provider=provider,
            status="SEM_RESULTADO",
            collected_at=datetime.now(timezone.utc),
        )

    @classmethod
    def failed(cls, product: ProductInput, provider: str, error: str) -> CollectionRow:
        return cls(
            product=product,
            provider=provider,
            status="ERRO",
            error=error,
            collected_at=datetime.now(timezone.utc),
        )
