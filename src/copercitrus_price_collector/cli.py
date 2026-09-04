from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from .database import Database, DatabaseError, database_url
from .errors import ConfigurationError, PriceCollectorError
from .runner import execute_collection
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
    collect.add_argument(
        "--no-db",
        action="store_true",
        help="nao registra a coleta no PostgreSQL mesmo com DATABASE_URL definida",
    )

    database = subcommands.add_parser(
        "db", help="operacoes no PostgreSQL configurado em DATABASE_URL"
    )
    db_actions = database.add_subparsers(dest="db_command", required=True)
    db_actions.add_parser("init", help="cria as tabelas da coleta se nao existirem")
    db_actions.add_parser("check", help="testa a conexao com o banco")
    history = db_actions.add_parser("runs", help="lista as ultimas coletas registradas")
    history.add_argument("--limit", type=int, default=20)

    return parser


def _open_database() -> Database:
    dsn = database_url()
    if not dsn:
        raise ConfigurationError(
            "DATABASE_URL nao configurada. No Railway, vincule um PostgreSQL ao servico."
        )
    db = Database(dsn)
    db.open()
    return db


def _run_db_command(args: argparse.Namespace) -> int:
    db = _open_database()
    try:
        if args.db_command == "init":
            db.create_schema()
            print("Schema criado/atualizado com sucesso.")
            return 0
        if args.db_command == "check":
            db.ping()
            print("Conexao com o PostgreSQL confirmada.")
            return 0
        if args.db_command == "runs":
            runs = db.list_runs(limit=max(1, args.limit))
            if not runs:
                print("Nenhuma coleta registrada.")
                return 0
            for run in runs:
                print(
                    f"#{run['id']:<6} {run['iniciada_em']:%Y-%m-%d %H:%M}  "
                    f"{run['origem']:<6} {run['status']:<13} "
                    f"produtos={run['total_produtos']:<4} "
                    f"ofertas={run['total_ofertas']:<5} "
                    f"erros={run['total_erros']}"
                )
            return 0
        raise ConfigurationError(f"Subcomando desconhecido: {args.db_command}")
    finally:
        db.close()


def _run_collect(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if args.headed:
        settings = replace(settings, headless=False)
    if args.browser_channel:
        settings = replace(settings, browser_channel=args.browser_channel)
    if args.browser_user_data_dir:
        settings = replace(settings, browser_user_data_dir=args.browser_user_data_dir)
    if args.browser_cdp_url:
        settings = replace(settings, browser_cdp_url=args.browser_cdp_url)

    limit = args.limit if args.limit is not None else settings.result_limit
    delay = args.delay if args.delay is not None else settings.request_delay_seconds
    if not 1 <= limit <= 20:
        raise ConfigurationError("--limit deve estar entre 1 e 20")
    if delay < 0:
        raise ConfigurationError("--delay nao pode ser negativo")

    products = read_products(args.input, args.sheet, args.max_products)

    database: Database | None = None
    dsn = None if args.no_db else database_url()
    if dsn:
        try:
            database = Database(dsn)
            database.open()
            database.create_schema()
        except DatabaseError as exc:
            # O banco e um registro paralelo: sua indisponibilidade nao pode
            # impedir a geracao do Excel, que e a entrega principal do RPA.
            print(f"Aviso: coleta nao sera registrada no banco ({exc})", file=sys.stderr)
            if database is not None:
                database.close()
            database = None

    try:
        outcome = execute_collection(
            products,
            settings,
            providers=args.providers,
            limit=limit,
            delay=delay,
            database=database,
            origem="cli",
            extra_parametros={"entrada": str(args.input)},
        )
    finally:
        if database is not None:
            database.close()

    destination = export_results(outcome.rows, args.output)
    totals = outcome.totals
    registro = (
        f" Coleta #{outcome.coleta_id} registrada no banco."
        if outcome.coleta_id is not None
        else ""
    )
    print(
        f"Concluido: {totals.total_produtos} produtos, {totals.total_ofertas} ofertas, "
        f"{totals.total_similares} similares e {totals.total_erros} erros. "
        f"Arquivo: {destination}.{registro}"
    )
    return 0 if not totals.total_erros else 1


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except KeyboardInterrupt:
        return 130
    try:
        if args.command == "template":
            destination = create_template(args.output)
            print(f"Planilha-modelo criada: {destination}")
            return 0
        if args.command == "db":
            return _run_db_command(args)
        return _run_collect(args)
    except KeyboardInterrupt:
        print("Coleta interrompida pelo usuario.", file=sys.stderr)
        return 130
    except PriceCollectorError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Erro de arquivo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
