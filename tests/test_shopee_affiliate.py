import unittest

from copercitrus_price_collector.browser import BrowserProductCard
from copercitrus_price_collector.models import ProductInput
from copercitrus_price_collector.providers.shopee_affiliate import ShopeeProvider


class FakeBrowser:
    def __init__(self, cards):
        self.cards = cards
        self.url = None

    def collect_cards(self, provider_name, url, selectors, limit):
        self.url = url
        return self.cards[:limit]


class ShopeeProviderTest(unittest.TestCase):
    def test_uses_public_search_page_and_classifies_similar_product(self):
        browser = FakeBrowser(
            [
                BrowserProductCard(
                    title="Furadeira parafusadeira Bosch GSB 12V",
                    price_text="R$ 499,00",
                    purchase_url="https://shopee.com.br/product/1/2",
                    seller="Loja Oficial",
                )
            ]
        )
        provider = ShopeeProvider(browser)

        results = provider.search(
            ProductInput(2, "Parafusadeira", "Bosch", "GSR 12V"), 3
        )

        self.assertEqual(499.0, results[0].price_min)
        self.assertEqual("Bosch", results[0].brand)
        self.assertEqual("SIMILAR", results[0].match_type)
        self.assertTrue(results[0].possible_similar)
        self.assertIn("shopee.com.br/search?keyword=", browser.url)


if __name__ == "__main__":
    unittest.main()
