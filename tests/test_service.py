import unittest

from copercitrus_price_collector.errors import ProviderError
from copercitrus_price_collector.models import ProductInput, SearchResult
from copercitrus_price_collector.service import CollectionService


class SuccessProvider:
    name = "Fonte OK"

    def search(self, query, limit):
        return [
            SearchResult(
                provider=self.name,
                rank=1,
                title=query,
                description=query,
                price_min=10.0,
                price_max=10.0,
                currency="BRL",
                purchase_url="https://example.com",
            )
        ]


class FailureProvider:
    name = "Fonte Erro"

    def search(self, query, limit):
        raise ProviderError("indisponivel")


class CollectionServiceTest(unittest.TestCase):
    def test_keeps_batch_running_when_one_provider_fails(self):
        delays = []
        service = CollectionService(
            [SuccessProvider(), FailureProvider()],
            result_limit=2,
            request_delay_seconds=0.5,
            sleeper=delays.append,
        )

        rows = service.collect([ProductInput(2, "Produto")])

        self.assertEqual(["OK", "ERRO"], [row.status for row in rows])
        self.assertEqual([0.5], delays)
        self.assertEqual("indisponivel", rows[1].error)


if __name__ == "__main__":
    unittest.main()
