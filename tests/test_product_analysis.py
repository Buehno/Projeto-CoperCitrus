import unittest

from copercitrus_price_collector.models import ProductInput
from copercitrus_price_collector.product_analysis import (
    classify_match,
    extract_package_quantity,
    parse_price,
    similarity_score,
)


class ProductAnalysisTest(unittest.TestCase):
    def test_parses_brazilian_prices(self):
        self.assertEqual(1299.9, parse_price("a partir de R$ 1.299,90"))
        self.assertEqual(49.0, parse_price("R$ 49"))
        self.assertIsNone(parse_price("preco indisponivel"))

    def test_extracts_package_quantity(self):
        self.assertEqual("12 un", extract_package_quantity("Caixa com 12 unidades"))
        self.assertEqual("500 ml", extract_package_quantity("Frasco 500 ml"))
        self.assertIsNone(extract_package_quantity("Produto unitario"))

    def test_scores_and_classifies_match(self):
        product = ProductInput(2, "Mouse sem fio", "Logitech", "M170")
        compatible = similarity_score(product, "Mouse sem fio Logitech M170")
        divergent = similarity_score(product, "Teclado mecanico Redragon")
        self.assertEqual("COMPATIVEL", classify_match(compatible))
        self.assertEqual("DIVERGENTE", classify_match(divergent))


if __name__ == "__main__":
    unittest.main()
