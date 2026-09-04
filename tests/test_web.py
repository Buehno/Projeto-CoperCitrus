import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from copercitrus_price_collector import web
from copercitrus_price_collector.database import DatabaseError


class WebTestCase(unittest.TestCase):
    """Sobe a API com um banco falso; nenhum teste toca PostgreSQL ou browser."""

    def setUp(self):
        self.db = MagicMock()
        self.db.start_run.return_value = 55
        self.db.list_runs.return_value = [{"id": 55, "status": "CONCLUIDA"}]
        self.db.get_run.return_value = {"id": 55, "status": "CONCLUIDA"}
        self.db.list_results.return_value = [{"busca_id": 1, "produto": "Oleo"}]

        # lifespan roda sem DATABASE_URL e nao conecta em nada
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.client = TestClient(web.app)
        self.client.__enter__()
        web._state["database"] = self.db
        web._state["schema_ready"] = True

    def tearDown(self):
        web._state["database"] = None
        web._state["schema_ready"] = False
        self.client.__exit__(None, None, None)
        self.env.stop()
        if web._collection_lock.locked():
            web._collection_lock.release()


class HealthTest(WebTestCase):
    def test_health_is_ok_when_database_answers(self):
        response = self.client.get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok", "banco": "ok"}, response.json())

    def test_health_is_503_without_database(self):
        web._state["database"] = None

        response = self.client.get("/health")

        self.assertEqual(503, response.status_code)
        self.assertEqual("degradado", response.json()["status"])

    def test_health_is_503_when_database_fails(self):
        self.db.ping.side_effect = DatabaseError("conexao recusada")

        response = self.client.get("/health")

        self.assertEqual(503, response.status_code)
        self.assertEqual("erro", response.json()["banco"])

    def test_root_reports_database_state(self):
        response = self.client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertEqual("configurado", response.json()["banco"])
        self.assertEqual("pronto", response.json()["schema"])

    def test_root_answers_even_without_database(self):
        web._state["database"] = None
        web._state["schema_ready"] = False

        response = self.client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertEqual("nao configurado", response.json()["banco"])


class CriarBuscaTest(WebTestCase):
    def test_accepted_run_is_registered_and_returns_202(self):
        with patch.object(web, "threading") as threading_mock:
            response = self.client.post(
                "/buscas",
                json={"produtos": [{"produto": "Oleo lubrificante"}], "limit": 3},
            )

        self.assertEqual(202, response.status_code)
        body = response.json()
        self.assertEqual(55, body["coleta_id"])
        self.assertEqual("EM_ANDAMENTO", body["status"])
        self.assertEqual(1, body["total_produtos"])
        self.db.start_run.assert_called_once()
        self.assertEqual("api", self.db.start_run.call_args.kwargs["origem"])
        threading_mock.Thread.assert_called_once()

    def test_empty_product_list_is_rejected(self):
        response = self.client.post("/buscas", json={"produtos": []})

        self.assertEqual(422, response.status_code)
        self.db.start_run.assert_not_called()

    def test_unknown_provider_is_rejected(self):
        response = self.client.post(
            "/buscas",
            json={"produtos": [{"produto": "Oleo"}], "providers": ["amazon"]},
        )

        self.assertEqual(422, response.status_code)

    def test_limit_out_of_range_is_rejected(self):
        response = self.client.post(
            "/buscas", json={"produtos": [{"produto": "Oleo"}], "limit": 99}
        )

        self.assertEqual(422, response.status_code)

    def test_concurrent_run_returns_409(self):
        web._collection_lock.acquire()

        response = self.client.post(
            "/buscas", json={"produtos": [{"produto": "Oleo"}]}
        )

        self.assertEqual(409, response.status_code)
        self.db.start_run.assert_not_called()

    def test_without_database_returns_503(self):
        web._state["database"] = None

        response = self.client.post(
            "/buscas", json={"produtos": [{"produto": "Oleo"}]}
        )

        self.assertEqual(503, response.status_code)


class ApiKeyTest(WebTestCase):
    def test_write_endpoint_requires_key_when_configured(self):
        with patch.dict(os.environ, {"API_KEY": "segredo"}):
            response = self.client.post(
                "/buscas", json={"produtos": [{"produto": "Oleo"}]}
            )

        self.assertEqual(401, response.status_code)
        self.db.start_run.assert_not_called()

    def test_correct_key_is_accepted(self):
        with patch.dict(os.environ, {"API_KEY": "segredo"}), patch.object(
            web, "threading"
        ):
            response = self.client.post(
                "/buscas",
                json={"produtos": [{"produto": "Oleo"}]},
                headers={"X-API-Key": "segredo"},
            )

        self.assertEqual(202, response.status_code)

    def test_read_endpoint_stays_open(self):
        with patch.dict(os.environ, {"API_KEY": "segredo"}):
            response = self.client.get("/buscas")

        self.assertEqual(200, response.status_code)


class ConsultaTest(WebTestCase):
    def test_list_runs(self):
        response = self.client.get("/buscas?limit=10")

        self.assertEqual(200, response.status_code)
        self.assertEqual(55, response.json()["coletas"][0]["id"])
        self.db.list_runs.assert_called_once_with(limit=10, offset=0)

    def test_list_runs_clamps_limit(self):
        self.client.get("/buscas?limit=99999")

        self.assertEqual(200, self.db.list_runs.call_args.kwargs["limit"])

    def test_run_detail(self):
        response = self.client.get("/buscas/55")

        self.assertEqual(200, response.status_code)
        self.assertEqual("CONCLUIDA", response.json()["status"])

    def test_missing_run_returns_404(self):
        self.db.get_run.return_value = None

        self.assertEqual(404, self.client.get("/buscas/999").status_code)
        self.assertEqual(404, self.client.get("/buscas/999/resultados").status_code)

    def test_results_of_a_run(self):
        response = self.client.get("/buscas/55/resultados")

        self.assertEqual(200, response.status_code)
        self.assertEqual("Oleo", response.json()["resultados"][0]["produto"])

    def test_missing_spreadsheet_returns_404(self):
        self.assertEqual(404, self.client.get("/buscas/55/planilha").status_code)


class UploadTest(WebTestCase):
    def test_non_xlsx_upload_is_rejected(self):
        response = self.client.post(
            "/buscas/planilha",
            files={"arquivo": ("produtos.csv", b"a,b", "text/csv")},
        )

        self.assertEqual(400, response.status_code)
        self.db.start_run.assert_not_called()

    def test_invalid_xlsx_content_is_rejected(self):
        response = self.client.post(
            "/buscas/planilha",
            files={"arquivo": ("produtos.xlsx", b"nao e um xlsx", "application/xlsx")},
        )

        self.assertEqual(400, response.status_code)
        self.db.start_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
