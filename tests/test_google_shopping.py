import unittest

from copercitrus_price_collector.providers.google_shopping import GoogleShoppingProvider


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload
        self.params = None

    def get_json(self, url, params, headers=None):
        self.params = params
        return self.payload

    def post_json(self, url, body, headers=None):
        raise AssertionError("not expected")


class GoogleShoppingProviderTest(unittest.TestCase):
    def test_maps_and_deduplicates_results(self):
        http = FakeHttp(
            {
                "inline_shopping_results": [
                    {
                        "title": "Notebook X",
                        "extracted_price": 3999.9,
                        "link": "https://loja.example/x",
                        "source": "Loja A",
                        "snippet": "16 GB RAM",
                        "rating": 4.8,
                        "reviews": 42,
                        "product_id": "x",
                    }
                ],
                "categorized_shopping_results": [
                    {
                        "shopping_results": [
                            {
                                "title": "Notebook X repetido",
                                "price": "R$ 3.999,90",
                                "product_link": "https://google.example/x",
                                "product_id": "x",
                            },
                            {
                                "title": "Notebook Y",
                                "price": "R$ 4.250,00",
                                "product_link": "https://google.example/y",
                                "source": "Loja B",
                            },
                        ]
                    }
                ],
            }
        )
        provider = GoogleShoppingProvider("secret", http)

        results = provider.search("notebook", 5)

        self.assertEqual(2, len(results))
        self.assertEqual(3999.9, results[0].price_min)
        self.assertEqual("16 GB RAM", results[0].description)
        self.assertEqual(4250.0, results[1].price_min)
        self.assertEqual("br", http.params["gl"])
        self.assertEqual("secret", http.params["api_key"])


if __name__ == "__main__":
    unittest.main()
