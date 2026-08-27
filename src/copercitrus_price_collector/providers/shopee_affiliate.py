"""Shopee Affiliate API integration."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable

from ..errors import ProviderError
from ..http import JsonHttpClient
from ..models import SearchResult
from .google_shopping import _number, _optional_int, _optional_text


PRODUCT_QUERY = """
query ProductSearch($keyword: String!, $page: Int!, $limit: Int!) {
  productOfferV2(
    listType: 0
    sortType: 1
    keyword: $keyword
    page: $page
    limit: $limit
  ) {
    nodes {
      itemId
      shopId
      productName
      priceMin
      priceMax
      priceDiscountRate
      imageUrl
      productLink
      offerLink
      shopName
      ratingStar
      sales
    }
  }
}
""".strip()


class ShopeeAffiliateProvider:
    name = "Shopee"
    endpoint = "https://open-api.affiliate.shopee.com.br/graphql"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        http: JsonHttpClient,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.http = http
        self.clock = clock

    def search(self, query: str, limit: int) -> list[SearchResult]:
        body = json.dumps(
            {
                "query": PRODUCT_QUERY,
                "variables": {"keyword": query, "page": 1, "limit": limit},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        timestamp = int(self.clock())
        signature = hashlib.sha256(
            f"{self.app_id}{timestamp}{body}{self.app_secret}".encode("utf-8")
        ).hexdigest()
        authorization = (
            f"SHA256 Credential={self.app_id}, "
            f"Timestamp={timestamp}, Signature={signature}"
        )
        payload = self.http.post_json(
            self.endpoint,
            body,
            {"Authorization": authorization, "Content-Type": "application/json"},
        )
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            message = first.get("message") if isinstance(first, dict) else str(first)
            raise ProviderError(f"Shopee: {message or 'erro nao detalhado'}")

        data = payload.get("data")
        connection = data.get("productOfferV2") if isinstance(data, dict) else None
        nodes = connection.get("nodes") if isinstance(connection, dict) else None
        if nodes is None:
            raise ProviderError("Shopee retornou uma estrutura inesperada")
        if not isinstance(nodes, list):
            raise ProviderError("Shopee retornou uma lista de produtos invalida")

        results: list[SearchResult] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = str(node.get("productName") or "").strip()
            purchase_url = str(node.get("productLink") or node.get("offerLink") or "").strip()
            if not title or not purchase_url:
                continue
            price_min = _number(node.get("priceMin"))
            price_max = _number(node.get("priceMax")) or price_min
            results.append(
                SearchResult(
                    provider=self.name,
                    rank=len(results) + 1,
                    title=title,
                    description=title,
                    price_min=price_min,
                    price_max=price_max,
                    currency="BRL",
                    purchase_url=purchase_url,
                    seller=_optional_text(node.get("shopName")),
                    rating=_number(node.get("ratingStar")),
                    sold_count=_optional_int(node.get("sales")),
                    image_url=_optional_text(node.get("imageUrl")),
                )
            )
            if len(results) >= limit:
                break
        return results
