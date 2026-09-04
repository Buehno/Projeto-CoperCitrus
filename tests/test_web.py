import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from copercitrus_price_collector import web
from copercitrus_price_collector.database import DatabaseError


def _db_com_dados():
    db = MagicMock()
    db.resumo.return_value = {
        "coletas": 3,
        "buscas": 12,
        "ofertas": 27,
        "produtos": 6,
        "erros": 1,
        "ultima_coleta": datetime(2026, 9, 4, 15, 30, tzinfo=timezone.utc),
        "preco_medio": Decimal("128.4567"),
    }
    db.ofertas_por_fonte.return_value = [
        {"fonte": "Google Shopping", "ofertas": 18,
         "preco_medio": Decimal("130.00"), "menor_preco": Decimal("49.90")},
        {"fonte": "Shopee", "ofertas": 9,
         "preco_medio": Decimal("120.00"), "menor_preco": Decimal("39.90")},
    ]
    db.distribuicao_classificacao.return_value = [
        {"classificacao": "COMPATIVEL", "total": 20},
        {"classificacao": "SIMILAR", "total": 7},
    ]
    db.melhor_preco_por_produto.return_value = [
        {
            "produto": "Oleo lubrificante",
            "fonte": "Google Shopping",
            "titulo": "Oleo lubrificante Ipiranga 1L",
            "marca": "Ipiranga",
            "quantidade_embalagem": "1 L",
            "preco_min": Decimal("49.90"),
            "moeda": "R$",
            "url_compra": "https://loja.example/produto/oleo-ipiranga-1l",
            "vendedor": "Loja A",
            "similaridade": Decimal("91.50"),
            "classificacao": "COMPATIVEL",
        }
    ]
    db.maiores_dispersoes.return_value = [
        {"produto": "Oleo lubrificante", "ofertas": 4, "menor": Decimal("49.90"),
         "maior": Decimal("89.90"), "diferenca": Decimal("40.00")},
    ]
    db.buscas_sem_oferta.return_value = [
        {"produto": "Filtro raro", "fonte": "Shopee", "status": "SEM_RESULTADO",
         "erro": None, "coletado_em": datetime(2026, 9, 4, tzinfo=timezone.utc)},
    ]
    db.list_runs.return_value = [{"id": 3, "status": "CONCLUIDA"}]
    db.get_run.return_value = {"id": 3, "status": "CONCLUIDA"}
    db.list_results.return_value = [{"busca_id": 1, "produto": "Oleo"}]
    return db


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.db = _db_com_dados()
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


class DashboardTest(WebTestCase):
    def test_renders_html_with_kpis_and_prices(self):
        response = self.client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertIn("text/html", response.headers["content-type"])
        corpo = response.text
        self.assertIn("Dashboard de precos", corpo)
        self.assertIn("Oleo lubrificante", corpo)
        self.assertIn("R$ 49,90", corpo)
        self.assertIn("Google Shopping", corpo)

    def test_product_link_points_to_its_own_offer(self):
        corpo = self.client.get("/").text

        self.assertIn("https://loja.example/produto/oleo-ipiranga-1l", corpo)
        self.assertIn("noopener noreferrer nofollow", corpo)

    def test_empty_database_shows_guidance_not_an_error(self):
        self.db.resumo.return_value = {"ofertas": 0}

        response = self.client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertIn("Banco vazio", response.text)
        self.assertIn("copercitrus-price collect", response.text)

    def test_without_database_returns_503_page(self):
        web._state["database"] = None

        response = self.client.get("/")

        self.assertEqual(503, response.status_code)
        self.assertIn("DATABASE_URL", response.text)

    def test_database_failure_renders_page_instead_of_stacktrace(self):
        self.db.resumo.side_effect = DatabaseError("conexao recusada")

        response = self.client.get("/")

        self.assertEqual(503, response.status_code)
        self.assertIn("Sem conexao com o banco", response.text)
        self.assertIn("conexao recusada", response.text)


class EscapingTest(WebTestCase):
    """Titulo, vendedor e link vem de paginas de terceiros."""

    def test_scraped_title_is_escaped(self):
        self.db.melhor_preco_por_produto.return_value = [
            {
                "produto": "<img src=x onerror=alert(1)>",
                "fonte": "Shopee",
                "titulo": "<script>alert('xss')</script>",
                "marca": None,
                "quantidade_embalagem": None,
                "preco_min": Decimal("10.00"),
                "moeda": "R$",
                "url_compra": "https://ok.example/p",
                "vendedor": None,
                "similaridade": None,
                "classificacao": None,
            }
        ]

        corpo = self.client.get("/").text

        self.assertNotIn("<script>alert('xss')</script>", corpo)
        self.assertNotIn("<img src=x onerror", corpo)
        self.assertIn("&lt;script&gt;", corpo)

    def test_javascript_url_is_dropped(self):
        linha = self.db.melhor_preco_por_produto.return_value[0]
        linha["url_compra"] = "javascript:alert(1)"

        corpo = self.client.get("/").text

        self.assertNotIn("javascript:alert(1)", corpo)
        self.assertIn("sem link", corpo)

    def test_only_http_schemes_survive(self):
        self.assertEqual("https://a.example/p", web.safe_url("https://a.example/p"))
        self.assertEqual("http://a.example/p", web.safe_url("http://a.example/p"))
        self.assertIsNone(web.safe_url("javascript:alert(1)"))
        self.assertIsNone(web.safe_url("data:text/html,<script>"))
        self.assertIsNone(web.safe_url(None))


class SemEntradaDeDadosTest(WebTestCase):
    def test_write_endpoints_no_longer_exist(self):
        for rota in ("/buscas", "/buscas/planilha"):
            resposta = self.client.post(rota, json={"produtos": [{"produto": "x"}]})
            self.assertIn(
                resposta.status_code, (404, 405), f"{rota} deveria ter sumido"
            )

    def test_app_exposes_no_write_routes(self):
        metodos = set()
        for rota in web.app.routes:
            metodos |= getattr(rota, "methods", set())
        self.assertFalse(metodos & {"POST", "PUT", "PATCH", "DELETE"})

    def test_app_does_not_import_the_browser_stack(self):
        import inspect

        fonte = inspect.getsource(web)
        for proibido in ("BrowserRpa", "execute_collection", "playwright"):
            self.assertNotIn(proibido, fonte)


class HealthTest(WebTestCase):
    def test_ok(self):
        response = self.client.get("/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok", "banco": "ok"}, response.json())

    def test_sem_banco(self):
        web._state["database"] = None
        self.assertEqual(503, self.client.get("/health").status_code)

    def test_banco_com_erro(self):
        self.db.ping.side_effect = DatabaseError("recusada")
        response = self.client.get("/health")
        self.assertEqual(503, response.status_code)
        self.assertEqual("erro", response.json()["banco"])


class ApiTest(WebTestCase):
    def test_resumo(self):
        response = self.client.get("/api/resumo")
        self.assertEqual(200, response.status_code)
        self.assertEqual(27, response.json()["resumo"]["ofertas"])

    def test_precos(self):
        response = self.client.get("/api/precos?limit=10")
        self.assertEqual(200, response.status_code)
        self.db.melhor_preco_por_produto.assert_called_once_with(limit=10)

    def test_precos_clamps_limit(self):
        self.client.get("/api/precos?limit=999999")
        self.assertEqual(
            1000, self.db.melhor_preco_por_produto.call_args.kwargs["limit"]
        )

    def test_coletas(self):
        response = self.client.get("/api/coletas")
        self.assertEqual(200, response.status_code)
        self.assertEqual(3, response.json()["coletas"][0]["id"])

    def test_resultados_de_coleta_inexistente(self):
        self.db.get_run.return_value = None
        self.assertEqual(
            404, self.client.get("/api/coletas/999/resultados").status_code
        )


class FormatacaoTest(unittest.TestCase):
    def test_moeda_no_formato_brasileiro(self):
        self.assertEqual("R$ 1.234,50", web.moeda(Decimal("1234.5")))
        self.assertEqual("R$ 49,90", web.moeda(Decimal("49.90")))
        self.assertEqual("—", web.moeda(None))

    def test_data_hora(self):
        self.assertEqual(
            "04/09/2026 15:30",
            web.data_hora(datetime(2026, 9, 4, 15, 30, tzinfo=timezone.utc)),
        )
        self.assertEqual("—", web.data_hora(None))

    def test_dominio(self):
        self.assertEqual("loja.example", web.dominio("https://loja.example/p/1"))
        self.assertEqual("—", web.dominio(None))


if __name__ == "__main__":
    unittest.main()
