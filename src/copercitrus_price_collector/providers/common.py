"""Mapeamento compartilhado dos cards visiveis para o modelo de saida."""

from __future__ import annotations

from ..browser import BrowserProductCard
from ..models import ProductInput, SearchResult
from ..product_analysis import (
    classify_match,
    extract_package_quantity,
    identify_brand,
    parse_price,
    similarity_score,
)


def map_card(
    provider_name: str,
    product: ProductInput,
    card: BrowserProductCard,
    rank: int,
) -> SearchResult:
    score = similarity_score(product, card.title)
    combined_text = " | ".join(
        value for value in (card.title, card.description, card.raw_text) if value
    )
    price = parse_price(card.price_text)
    return SearchResult(
        provider=provider_name,
        rank=rank,
        title=card.title,
        description=card.description or card.title,
        price_min=price,
        price_max=price,
        currency="BRL",
        purchase_url=card.purchase_url,
        brand=identify_brand(card.title, product.marca),
        package_quantity=extract_package_quantity(combined_text),
        similarity_score=score,
        match_type=classify_match(score),
        seller=card.seller,
        image_url=card.image_url,
    )
