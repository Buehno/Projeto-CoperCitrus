"""Dashboard de precos.

Aplicacao somente leitura: consome o PostgreSQL alimentado pelo CLI do RPA e
apresenta os insights. Nao existe entrada de dados pela web — a coleta e feita
por `copercitrus-price collect`, que grava nas mesmas tabelas.
"""

from __future__ import annotations

import html
import logging
import threading
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .database import Database, DatabaseError, database_url

logger = logging.getLogger("copercitrus.web")

_state: dict[str, Any] = {"database": None, "schema_ready": False}


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
    """Cria o schema na primeira operacao que conseguir conectar."""

    if _state.get("schema_ready"):
        return
    try:
        db.create_schema()
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _state["schema_ready"] = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = database_url()
    if not dsn:
        logger.error("DATABASE_URL nao configurada: o dashboard ficara indisponivel.")
    else:
        db = Database(dsn)
        db.open(wait=False)
        _state["database"] = db
        _state["schema_ready"] = False

        def preparar_schema() -> None:
            try:
                db.create_schema()
            except DatabaseError as exc:
                logger.warning("Schema pendente ate a primeira conexao: %s", exc)
                return
            _state["schema_ready"] = True
            logger.info("PostgreSQL conectado e schema verificado.")

        threading.Thread(
            target=preparar_schema, name="schema-init", daemon=True
        ).start()
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
    title="CoperCitrus — Dashboard de precos",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


# ------------------------------------------------------------- formatacao


def esc(value: Any) -> str:
    """Escapa para HTML. Titulos e vendedores vem de paginas de terceiros."""

    if value is None:
        return "—"
    return html.escape(str(value), quote=True)


def safe_url(value: Any) -> str | None:
    """Aceita apenas http/https: o link tambem vem de conteudo raspado."""

    if not value:
        return None
    try:
        parsed = urlparse(str(value))
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return str(value)


def moeda(value: Any, simbolo: str = "R$") -> str:
    if value is None:
        return "—"
    try:
        numero = Decimal(str(value))
    except Exception:
        return "—"
    inteiro, _, decimal = f"{numero:,.2f}".partition(".")
    return f"{simbolo} {inteiro.replace(',', '.')},{decimal}"


def data_hora(value: Any) -> str:
    if not isinstance(value, datetime):
        return "—"
    return value.strftime("%d/%m/%Y %H:%M")


def dominio(url: str | None) -> str:
    if not url:
        return "—"
    try:
        return urlparse(url).netloc or "—"
    except ValueError:
        return "—"


# ---------------------------------------------------------------- markup

ESTILO = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--muted:#5d6672;--line:#e3e7ec;
--accent:#1f6f43;--accent-soft:#e6f2ea;--warn:#b45309;--bar:#2f8f5b}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--ink:#e8ecf1;
--muted:#98a2b0;--line:#252b33;--accent:#5fbe8a;--accent-soft:#16281f;--warn:#e0a355;--bar:#4aa876}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 64px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;
margin-bottom:28px}
h1{font-size:22px;margin:0;letter-spacing:-.01em}
h2{font-size:15px;margin:0 0 14px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.sub{color:var(--muted);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:28px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.kpi .n{font-size:26px;font-weight:640;letter-spacing:-.02em}
.kpi .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:22px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:22px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
color:var(--muted);font-weight:600;padding:0 10px 8px;border-bottom:1px solid var(--line)}
td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.prod{font-weight:560}
.anuncio{color:var(--muted);font-size:12.5px;margin-top:2px;display:block}
.host{color:var(--muted);font-size:11.5px}
.bar{height:7px;background:var(--accent-soft);border-radius:4px;overflow:hidden;margin-top:5px}
.bar span{display:block;height:100%;background:var(--bar)}
.row{margin-bottom:13px}
.row .t{display:flex;justify-content:space-between;font-size:13.5px;gap:10px}
.tag{display:inline-block;font-size:11px;padding:2px 7px;border-radius:5px;
background:var(--accent-soft);color:var(--accent);font-weight:600}
.empty{text-align:center;padding:44px 20px;color:var(--muted)}
.empty code{background:var(--accent-soft);color:var(--accent);padding:2px 7px;border-radius:5px}
footer{margin-top:34px;color:var(--muted);font-size:12px;text-align:center}
"""


def _pagina(titulo: str, corpo: str) -> str:
    return (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(titulo)}</title><style>{ESTILO}</style></head>"
        f"<body><div class='wrap'>{corpo}</div></body></html>"
    )


def _barras(linhas: list[dict[str, Any]], rotulo: str, valor: str) -> str:
    if not linhas:
        return "<p class='sub'>Sem dados.</p>"
    maximo = max((int(l[valor] or 0) for l in linhas), default=0) or 1
    partes = []
    for linha in linhas:
        total = int(linha[valor] or 0)
        pct = round(total * 100 / maximo)
        partes.append(
            f"<div class='row'><div class='t'><span>{esc(linha[rotulo])}</span>"
            f"<strong>{total}</strong></div>"
            f"<div class='bar'><span style='width:{pct}%'></span></div></div>"
        )
    return "".join(partes)


def _tabela_precos(linhas: list[dict[str, Any]]) -> str:
    if not linhas:
        return "<p class='sub'>Nenhuma oferta com preco coletada ainda.</p>"
    corpo = []
    for linha in linhas:
        url = safe_url(linha.get("url_compra"))
        titulo = esc(linha.get("titulo"))
        # O link e o do proprio anuncio de onde o nome saiu.
        anuncio = (
            f"<a href='{esc(url)}' target='_blank' rel='noopener noreferrer nofollow'>"
            f"{titulo}</a><span class='host'> · {esc(dominio(url))}</span>"
            if url
            else f"{titulo}<span class='host'> · sem link</span>"
        )
        corpo.append(
            "<tr>"
            f"<td><span class='prod'>{esc(linha.get('produto'))}</span>"
            f"<span class='anuncio'>{anuncio}</span></td>"
            f"<td>{esc(linha.get('marca'))}</td>"
            f"<td>{esc(linha.get('quantidade_embalagem'))}</td>"
            f"<td>{esc(linha.get('fonte'))}</td>"
            f"<td class='num'>{moeda(linha.get('preco_min'), linha.get('moeda') or 'R$')}</td>"
            "</tr>"
        )
    return (
        "<div class='scroll'><table><thead><tr><th>Produto / anuncio</th>"
        "<th>Marca</th><th>Embalagem</th><th>Fonte</th>"
        "<th class='num'>Menor preco</th></tr></thead>"
        f"<tbody>{''.join(corpo)}</tbody></table></div>"
    )


def _tabela_dispersao(linhas: list[dict[str, Any]]) -> str:
    if not linhas:
        return "<p class='sub'>Sem produtos com mais de uma oferta.</p>"
    corpo = "".join(
        "<tr>"
        f"<td>{esc(l.get('produto'))}</td>"
        f"<td class='num'>{int(l.get('ofertas') or 0)}</td>"
        f"<td class='num'>{moeda(l.get('menor'))}</td>"
        f"<td class='num'>{moeda(l.get('maior'))}</td>"
        f"<td class='num'><strong>{moeda(l.get('diferenca'))}</strong></td>"
        "</tr>"
        for l in linhas
    )
    return (
        "<div class='scroll'><table><thead><tr><th>Produto</th>"
        "<th class='num'>Ofertas</th><th class='num'>Menor</th>"
        "<th class='num'>Maior</th><th class='num'>Economia</th></tr></thead>"
        f"<tbody>{corpo}</tbody></table></div>"
    )


# -------------------------------------------------------------- endpoints


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    db = _state.get("database")
    if db is None:
        return HTMLResponse(
            _pagina(
                "Dashboard indisponivel",
                "<div class='panel empty'><h1>Banco nao configurado</h1>"
                "<p>Defina <code>DATABASE_URL</code> nas variaveis do servico "
                "apontando para o PostgreSQL do projeto.</p></div>",
            ),
            status_code=503,
        )
    try:
        ensure_schema(db)
        resumo = db.resumo()
        fontes = db.ofertas_por_fonte()
        classes = db.distribuicao_classificacao()
        precos = db.melhor_preco_por_produto(limit=200)
        dispersao = db.maiores_dispersoes(limit=10)
        falhas = db.buscas_sem_oferta(limit=10)
    except (DatabaseError, HTTPException) as exc:
        detalhe = getattr(exc, "detail", str(exc))
        return HTMLResponse(
            _pagina(
                "Dashboard indisponivel",
                "<div class='panel empty'><h1>Sem conexao com o banco</h1>"
                f"<p>{esc(detalhe)}</p></div>",
            ),
            status_code=503,
        )

    if not int(resumo.get("ofertas") or 0):
        corpo = (
            "<header><div><h1>CoperCitrus — Dashboard de precos</h1>"
            "<div class='sub'>Somente leitura · dados do PostgreSQL</div></div></header>"
            "<div class='panel empty'><h2>Banco vazio</h2>"
            "<p>Nenhuma coleta registrada ainda. Rode o RPA para alimentar o banco:</p>"
            "<p><code>copercitrus-price collect produtos.xlsx</code></p>"
            "<p class='sub'>Com <code>DATABASE_URL</code> apontando para este "
            "mesmo PostgreSQL.</p></div>"
        )
        return HTMLResponse(_pagina("CoperCitrus — Dashboard", corpo))

    kpis = [
        (f"{int(resumo.get('produtos') or 0)}", "Produtos"),
        (f"{int(resumo.get('ofertas') or 0)}", "Ofertas"),
        (f"{int(resumo.get('buscas') or 0)}", "Buscas"),
        (f"{int(resumo.get('coletas') or 0)}", "Coletas"),
        (moeda(resumo.get("preco_medio")), "Preco medio"),
        (f"{int(resumo.get('erros') or 0)}", "Buscas com erro"),
    ]
    cards = "".join(
        f"<div class='kpi'><div class='n'>{esc(n)}</div><div class='l'>{esc(l)}</div></div>"
        for n, l in kpis
    )

    falhas_html = (
        "".join(
            f"<tr><td>{esc(f.get('produto'))}</td><td>{esc(f.get('fonte'))}</td>"
            f"<td><span class='tag'>{esc(f.get('status'))}</span></td>"
            f"<td class='sub'>{esc(f.get('erro'))}</td></tr>"
            for f in falhas
        )
        or "<tr><td colspan='4' class='sub'>Nenhuma falha registrada.</td></tr>"
    )

    corpo = (
        "<header><div><h1>CoperCitrus — Dashboard de precos</h1>"
        "<div class='sub'>Somente leitura · dados do PostgreSQL · "
        f"ultima coleta em {esc(data_hora(resumo.get('ultima_coleta')))}</div></div></header>"
        f"<div class='kpis'>{cards}</div>"
        "<div class='grid2'>"
        f"<div class='panel'><h2>Ofertas por fonte</h2>{_barras(fontes, 'fonte', 'ofertas')}</div>"
        "<div class='panel'><h2>Aderencia ao produto pedido</h2>"
        f"{_barras(classes, 'classificacao', 'total')}</div>"
        "</div>"
        "<div class='panel'><h2>Maior economia potencial</h2>"
        f"{_tabela_dispersao(dispersao)}</div>"
        "<div class='panel'><h2>Menor preco por produto</h2>"
        f"{_tabela_precos(precos)}</div>"
        "<div class='panel'><h2>Buscas sem oferta</h2><div class='scroll'><table>"
        "<thead><tr><th>Produto</th><th>Fonte</th><th>Status</th><th>Detalhe</th></tr></thead>"
        f"<tbody>{falhas_html}</tbody></table></div></div>"
        f"<footer>copercitrus-price-collector {esc(__version__)} · "
        "coleta pelo CLI, visualizacao somente leitura</footer>"
    )
    return HTMLResponse(_pagina("CoperCitrus — Dashboard de precos", corpo))


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


@app.get("/api/resumo")
def api_resumo(db: Database = Depends(get_database)) -> dict[str, Any]:
    return {
        "resumo": db.resumo(),
        "por_fonte": db.ofertas_por_fonte(),
        "por_classificacao": db.distribuicao_classificacao(),
    }


@app.get("/api/precos")
def api_precos(
    limit: int = 200, db: Database = Depends(get_database)
) -> dict[str, Any]:
    return {"precos": db.melhor_preco_por_produto(limit=max(1, min(limit, 1000)))}


@app.get("/api/coletas")
def api_coletas(
    limit: int = 50, offset: int = 0, db: Database = Depends(get_database)
) -> dict[str, Any]:
    return {
        "coletas": db.list_runs(limit=max(1, min(limit, 200)), offset=max(0, offset))
    }


@app.get("/api/coletas/{coleta_id}/resultados")
def api_resultados(
    coleta_id: int,
    limit: int = 500,
    offset: int = 0,
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    if db.get_run(coleta_id) is None:
        raise HTTPException(status_code=404, detail="Coleta nao encontrada")
    return {
        "coleta_id": coleta_id,
        "resultados": db.list_results(
            coleta_id, limit=max(1, min(limit, 2000)), offset=max(0, offset)
        ),
    }
