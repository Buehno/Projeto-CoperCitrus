"""Persistencia das coletas em PostgreSQL.

O schema e criado de forma idempotente na subida da aplicacao, entao um deploy
novo no Railway com um banco vazio ja fica operacional sem passo manual.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from .errors import PriceCollectorError
from .models import CollectionRow, ProductInput


class DatabaseError(PriceCollectorError):
    """Falha de conexao ou de escrita no PostgreSQL."""


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS coletas (
        id                BIGSERIAL PRIMARY KEY,
        origem            TEXT        NOT NULL DEFAULT 'cli',
        status            TEXT        NOT NULL DEFAULT 'EM_ANDAMENTO',
        iniciada_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
        finalizada_em     TIMESTAMPTZ,
        total_produtos    INTEGER     NOT NULL DEFAULT 0,
        total_ofertas     INTEGER     NOT NULL DEFAULT 0,
        total_similares   INTEGER     NOT NULL DEFAULT 0,
        total_erros       INTEGER     NOT NULL DEFAULT 0,
        erro              TEXT,
        parametros        JSONB       NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS buscas (
        id                    BIGSERIAL PRIMARY KEY,
        coleta_id             BIGINT      NOT NULL
                              REFERENCES coletas(id) ON DELETE CASCADE,
        linha_planilha        INTEGER,
        produto               TEXT        NOT NULL,
        marca                 TEXT,
        modelo                TEXT,
        sku                   TEXT,
        quantidade_solicitada TEXT,
        termo_pesquisa        TEXT        NOT NULL,
        fonte                 TEXT        NOT NULL,
        status                TEXT        NOT NULL,
        erro                  TEXT,
        coletado_em           TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resultados (
        id                     BIGSERIAL PRIMARY KEY,
        busca_id               BIGINT NOT NULL
                               REFERENCES buscas(id) ON DELETE CASCADE,
        posicao                INTEGER,
        titulo                 TEXT   NOT NULL,
        descricao              TEXT,
        marca                  TEXT,
        quantidade_embalagem   TEXT,
        preco_min              NUMERIC(14, 2),
        preco_max              NUMERIC(14, 2),
        moeda                  TEXT,
        url_compra             TEXT,
        vendedor               TEXT,
        avaliacao              NUMERIC(4, 2),
        total_avaliacoes       INTEGER,
        total_vendidos         INTEGER,
        imagem_url             TEXT,
        similaridade           NUMERIC(6, 2),
        classificacao          TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_coletas_iniciada_em ON coletas (iniciada_em DESC)",
    "CREATE INDEX IF NOT EXISTS idx_buscas_coleta_id ON buscas (coleta_id)",
    "CREATE INDEX IF NOT EXISTS idx_buscas_produto ON buscas (produto)",
    "CREATE INDEX IF NOT EXISTS idx_resultados_busca_id ON resultados (busca_id)",
)


def database_url() -> str | None:
    """DSN do PostgreSQL vindo do ambiente.

    Railway injeta `DATABASE_URL` ao vincular um Postgres ao servico.
    `POSTGRES_URL` e aceito como alternativa.
    """

    for name in ("DATABASE_URL", "POSTGRES_URL"):
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


@dataclass(frozen=True, slots=True)
class RunTotals:
    total_produtos: int = 0
    total_ofertas: int = 0
    total_similares: int = 0
    total_erros: int = 0


class Database:
    """Pool de conexoes e operacoes de gravacao/leitura das coletas."""

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 4,
        connect_timeout: float = 10.0,
    ) -> None:
        if not dsn or not dsn.strip():
            raise DatabaseError("DATABASE_URL nao configurada")
        self.dsn = dsn.strip()
        self._pool = ConnectionPool(
            self.dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=connect_timeout,
            kwargs={"connect_timeout": int(connect_timeout)},
            open=False,
        )

    # ---------------------------------------------------------------- ciclo

    def open(self, timeout: float = 15.0, *, wait: bool = True) -> None:
        """Abre o pool.

        `wait=False` nao bloqueia nem falha se o banco ainda nao respondeu: o
        pool segue tentando em background e as conexoes passam a funcionar
        assim que o PostgreSQL subir. E o modo usado pela API, para que uma
        indisponibilidade momentanea no deploy nao derrube o servico.
        """

        try:
            self._pool.open(wait=wait, timeout=timeout)
        except Exception as exc:  # pragma: no cover - depende do ambiente
            raise DatabaseError(
                f"Nao foi possivel conectar ao PostgreSQL: {exc}"
            ) from exc

    def close(self) -> None:
        self._pool.close()

    def __enter__(self) -> Database:
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextmanager
    def connection(self):
        try:
            with self._pool.connection() as conn:
                yield conn
        except DatabaseError:
            raise
        except psycopg.Error as exc:
            raise DatabaseError(f"Erro no PostgreSQL: {exc}") from exc
        except Exception as exc:
            raise DatabaseError(f"Erro ao acessar o PostgreSQL: {exc}") from exc

    # --------------------------------------------------------------- schema

    def create_schema(self) -> None:
        """Cria tabelas e indices. Seguro para rodar em toda subida."""

        with self.connection() as conn:
            with conn.cursor() as cur:
                for statement in SCHEMA_STATEMENTS:
                    cur.execute(statement)
            conn.commit()

    def ping(self) -> bool:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None

    # --------------------------------------------------------------- escrita

    def start_run(
        self,
        *,
        origem: str = "cli",
        total_produtos: int = 0,
        parametros: dict[str, Any] | None = None,
    ) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO coletas (origem, status, total_produtos, parametros)
                    VALUES (%s, 'EM_ANDAMENTO', %s, %s)
                    RETURNING id
                    """,
                    (origem, total_produtos, Json(parametros or {})),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:  # pragma: no cover - INSERT ... RETURNING sempre devolve
            raise DatabaseError("Nao foi possivel registrar a coleta")
        return int(row[0])

    def save_rows(self, coleta_id: int, rows: Sequence[CollectionRow]) -> int:
        """Grava as buscas e seus resultados. Devolve quantas buscas foram criadas.

        Linhas do mesmo produto/fonte sao agrupadas em uma unica busca, porque
        `CollectionService` emite uma `CollectionRow` por oferta encontrada.
        """

        if not rows:
            return 0

        grouped: dict[tuple[int | None, str, str], list[CollectionRow]] = {}
        for row in rows:
            key = (row.product.row_number, row.product.query, row.provider)
            grouped.setdefault(key, []).append(row)

        created = 0
        with self.connection() as conn:
            with conn.cursor() as cur:
                for group in grouped.values():
                    busca_id = self._insert_busca(cur, coleta_id, group)
                    created += 1
                    offers = [row.result for row in group if row.result is not None]
                    if offers:
                        self._insert_resultados(cur, busca_id, offers)
            conn.commit()
        return created

    @staticmethod
    def _insert_busca(cur, coleta_id: int, group: Sequence[CollectionRow]) -> int:
        first = group[0]
        product: ProductInput = first.product
        status = _group_status(group)
        erro = next((row.error for row in group if row.error), None)
        cur.execute(
            """
            INSERT INTO buscas (
                coleta_id, linha_planilha, produto, marca, modelo, sku,
                quantidade_solicitada, termo_pesquisa, fonte, status, erro,
                coletado_em
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                coleta_id,
                product.row_number,
                product.produto,
                product.marca,
                product.modelo,
                product.sku,
                product.quantidade_solicitada,
                product.query,
                first.provider,
                status,
                erro,
                first.collected_at,
            ),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover
            raise DatabaseError("Nao foi possivel registrar a busca")
        return int(row[0])

    @staticmethod
    def _insert_resultados(cur, busca_id: int, offers: Iterable[Any]) -> None:
        payload = [
            (
                busca_id,
                offer.rank,
                offer.title,
                offer.description,
                offer.brand,
                offer.package_quantity,
                offer.price_min,
                offer.price_max,
                offer.currency,
                offer.purchase_url,
                offer.seller,
                offer.rating,
                offer.review_count,
                offer.sold_count,
                offer.image_url,
                offer.similarity_score,
                offer.match_type,
            )
            for offer in offers
        ]
        cur.executemany(
            """
            INSERT INTO resultados (
                busca_id, posicao, titulo, descricao, marca, quantidade_embalagem,
                preco_min, preco_max, moeda, url_compra, vendedor, avaliacao,
                total_avaliacoes, total_vendidos, imagem_url, similaridade,
                classificacao
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            payload,
        )

    def finish_run(
        self,
        coleta_id: int,
        *,
        status: str,
        totals: RunTotals | None = None,
        erro: str | None = None,
    ) -> None:
        totals = totals or RunTotals()
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE coletas
                       SET status = %s,
                           finalizada_em = %s,
                           total_produtos = %s,
                           total_ofertas = %s,
                           total_similares = %s,
                           total_erros = %s,
                           erro = %s
                     WHERE id = %s
                    """,
                    (
                        status,
                        datetime.now(timezone.utc),
                        totals.total_produtos,
                        totals.total_ofertas,
                        totals.total_similares,
                        totals.total_erros,
                        erro,
                        coleta_id,
                    ),
                )
            conn.commit()

    # --------------------------------------------------------------- leitura

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM coletas
                     ORDER BY iniciada_em DESC, id DESC
                     LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
                return list(cur.fetchall())

    def get_run(self, coleta_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM coletas WHERE id = %s", (coleta_id,))
                return cur.fetchone()

    def list_results(
        self,
        coleta_id: int,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT b.id            AS busca_id,
                           b.produto,
                           b.marca         AS marca_solicitada,
                           b.quantidade_solicitada,
                           b.termo_pesquisa,
                           b.fonte,
                           b.status,
                           b.erro,
                           b.coletado_em,
                           r.id            AS resultado_id,
                           r.posicao,
                           r.titulo,
                           r.descricao,
                           r.marca         AS marca_encontrada,
                           r.quantidade_embalagem,
                           r.preco_min,
                           r.preco_max,
                           r.moeda,
                           r.url_compra,
                           r.vendedor,
                           r.similaridade,
                           r.classificacao
                      FROM buscas b
                      LEFT JOIN resultados r ON r.busca_id = b.id
                     WHERE b.coleta_id = %s
                     ORDER BY b.linha_planilha NULLS LAST, b.id, r.posicao NULLS LAST
                     LIMIT %s OFFSET %s
                    """,
                    (coleta_id, limit, offset),
                )
                return list(cur.fetchall())


    # ------------------------------------------------------------- dashboard

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())

    def resumo(self) -> dict[str, Any]:
        rows = self._rows(
            """
            SELECT (SELECT count(*) FROM coletas)                        AS coletas,
                   (SELECT count(*) FROM buscas)                         AS buscas,
                   (SELECT count(*) FROM resultados)                     AS ofertas,
                   (SELECT count(DISTINCT produto) FROM buscas)          AS produtos,
                   (SELECT count(*) FROM buscas WHERE status = 'ERRO')   AS erros,
                   (SELECT max(iniciada_em) FROM coletas)                AS ultima_coleta,
                   (SELECT avg(preco_min) FROM resultados
                     WHERE preco_min IS NOT NULL)                        AS preco_medio
            """
        )
        return rows[0] if rows else {}

    def ofertas_por_fonte(self) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT b.fonte,
                   count(r.id)     AS ofertas,
                   avg(r.preco_min) AS preco_medio,
                   min(r.preco_min) AS menor_preco
              FROM buscas b
              LEFT JOIN resultados r ON r.busca_id = b.id
             GROUP BY b.fonte
             ORDER BY ofertas DESC
            """
        )

    def distribuicao_classificacao(self) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT coalesce(classificacao, 'SEM_CLASSIFICACAO') AS classificacao,
                   count(*) AS total
              FROM resultados
             GROUP BY 1
             ORDER BY total DESC
            """
        )

    def melhor_preco_por_produto(self, limit: int = 100) -> list[dict[str, Any]]:
        """Oferta mais barata de cada produto, com o link do proprio anuncio."""

        return self._rows(
            """
            SELECT DISTINCT ON (b.produto)
                   b.produto,
                   b.fonte,
                   r.titulo,
                   r.marca,
                   r.quantidade_embalagem,
                   r.preco_min,
                   r.moeda,
                   r.url_compra,
                   r.vendedor,
                   r.similaridade,
                   r.classificacao
              FROM buscas b
              JOIN resultados r ON r.busca_id = b.id
             WHERE r.preco_min IS NOT NULL
             ORDER BY b.produto, r.preco_min ASC
             LIMIT %s
            """,
            (limit,),
        )

    def maiores_dispersoes(self, limit: int = 10) -> list[dict[str, Any]]:
        """Produtos com maior diferenca entre a oferta mais cara e a mais barata."""

        return self._rows(
            """
            SELECT b.produto,
                   count(r.id)                            AS ofertas,
                   min(r.preco_min)                       AS menor,
                   max(r.preco_min)                       AS maior,
                   max(r.preco_min) - min(r.preco_min)    AS diferenca
              FROM buscas b
              JOIN resultados r ON r.busca_id = b.id
             WHERE r.preco_min IS NOT NULL
             GROUP BY b.produto
            HAVING count(r.id) > 1 AND max(r.preco_min) > min(r.preco_min)
             ORDER BY diferenca DESC
             LIMIT %s
            """,
            (limit,),
        )

    def buscas_sem_oferta(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT produto, fonte, status, erro, coletado_em
              FROM buscas
             WHERE status <> 'OK'
             ORDER BY coletado_em DESC
             LIMIT %s
            """,
            (limit,),
        )


def _group_status(group: Sequence[CollectionRow]) -> str:
    statuses = {row.status for row in group}
    if "OK" in statuses:
        return "OK"
    if "ERRO" in statuses:
        return "ERRO"
    return "SEM_RESULTADO"


def totals_from_rows(
    rows: Sequence[CollectionRow], total_produtos: int
) -> RunTotals:
    return RunTotals(
        total_produtos=total_produtos,
        total_ofertas=sum(1 for row in rows if row.status == "OK"),
        total_similares=sum(
            1 for row in rows if row.result is not None and row.result.possible_similar
        ),
        total_erros=sum(1 for row in rows if row.status == "ERRO"),
    )
