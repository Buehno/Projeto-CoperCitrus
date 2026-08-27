import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from copercitrus_price_collector.errors import SpreadsheetError
from copercitrus_price_collector.models import CollectionRow, ProductInput, SearchResult
from copercitrus_price_collector.spreadsheet import create_template, export_results, read_products


class SpreadsheetTest(unittest.TestCase):
    def test_reads_flexible_headers_and_builds_query(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "produtos.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Nome", "Marca", "Modelo", "Código do produto"])
            sheet.append(["Notebook", "Dell", "Inspiron 15", "ABC-1"])
            workbook.save(path)
            workbook.close()

            products = read_products(path)

            self.assertEqual(1, len(products))
            self.assertEqual("Notebook Dell Inspiron 15 ABC-1", products[0].query)
            self.assertEqual(2, products[0].row_number)

    def test_rejects_missing_product_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "produtos.xlsx"
            workbook = Workbook()
            workbook.active.append(["Marca", "Modelo"])
            workbook.active.append(["Dell", "X"])
            workbook.save(path)
            workbook.close()

            with self.assertRaisesRegex(SpreadsheetError, "Produto"):
                read_products(path)

    def test_creates_template_and_result_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            template_path = create_template(Path(directory) / "modelo.xlsx")
            template = load_workbook(template_path)
            self.assertEqual(
                ["Produto", "Marca", "Modelo", "SKU"],
                [cell.value for cell in template["Produtos"][1]],
            )
            template.close()

            product = ProductInput(2, "Mouse", "Logitech", "M170", "SKU-1")
            result = SearchResult(
                provider="Shopee",
                rank=1,
                title="Mouse Logitech M170",
                description="Mouse sem fio",
                price_min=79.9,
                price_max=79.9,
                currency="BRL",
                purchase_url="https://shopee.example/item",
                seller="Loja",
            )
            output = export_results(
                [CollectionRow.success(product, result)],
                Path(directory) / "resultado.xlsx",
            )
            workbook = load_workbook(output)
            self.assertEqual(["Resultados", "Resumo"], workbook.sheetnames)
            self.assertEqual("OK", workbook["Resultados"]["U2"].value)
            self.assertEqual(79.9, workbook["Resumo"]["D2"].value)
            self.assertEqual(
                "https://shopee.example/item",
                workbook["Resumo"]["G2"].hyperlink.target,
            )
            workbook.close()


if __name__ == "__main__":
    unittest.main()
