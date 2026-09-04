import unittest
from unittest.mock import MagicMock, patch

from copercitrus_price_collector.database import RunTotals
from copercitrus_price_collector.errors import ConfigurationError, ProviderError
from copercitrus_price_collector.models import CollectionRow, ProductInput, SearchResult
from copercitrus_price_collector.runner import execute_collection, parse_providers
from copercitrus_price_collector.settings import Settings


def _settings():
    return Settings(
        headless=True,
        browser_channel=None,
        browser_user_data_dir=None,
        browser_cdp_url=None,
        browser_timeout_seconds=45.0,
        slow_mo_ms=0,
        request_delay_seconds=0.0,
        result_limit=5,
    )


class ParseProvidersTest(unittest.TestCase):
    def test_accepts_comma_separated_string(self):
        self.assertEqual(["google", "shopee"], parse_providers("google,shopee"))

    def test_accepts_list(self):
        self.assertEqual(["shopee"], parse_providers(["shopee"]))

    def test_normalizes_case_and_whitespace(self):
        self.assertEqual(["google"], parse_providers("  GOOGLE  "))

    def test_removes_duplicates_and_keeps_canonical_order(self):
        self.assertEqual(
            ["google", "shopee"], parse_providers("shopee,google,shopee")
        )

    def test_rejects_unknown_provider(self):
        with self.assertRaises(ConfigurationError):
            parse_providers("google,mercadolivre")

    def test_rejects_empty_selection(self):
        with self.assertRaises(ConfigurationError):
            parse_providers("  ,  ")


class ExecuteCollectionTest(unittest.TestCase):
    def setUp(self):
        self.products = [ProductInput(2, "Produto")]
        self.result = SearchResult(
            provider="google",
            rank=1,
            title="Produto 1L",
            description="d",
            price_min=10.0,
            price_max=10.0,
            currency="BRL",
            purchase_url="https://exemplo.com/1",
        )
        self.rows = [CollectionRow.success(self.products[0], self.result)]

    @patch("copercitrus_price_collector.runner.CollectionService")
    @patch("copercitrus_price_collector.runner.build_providers")
    @patch("copercitrus_price_collector.runner.BrowserRpa")
    def test_records_run_start_rows_and_finish(self, browser, build, service):
        service.return_value.collect.return_value = self.rows
        db = MagicMock()
        db.start_run.return_value = 42

        outcome = execute_collection(
            self.products,
            _settings(),
            providers="google",
            limit=5,
            delay=0.0,
            database=db,
            origem="api",
        )

        self.assertEqual(42, outcome.coleta_id)
        db.start_run.assert_called_once()
        self.assertEqual("api", db.start_run.call_args.kwargs["origem"])
        self.assertEqual(1, db.start_run.call_args.kwargs["total_produtos"])
        db.save_rows.assert_called_once_with(42, self.rows)
        db.finish_run.assert_called_once()
        self.assertEqual("CONCLUIDA", db.finish_run.call_args.kwargs["status"])
        self.assertEqual(
            RunTotals(1, 1, 0, 0), db.finish_run.call_args.kwargs["totals"]
        )

    @patch("copercitrus_price_collector.runner.CollectionService")
    @patch("copercitrus_price_collector.runner.build_providers")
    @patch("copercitrus_price_collector.runner.BrowserRpa")
    def test_marks_run_as_failed_when_browser_breaks(self, browser, build, service):
        browser.return_value.__enter__.side_effect = ProviderError("chromium caiu")
        db = MagicMock()
        db.start_run.return_value = 7

        with self.assertRaises(ProviderError):
            execute_collection(
                self.products,
                _settings(),
                providers="google",
                limit=5,
                delay=0.0,
                database=db,
            )

        db.finish_run.assert_called_once()
        self.assertEqual("FALHOU", db.finish_run.call_args.kwargs["status"])
        self.assertEqual("chromium caiu", db.finish_run.call_args.kwargs["erro"])
        db.save_rows.assert_not_called()

    @patch("copercitrus_price_collector.runner.CollectionService")
    @patch("copercitrus_price_collector.runner.build_providers")
    @patch("copercitrus_price_collector.runner.BrowserRpa")
    def test_runs_without_database(self, browser, build, service):
        service.return_value.collect.return_value = self.rows

        outcome = execute_collection(
            self.products,
            _settings(),
            providers="google,shopee",
            limit=5,
            delay=0.0,
            database=None,
        )

        self.assertIsNone(outcome.coleta_id)
        self.assertEqual(self.rows, outcome.rows)
        self.assertEqual(["google", "shopee"], outcome.parametros["providers"])

    @patch("copercitrus_price_collector.runner.BrowserRpa")
    def test_unknown_provider_fails_before_opening_the_browser(self, browser):
        db = MagicMock()

        with self.assertRaises(ConfigurationError):
            execute_collection(
                self.products,
                _settings(),
                providers="amazon",
                limit=5,
                delay=0.0,
                database=db,
            )

        browser.assert_not_called()
        db.start_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
