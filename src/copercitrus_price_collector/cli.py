from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from .browser import BrowserRpa
from .errors import ConfigurationError, PriceCollectorError
from .providers import GoogleShoppingProvider, PriceProvider, ShopeeProvider
from .service import CollectionService
from .settings import Settings
from .spreadsheet import create_template, export_results, read_products


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copercitrus-price",
        description="RPA de precos do Google Shopping e Shopee a partir de um Excel.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    template = subcommands.add_parser("template", help="cria uma planilha-modelo")
    template.add_argument("output", nargs="?", default="produtos.xlsx")

    collect = subcommands.add_parser("collect", help="processa uma planilha via browser")
    collect.add_argument("input")
    collect.add_argument("--output", default="resultados/precos.xlsx")
    collect.add_argument("--sheet")
    collect.add_argument("--providers", default="google,shopee")
    collect.add_argument("--limit", type=int)
    collect.add_argument("--max-products", type=int, default=1000)
    collect.add_argument("--delay", type=float)
    collect.add_argument(
        "--headed",
        action="store_true",
        help="exibe o Chromium durante a execucao",
    )
    collect.add_argument(
        "--browser-channel",
        choices=("chrome", "msedge"),
        help="usa o Chrome ou Edge instalado em vez do Chromium do Playwright",
    )
    collect.add_argument(
        "--browser-user-data-dir",
        help="usa um perfil persistente do navegador e preserva a sessao local",
    )
    collect.add_argument(
        "--browser-cdp-url",
        help="conecta a um Chrome ja aberto com depuracao remota, por exemplo http://127.0.0.1:9222",
    )
    return parser


def _build_providers(selected: list[str], browser: BrowserRpa) -> list[PriceProvider]:
    providers: list[PriceProvider] = []
    unknown = sorted(set(selected) - {"google", "shopee"})
    if unknown:
        raise ConfigurationError(f"Fonte desconhecida: {', '.join(unknown)}")
    if "google" in selected:
        providers.append(GoogleShoppingProvider(browser))
    if "shopee" in selected:
        providers.append(ShopeeProvider(browser))
    if not providers:
        raise ConfigurationError("Selecione ao menos uma fonte")
    return providers


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "template":
            destination = create_template(args.output)
            print(f"Planilha-modelo criada: {destination}")
            return 0

        settings = Settings.from_env()
        if args.headed:
            settings = replace(settings, headless=False)
        if args.browser_channel:
            settings = replace(settings, browser_channel=args.browser_channel)
        if args.browser_user_data_dir:
            settings = replace(
                settings, browser_user_data_dir=args.browser_user_data_dir
            )
        if args.browser_cdp_url:
            settings = replace(settings, browser_cdp_url=args.browser_cdp_url)

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
        with BrowserRpa(settings) as browser:
            providers = _build_providers(selected, browser)
            rows = CollectionService(providers, limit, delay).collect(products)

        destination = export_results(rows, args.output)
        offers = sum(1 for row in rows if row.status == "OK")
        similars = sum(
            1
            for row in rows
            if row.result is not None and row.result.possible_similar
        )
        errors = sum(1 for row in rows if row.status == "ERRO")
        print(
            f"Concluido: {len(products)} produtos, {offers} ofertas, "
            f"{similars} similares e {errors} erros. Arquivo: {destination}"
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
