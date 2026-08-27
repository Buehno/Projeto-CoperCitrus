from __future__ import annotations

import argparse
import sys

from .errors import ConfigurationError, PriceCollectorError
from .http import UrllibJsonHttpClient
from .providers import GoogleShoppingProvider, PriceProvider, ShopeeAffiliateProvider
from .service import CollectionService
from .settings import Settings
from .spreadsheet import create_template, export_results, read_products


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copercitrus-price",
        description="Coleta precos do Google Shopping e Shopee a partir de um Excel.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    template = subcommands.add_parser("template", help="cria uma planilha-modelo")
    template.add_argument("output", nargs="?", default="produtos.xlsx")

    collect = subcommands.add_parser("collect", help="processa uma planilha")
    collect.add_argument("input")
    collect.add_argument("--output", default="resultados/precos.xlsx")
    collect.add_argument("--sheet")
    collect.add_argument("--providers", default="google,shopee")
    collect.add_argument("--limit", type=int)
    collect.add_argument("--max-products", type=int, default=1000)
    collect.add_argument("--delay", type=float)
    return parser


def _build_providers(
    selected: list[str], settings: Settings, http: UrllibJsonHttpClient
) -> list[PriceProvider]:
    providers: list[PriceProvider] = []
    unknown = sorted(set(selected) - {"google", "shopee"})
    if unknown:
        raise ConfigurationError(f"Provider desconhecido: {', '.join(unknown)}")
    if "google" in selected:
        if not settings.serpapi_key:
            raise ConfigurationError("SERPAPI_KEY e obrigatoria para o provider google")
        providers.append(
            GoogleShoppingProvider(
                settings.serpapi_key, http, location=settings.google_location
            )
        )
    if "shopee" in selected:
        if not settings.shopee_app_id or not settings.shopee_app_secret:
            raise ConfigurationError(
                "SHOPEE_APP_ID e SHOPEE_APP_SECRET sao obrigatorias para shopee"
            )
        providers.append(
            ShopeeAffiliateProvider(
                settings.shopee_app_id, settings.shopee_app_secret, http
            )
        )
    if not providers:
        raise ConfigurationError("Selecione ao menos um provider")
    return providers


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "template":
            destination = create_template(args.output)
            print(f"Planilha-modelo criada: {destination}")
            return 0

        settings = Settings.from_env()
        selected = [
            item.strip().casefold() for item in args.providers.split(",") if item.strip()
        ]
        limit = args.limit if args.limit is not None else settings.result_limit
        delay = (
            args.delay
            if args.delay is not None
            else settings.request_delay_seconds
        )
        if not 1 <= limit <= 20:
            raise ConfigurationError("--limit deve estar entre 1 e 20")
        if delay < 0:
            raise ConfigurationError("--delay nao pode ser negativo")

        products = read_products(args.input, args.sheet, args.max_products)
        http = UrllibJsonHttpClient(settings.timeout_seconds, settings.max_retries)
        providers = _build_providers(selected, settings, http)
        service = CollectionService(providers, limit, delay)
        rows = service.collect(products)
        destination = export_results(rows, args.output)
        offers = sum(1 for row in rows if row.status == "OK")
        errors = sum(1 for row in rows if row.status == "ERRO")
        print(
            f"Concluido: {len(products)} produtos, {offers} ofertas, "
            f"{errors} erros. Arquivo: {destination}"
        )
        return 0 if not errors else 1
    except PriceCollectorError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Erro de arquivo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
