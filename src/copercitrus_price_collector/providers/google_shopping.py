"""Google Shopping integration through SerpAPI."""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..errors import ProviderError
from ..http import JsonHttpClient
from ..models import SearchResult


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    match = re.search(r"\d[\d.,]*", text)
    if not match:
        return None
    number = match.group(0)
    if "," in number and "." in number:
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif "," in number:
        decimal_digits = len(number.rsplit(",", 1)[1])
        number = number.replace(".", "")
        number = number.replace(",", "." if decimal_digits <= 2 else "")
    try:
        return float(number)
    except ValueError:
        return None


class GoogleShoppingProvider:
    name = "Google Shopping"
    endpoint = "https://serpapi.com/search.json"

    def __init__(
        self,
        api_key: str,
        http: JsonHttpClient,
        location: str = "Sao Paulo, State of Sao Paulo, Brazil",
    ) -> None:
        self.api_key = api_key
        self.http = http
        self.location = location

    def search(self, query: str, limit: int) -> list[SearchResult]:
        payload = self.http.get_json(
            self.endpoint,
            {
                "engine": "google_shopping",
                "q": query,
                "api_key": self.api_key,
                "gl": "br",
                "hl": "pt-br",
                "google_domain": "google.com.br",
                "location": self.location,
            },
        )
        if payload.get("error"):
            raise ProviderError(f"Google Shopping: {payload['error']}")

        results: list[SearchResult] = []
        seen: set[str] = set()
        for node in self._nodes(payload):
            title = str(node.get("title") or "").strip()
            purchase_url = str(node.get("link") or node.get("product_link") or "").strip()
            if not title or not purchase_url:
                continue
            identity = str(node.get("product_id") or purchase_url).casefold()
            if identity in seen:
                continue
            seen.add(identity)

            description = str(node.get("snippet") or "").strip()
            if not description:
                extensions = node.get("extensions")
                if isinstance(extensions, list):
                    description = " | ".join(str(item) for item in extensions if item)
            if not description:
                description = title

            price_min = _number(node.get("extracted_price"))
            if price_min is None:
                price_min = _number(node.get("price"))
            price_max = _number(node.get("extracted_price_max")) or price_min

            results.append(
                SearchResult(
                    provider=self.name,
                    rank=len(results) + 1,
                    title=title,
                    description=description,
                    price_min=price_min,
                    price_max=price_max,
                    currency="BRL",
                    purchase_url=purchase_url,
                    seller=_optional_text(node.get("source")),
                    rating=_number(node.get("rating")),
                    review_count=_optional_int(node.get("reviews")),
                    image_url=_optional_text(
                        node.get("thumbnail") or node.get("serpapi_thumbnail")
                    ),
                )
            )
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _nodes(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        for key in ("shopping_results", "inline_shopping_results"):
            items = payload.get(key)
            if isinstance(items, list):
                yield from (item for item in items if isinstance(item, dict))

        categories = payload.get("categorized_shopping_results")
        if isinstance(categories, list):
            for category in categories:
                if not isinstance(category, dict):
                    continue
                items = category.get("shopping_results")
                if isinstance(items, list):
                    yield from (item for item in items if isinstance(item, dict))


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
