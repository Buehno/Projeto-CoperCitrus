import unittest

from copercitrus_price_collector.browser import (
    BLOCK_MARKERS,
    BrowserBlockedError,
    BrowserProductCard,
    BrowserRpa,
)
from copercitrus_price_collector.models import ProductInput
from copercitrus_price_collector.providers.google_shopping import GoogleShoppingProvider


class FakeBrowser:
    def __init__(self, cards):
        self.cards = cards
        self.calls = []

    def collect_cards(self, provider_name, url, selectors, limit):
        self.calls.append((provider_name, url, selectors, limit))
        return self.cards[:limit]


class GoogleShoppingProviderTest(unittest.TestCase):
    def test_builds_browser_search_and_maps_visible_cards(self):
        browser = FakeBrowser(
            [
                BrowserProductCard(
                    title="Mouse sem fio Logitech M170 kit 2 unidades",
                    price_text="R$ 79,90",
                    purchase_url="https://loja.example/m170",
                    seller="Loja A",
                    raw_text="Mouse Logitech M170 - kit com 2 unidades",
                )
            ]
        )
        provider = GoogleShoppingProvider(browser)
        product = ProductInput(2, "Mouse sem fio", "Logitech", "M170", "SKU-1", "10")

        results = provider.search(product, 5)

        self.assertEqual(1, len(results))
        self.assertEqual(79.9, results[0].price_min)
        self.assertEqual("Logitech", results[0].brand)
        self.assertEqual("2 un", results[0].package_quantity)
        self.assertEqual("COMPATIVEL", results[0].match_type)
        self.assertIn("tbm=shop", browser.calls[0][1])
        self.assertIn("Mouse+sem+fio+Logitech+M170+SKU-1", browser.calls[0][1])
        self.assertNotIn("api", browser.calls[0][1].casefold())

    def test_detects_google_verification_prompt_as_block(self):
        class Body:
            def __init__(self, text):
                self.text = text

            def inner_text(self, timeout=0):
                return self.text

        class Page:
            def locator(self, selector):
                return Body("Verifique para continuar")

        with self.assertRaises(BrowserBlockedError):
            BrowserRpa._raise_if_blocked(Page(), "Google Shopping")

        self.assertIn("verifique para continuar", " ".join(BLOCK_MARKERS).casefold())


if __name__ == "__main__":
    unittest.main()
