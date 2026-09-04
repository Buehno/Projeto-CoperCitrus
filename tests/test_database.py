import unittest
from contextlib import contextmanager
from datetime import datetime, timezone

from copercitrus_price_collector.database import (
    SCHEMA_STATEMENTS,
    Database,
    DatabaseError,
    database_url,
    totals_from_rows,
)
from copercitrus_price_collector.models import CollectionRow, ProductInput, SearchResult


def _result(**overrides):
    base = dict(
        provider="google",
        rank=1,
        title="Oleo lubrificante 1L",
        description="descricao",
        price_min=49.9,
        price_max=49.9,
        currency="BRL",
        purchase_url="https://exemplo.com/p/1",
        brand="Marca",
        package_quantity="1 L",
        similarity_score=91.5,
        match_type="COMPATIVEL",
    )
    base.update(overrides)
    return SearchResult(**base)


class FakeCursor:
    def __init__(self, log):
        self.log = log
        self._next_id = 100

    def execute(self, sql, params=None):
        self.log.append(("execute", " ".join(sql.split()), params))

    def executemany(self, sql, params):
        self.log.append(("executemany", " ".join(sql.split()), list(params)))

    def fetchone(self):
        self._next_id += 1
        return (self._next_id,)

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, log):
        self.log = log
        self.commits = 0

    def cursor(self, row_factory=None):
        return FakeCursor(self.log)

    def commit(self):
        self.commits += 1


class FakeDatabase(Database):
    def __init__(self):
        self.log = []
        self.conn = FakeConnection(self.log)

    @contextmanager
    def connection(self):
        yield self.conn


class SchemaTest(unittest.TestCase):
    def test_schema_is_idempotent(self):
        for statement in SCHEMA_STATEMENTS:
            self.assertIn("IF NOT EXISTS", statement)

    def test_create_schema_runs_every_statement_and_commits(self):
        db = FakeDatabase()

        db.create_schema()

        executed = [entry for entry in db.log if entry[0] == "execute"]
        self.assertEqual(len(SCHEMA_STATEMENTS), len(executed))
        self.assertEqual(1, db.conn.commits)


class DsnTest(unittest.TestCase):
    def test_empty_dsn_is_rejected(self):
        with self.assertRaises(DatabaseError):
            Database("   ")

    def test_database_url_prefers_railway_variable(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://a/b"}, clear=True):
            self.assertEqual("postgresql://a/b", database_url())
        with patch.dict(os.environ, {"POSTGRES_URL": "postgresql://c/d"}, clear=True):
            self.assertEqual("postgresql://c/d", database_url())
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(database_url())


class SaveRowsTest(unittest.TestCase):
    def setUp(self):
        self.product = ProductInput(2, "Oleo lubrificante", "Marca", None, "SKU1", "10")

    def test_offers_of_same_product_share_a_single_busca(self):
        rows = [
            CollectionRow.success(self.product, _result(rank=1)),
            CollectionRow.success(self.product, _result(rank=2)),
        ]
        db = FakeDatabase()

        created = db.save_rows(coleta_id=7, rows=rows)

        self.assertEqual(1, created)
        inserts = [e for e in db.log if e[0] == "execute" and "INSERT INTO buscas" in e[1]]
        self.assertEqual(1, len(inserts))
        self.assertEqual("OK", inserts[0][2][9])
        batch = [e for e in db.log if e[0] == "executemany"]
        self.assertEqual(1, len(batch))
        self.assertEqual(2, len(batch[0][2]))

    def test_different_providers_are_separate_buscas(self):
        rows = [
            CollectionRow.success(self.product, _result(provider="google")),
            CollectionRow.success(self.product, _result(provider="shopee")),
        ]
        db = FakeDatabase()

        self.assertEqual(2, db.save_rows(coleta_id=7, rows=rows))

    def test_error_row_is_stored_with_message_and_no_result(self):
        rows = [CollectionRow.failed(self.product, "shopee", "CAPTCHA detectado")]
        db = FakeDatabase()

        db.save_rows(coleta_id=7, rows=rows)

        insert = next(e for e in db.log if "INSERT INTO buscas" in e[1])
        self.assertEqual("ERRO", insert[2][9])
        self.assertEqual("CAPTCHA detectado", insert[2][10])
        self.assertFalse([e for e in db.log if e[0] == "executemany"])

    def test_empty_row_is_stored_as_sem_resultado(self):
        rows = [CollectionRow.empty(self.product, "google")]
        db = FakeDatabase()

        db.save_rows(coleta_id=7, rows=rows)

        insert = next(e for e in db.log if "INSERT INTO buscas" in e[1])
        self.assertEqual("SEM_RESULTADO", insert[2][9])

    def test_no_rows_does_not_touch_the_database(self):
        db = FakeDatabase()

        self.assertEqual(0, db.save_rows(coleta_id=7, rows=[]))
        self.assertEqual([], db.log)

    def test_busca_carries_the_input_product_fields(self):
        db = FakeDatabase()

        db.save_rows(7, [CollectionRow.success(self.product, _result())])

        params = next(e for e in db.log if "INSERT INTO buscas" in e[1])[2]
        self.assertEqual(7, params[0])
        self.assertEqual(2, params[1])
        self.assertEqual("Oleo lubrificante", params[2])
        self.assertEqual("Marca", params[3])
        self.assertEqual("SKU1", params[5])
        self.assertEqual("10", params[6])
        self.assertEqual("Oleo lubrificante Marca SKU1", params[7])


class FinishRunTest(unittest.TestCase):
    def test_finish_run_records_status_and_totals(self):
        db = FakeDatabase()
        product = ProductInput(2, "Produto")
        rows = [
            CollectionRow.success(product, _result()),
            CollectionRow.success(product, _result(match_type="SIMILAR")),
            CollectionRow.failed(product, "shopee", "erro"),
        ]
        totals = totals_from_rows(rows, total_produtos=1)

        db.finish_run(9, status="CONCLUIDA", totals=totals)

        params = next(e for e in db.log if "UPDATE coletas" in e[1])[2]
        self.assertEqual("CONCLUIDA", params[0])
        self.assertIsInstance(params[1], datetime)
        self.assertEqual(timezone.utc, params[1].tzinfo)
        self.assertEqual((1, 2, 1, 1), params[2:6])
        self.assertEqual(9, params[7])


class TotalsTest(unittest.TestCase):
    def test_totals_count_offers_similars_and_errors(self):
        product = ProductInput(2, "Produto")
        rows = [
            CollectionRow.success(product, _result(match_type="COMPATIVEL")),
            CollectionRow.success(product, _result(match_type="SIMILAR")),
            CollectionRow.empty(product, "google"),
            CollectionRow.failed(product, "shopee", "erro"),
        ]

        totals = totals_from_rows(rows, total_produtos=3)

        self.assertEqual(3, totals.total_produtos)
        self.assertEqual(2, totals.total_ofertas)
        self.assertEqual(1, totals.total_similares)
        self.assertEqual(1, totals.total_erros)


if __name__ == "__main__":
    unittest.main()
