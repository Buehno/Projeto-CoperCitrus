"""RPA da pagina publica de resultados do Google Shopping."""

from __future__ import annotations

from urllib.parse import urlencode

from ..browser import BrowserRpa, SiteSelectors
from ..models import ProductInput, SearchResult
from .common import map_card


GOOGLE_SELECTORS = SiteSelectors(
    cards=(
        "[data-docid]",
        ".sh-dgr__content",
        ".sh-dlr__list-result",
        ".pla-unit",
        "div[role='listitem']",
        "div[aria-label*='resultado']",
        "div[aria-label*='product']",
        "div[role='article']",
    ),
    titles=(
        "h3",
        "h2",
        ".tAxDx",
        ".sh-np__product-title",
        "[role='heading']",
        "div[role='heading']",
    ),
    prices=(
        ".a8Pemb",
        ".kHxwFf",
        ".T14wmb",
        ".HRLxBb",
        "[aria-label*='R$']",
        "span[aria-label*='R$']",
        "div[data-price]",
    ),
    # Do mais especifico para o mais generico: `_first_attribute` para no
    # primeiro que casar, entao `a[href]` no inicio anularia os demais e
    # devolveria qualquer ancora do card (loja, badge, imagem) como link.
    links=(
        "a[href*='/shopping/product/']",
        "a[href*='/products/']",
        "a[href*='/url?']",
        "a[href]",
    ),
    descriptions=(".vEjMR", ".sh-np__product-title", ".hP4iBf", ".b5YqMe"),
    sellers=(".aULzUe", ".IuHnof", ".sh-np__seller-container", "div[aria-label*='loja']"),
)


class GoogleShoppingProvider:
    name = "Google Shopping"
    endpoint = "https://www.google.com/search"

    def __init__(self, browser: BrowserRpa) -> None:
        self.browser = browser

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]:
        params = {"tbm": "shop", "hl": "pt-BR", "gl": "br", "q": product.query}
        cards = self.browser.collect_cards(
            self.name,
            f"{self.endpoint}?{urlencode(params)}",
            GOOGLE_SELECTORS,
            limit,
        )
        return [
            map_card(self.name, product, card, index)
            for index, card in enumerate(cards, 1)
        ]
