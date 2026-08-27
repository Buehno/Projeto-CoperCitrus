"""RPA da pagina publica de pesquisa da Shopee Brasil."""

from __future__ import annotations

from urllib.parse import urlencode

from ..browser import BrowserRpa, SiteSelectors
from ..models import ProductInput, SearchResult
from .common import map_card


SHOPEE_SELECTORS = SiteSelectors(
    cards=(
        "[data-sqe='item']",
        ".shopee-search-item-result__item",
        "li[class*='shopee-search-item-result']",
    ),
    titles=(
        "[data-sqe='name']",
        "div[class*='line-clamp-2']",
        "div[class*='line-clamp']",
    ),
    prices=(
        "[data-testid='item-card-price']",
        "div[class*='text-shopee-primary']",
        "span[class*='text-shopee-primary']",
    ),
    links=("a[href*='/product/']", "a[href*='-i.']", "a[href]"),
    descriptions=("[data-sqe='name']", "div[class*='line-clamp-2']"),
    sellers=("[data-sqe='shop-name']", "div[class*='shop-name']"),
)


class ShopeeProvider:
    name = "Shopee"
    endpoint = "https://shopee.com.br/search"

    def __init__(self, browser: BrowserRpa) -> None:
        self.browser = browser

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]:
        cards = self.browser.collect_cards(
            self.name,
            f"{self.endpoint}?{urlencode({'keyword': product.query})}",
            SHOPEE_SELECTORS,
            limit,
        )
        return [
            map_card(self.name, product, card, index)
            for index, card in enumerate(cards, 1)
        ]
