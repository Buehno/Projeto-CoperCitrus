from __future__ import annotations

import json
import random
import time
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import ProviderHttpError


class JsonHttpClient(Protocol):
    def get_json(
        self,
        url: str,
        params: Mapping[str, str | int | float],
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...

    def post_json(
        self,
        url: str,
        body: str,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...


class UrllibJsonHttpClient:
    def __init__(self, timeout: float = 30.0, max_retries: int = 3) -> None:
        self.timeout = timeout
        self.max_retries = max_retries

    def get_json(
        self,
        url: str,
        params: Mapping[str, str | int | float],
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        query = urlencode(params)
        return self._request("GET", f"{url}?{query}", None, headers)

    def post_json(
        self,
        url: str,
        body: str,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", url, body.encode("utf-8"), headers)

    def _request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "CoperCitrus-PriceCollector/0.1",
            **(dict(headers) if headers else {}),
        }
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json; charset=utf-8")

        last_error: ProviderHttpError | None = None
        for attempt in range(self.max_retries + 1):
            request = Request(url, data=body, headers=request_headers, method=method)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    decoded = json.loads(raw.decode("utf-8"))
                    if not isinstance(decoded, dict):
                        raise ProviderHttpError(None, "O provedor retornou JSON inesperado")
                    return decoded
            except HTTPError as exc:
                last_error = ProviderHttpError(exc.code, self._safe_http_message(exc))
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise last_error from exc
            except (URLError, TimeoutError):
                last_error = ProviderHttpError(None, "Falha de conexao com o provedor")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderHttpError(None, "O provedor retornou uma resposta invalida") from exc

            if attempt < self.max_retries:
                time.sleep((0.5 * (2**attempt)) + random.uniform(0.0, 0.25))

        assert last_error is not None
        raise last_error

    @staticmethod
    def _safe_http_message(error: HTTPError) -> str:
        if error.code in {401, 403}:
            return "Credencial recusada ou acesso nao autorizado pelo provedor"
        if error.code == 429:
            return "Limite de requisicoes do provedor atingido"
        if error.code >= 500:
            return "Provedor temporariamente indisponivel"
        return f"Provedor retornou HTTP {error.code}"
