import hashlib
import json
import unittest

from copercitrus_price_collector.providers.shopee_affiliate import ShopeeAffiliateProvider


class FakeHttp:
    def __init__(self):
        self.body = None
        self.headers = None

    def get_json(self, url, params, headers=None):
        raise AssertionError("not expected")

    def post_json(self, url, body, headers=None):
        self.body = body
        self.headers = headers
        return {
            "data": {
                "productOfferV2": {
                    "nodes": [
                        {
                            "productName": "Mouse sem fio",
                            "priceMin": "89.90",
                            "priceMax": "99.90",
                            "productLink": "https://shopee.com.br/product/1/2",
                            "shopName": "Loja Oficial",
                            "ratingStar": "4.7",
                            "sales": 123,
                        }
                    ]
                }
            }
        }


class ShopeeAffiliateProviderTest(unittest.TestCase):
    def test_signs_exact_payload_and_maps_product(self):
        http = FakeHttp()
        provider = ShopeeAffiliateProvider(
            "123", "top-secret", http, clock=lambda: 1_700_000_000
        )

        results = provider.search("mouse", 3)

        expected_signature = hashlib.sha256(
            f"1231700000000{http.body}top-secret".encode()
        ).hexdigest()
        self.assertIn(expected_signature, http.headers["Authorization"])
        decoded = json.loads(http.body)
        self.assertEqual("mouse", decoded["variables"]["keyword"])
        self.assertEqual(3, decoded["variables"]["limit"])
        self.assertEqual(89.9, results[0].price_min)
        self.assertEqual(99.9, results[0].price_max)
        self.assertEqual(123, results[0].sold_count)


if __name__ == "__main__":
    unittest.main()
