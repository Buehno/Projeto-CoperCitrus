"""API HTTP do RPA de precos.

E o processo que o Railway mantem no ar: expoe o healthcheck, dispara coletas e
serve o historico gravado no PostgreSQL.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .database import Database, DatabaseError, database_url
from .errors import PriceCollectorError
from .models import ProductInput
from .runner import KNOWN_PROVIDERS, execute_collection, parse_providers
from .settings import Settings
from .spreadsheet import export_results, read_products

logger = logging.getLogger("copercitrus.web")

MAX_PRODUTOS = 1000
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

_state: dict[str, Any] = {"database": None, "schema_ready": False}
_collection_lock = threading.Lock()
_artifacts_dir = Path(tempfile.gettempdir()) / "copercitrus-resultados"


# --------------------------------------------------------------------- schemas


class ProdutoIn(BaseModel):
    produto: str = Field(min_length=1, max_length=300)
    marca: str | None = Field(default=None, max_length=200)
    modelo: str | None = Field(default=None, max_length=200)
    sku: str | None = Field(default=None, max_length=100)
    quantidade: str | None = Field(default=None, max_length=100)


class BuscaIn(BaseModel):
    produtos: list[ProdutoIn] = Field(min_length=1, max_length=MAX_PRODUTOS)
    providers: list[Literal["google", "shopee"]] = Field(
        default_factory=lambda: list(KNOWN_PROVIDERS)
    )
    limit: int = Field(default=5, ge=1, le=20)
    delay: float | None = Field(default=None, ge=0, le=60)


class ColetaAceita(BaseModel):
    coleta_id: int
    status: str
    total_produtos: int
    detalhe: str


# ------------------------------------------------------------------ infra


def get_database() -> Database:
    db = _state.get("database")
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Banco indisponivel. Verifique a variavel DATABASE_URL do servico.",
        )
    ensure_schema(db)
    return db


def ensure_schema(db: Database) -> None:
    """Garante o schema na primeira operacao bem-sucedida.

    Se o PostgreSQL ainda nao estava de pe quando a API subiu, a criacao das
    tabelas acontece aqui, sem exigir um novo deploy.
    """

    if _state.get("schema_ready"):
        return
    try:
        db.create_schema()
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _state["schema_ready"] = True


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Protege os endpoints de escrita quando API_KEY esta definida.

    Sem API_KEY configurada a API fica aberta, o que so e aceitavel em rede
    privada; em producao no Railway defina a variavel.
    """

    expected = os.getenv("API_KEY", "").strip()
    if not expected:
        return
    if not x_api_key or not _constant_time_equals(x_api_key, expected):
        raise HTTPException(status_code=401, detail="X-API-Key ausente ou invalida")


def _constant_time_equals(left: str, right: str) -> bool:
    from hmac import compare_digest

    return compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = database_url()
    if not dsn:
        logger.error(
            "DATABASE_URL nao configurada: a API sobe, mas /buscas ficara indisponivel."
        )
    else:
        db = Database(dsn)
        # wait=False: o startup nunca bloqueia nem quebra por causa do banco.
        # O Railway consegue subir o container mesmo se o Postgres demorar, e o
        # schema e criado na primeira requisicao que conseguir conectar.
        db.open(wait=False)
        _state["database"] = db
        _state["schema_ready"] = False

        def preparar_schema() -> None:
            try:
                db.create_schema()
            except DatabaseError as exc:
                logger.warning(
                    "Schema sera criado na primeira requisicao bem-sucedida: %s", exc
                )
                return
            _state["schema_ready"] = True
            logger.info("PostgreSQL conectado e schema verificado.")

        # Fora da thread do startup: o container abre a porta imediatamente e o
        # healthcheck do Railway nao espera o handshake do banco.
        threading.Thread(
            target=preparar_schema, name="schema-init", daemon=True
        ).start()
    _artifacts_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield
    finally:
        db = _state.get("database")
        if db is not None:
            with suppress(Exception):
                db.close()
        _state["database"] = None
        _state["schema_ready"] = False


app = FastAPI(
    title="CoperCitrus — RPA de pesquisa de precos",
    version=__version__,
    lifespan=lifespan,
)


# ------------------------------------------------------------------ execucao


def _run_in_background(
    products: list[ProductInput],
    providers: list[str],
    limit: int,
    delay: float | None,
    extra: dict[str, Any],
) -> int:
    """Registra a coleta e dispara a execucao numa thread dedicada.

    O Playwright sincrono nao pode rodar na thread do event loop, e uma coleta
    leva minutos: por isso a API responde 202 e o cliente acompanha por
    GET /buscas/{id}.
    """

    db = get_database()
    settings = Settings.from_env()
    effective_delay = delay if delay is not None else settings.request_delay_seconds

    if not _collection_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Ja existe uma coleta em andamento. Aguarde a conclusao.",
        )

    try:
        coleta_id = db.start_run(
            origem=extra.get("origem", "api"),
            total_produtos=len(products),
            parametros={
                "providers": providers,
                "limit": limit,
                "delay": effective_delay,
                **extra,
            },
        )
    except DatabaseError as exc:
        _collection_lock.release()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def worker() -> None:
        try:
            outcome = execute_collection(
                products,
                settings,
                providers=providers,
                limit=limit,
                delay=effective_delay,
                database=None,  # a coleta ja foi aberta acima
                origem=extra.get("origem", "api"),
            )
            db.save_rows(coleta_id, outcome.rows)
            db.finish_run(coleta_id, status="CONCLUIDA", totals=outcome.totals)
            with suppress(Exception):
                export_results(
                    outcome.rows, _artifacts_dir / f"coleta-{coleta_id}.xlsx"
                )
            logger.info("Coleta %s concluida", coleta_id)
        except Exception as exc:
            logger.exception("Coleta %s falhou", coleta_id)
            with suppress(Exception):
                db.finish_run(coleta_id, status="FALHOU", erro=str(exc))
        finally:
            _collection_lock.release()

    threading.Thread(
        target=worker, name=f"coleta-{coleta_id}", daemon=True
    ).start()
    return coleta_id


# ------------------------------------------------------------------ endpoints


@app.get("/")
def raiz() -> dict[str, Any]:
    return {
        "servico": "copercitrus-price-collector",
        "versao": __version__,
        # Estado real da conexao fica em /health; aqui so dizemos se ha DSN.
        "banco": "configurado" if _state.get("database") else "nao configurado",
        "schema": "pronto" if _state.get("schema_ready") else "pendente",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> JSONResponse:
    db = _state.get("database")
    if db is None:
        return JSONResponse(
            status_code=503, content={"status": "degradado", "banco": "indisponivel"}
        )
    try:
        db.ping()
    except DatabaseError as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "degradado", "banco": "erro", "detalhe": str(exc)},
        )
    return JSONResponse(content={"status": "ok", "banco": "ok"})


@app.post(
    "/buscas",
    status_code=202,
    response_model=ColetaAceita,
    dependencies=[Depends(require_api_key)],
)
def criar_busca(payload: BuscaIn) -> ColetaAceita:
    try:
        providers = parse_providers(payload.providers)
    except PriceCollectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    products = [
        ProductInput(
            row_number=index,
            produto=item.produto.strip(),
            marca=(item.marca or None),
            modelo=(item.modelo or None),
            sku=(item.sku or None),
            quantidade_solicitada=(item.quantidade or None),
        )
        for index, item in enumerate(payload.produtos, start=1)
    ]

    coleta_id = _run_in_background(
        products,
        providers,
        payload.limit,
        payload.delay,
        {"origem": "api"},
    )
    return ColetaAceita(
        coleta_id=coleta_id,
        status="EM_ANDAMENTO",
        total_produtos=len(products),
        detalhe=f"Acompanhe em GET /buscas/{coleta_id}",
    )


@app.post(
    "/buscas/planilha",
    status_code=202,
    response_model=ColetaAceita,
    dependencies=[Depends(require_api_key)],
)
async def criar_busca_por_planilha(
    arquivo: Annotated[UploadFile, File(description="Planilha .xlsx de entrada")],
    providers: Annotated[str, Form()] = "google,shopee",
    limit: Annotated[int, Form(ge=1, le=20)] = 5,
) -> ColetaAceita:
    if not (arquivo.filename or "").casefold().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .xlsx")

    conteudo = await arquivo.read(MAX_UPLOAD_BYTES + 1)
    if len(conteudo) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Planilha acima de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / "entrada.xlsx"
        destino.write_bytes(conteudo)
        try:
            selected = parse_providers(providers)
            products = read_products(destino, None, MAX_PRODUTOS)
        except PriceCollectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    coleta_id = _run_in_background(
        products,
        selected,
        limit,
        None,
        {"origem": "api", "arquivo": arquivo.filename},
    )
    return ColetaAceita(
        coleta_id=coleta_id,
        status="EM_ANDAMENTO",
        total_produtos=len(products),
        detalhe=f"Acompanhe em GET /buscas/{coleta_id}",
    )


@app.get("/buscas")
def listar_buscas(
    limit: int = 50, offset: int = 0, db: Database = Depends(get_database)
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return {"coletas": db.list_runs(limit=limit, offset=offset)}


@app.get("/buscas/{coleta_id}")
def detalhar_busca(
    coleta_id: int, db: Database = Depends(get_database)
) -> dict[str, Any]:
    run = db.get_run(coleta_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Coleta nao encontrada")
    return run


@app.get("/buscas/{coleta_id}/resultados")
def resultados_da_busca(
    coleta_id: int,
    limit: int = 500,
    offset: int = 0,
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    if db.get_run(coleta_id) is None:
        raise HTTPException(status_code=404, detail="Coleta nao encontrada")
    limit = max(1, min(limit, 2000))
    offset = max(0, offset)
    return {
        "coleta_id": coleta_id,
        "resultados": db.list_results(coleta_id, limit=limit, offset=offset),
    }


@app.get("/buscas/{coleta_id}/planilha")
def planilha_da_busca(coleta_id: int) -> FileResponse:
    caminho = _artifacts_dir / f"coleta-{coleta_id}.xlsx"
    if not caminho.is_file():
        raise HTTPException(
            status_code=404,
            detail="Excel indisponivel. O arquivo e temporario e some a cada deploy; "
            "use GET /buscas/{id}/resultados para os dados persistidos.",
        )
    return FileResponse(
        caminho,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        filename=f"copercitrus-coleta-{coleta_id}.xlsx",
    )
