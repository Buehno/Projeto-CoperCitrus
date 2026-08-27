"""Excel input and output helpers."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .errors import SpreadsheetError
from .models import CollectionRow, ProductInput


HEADER_ALIASES = {
    "produto": {"produto", "nome", "nomeproduto", "item", "descricaoproduto"},
    "marca": {"marca"},
    "modelo": {"modelo"},
    "sku": {"sku", "codigo", "codigoproduto", "codigodoproduto", "coditem"},
}

RESULT_HEADERS = [
    "Linha origem",
    "Produto solicitado",
    "Marca",
    "Modelo",
    "SKU",
    "Consulta",
    "Fonte",
    "Posicao",
    "Titulo",
    "Descricao",
    "Preco minimo",
    "Preco maximo",
    "Moeda",
    "Loja",
    "Avaliacao",
    "Quantidade avaliacoes",
    "Quantidade vendida",
    "Link de compra",
    "Imagem",
    "Coletado em UTC",
    "Status",
    "Erro",
]

HEADER_FILL = PatternFill("solid", fgColor="183B56")
HEADER_FONT = Font(color="FFFFFF", bold=True)
ERROR_FILL = PatternFill("solid", fgColor="FCE8E6")


def _normalize_header(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _cell_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def read_products(
    path: str | Path,
    sheet_name: str | None = None,
    max_products: int = 1000,
) -> list[ProductInput]:
    source = Path(path)
    if source.suffix.casefold() != ".xlsx":
        raise SpreadsheetError("A entrada deve ser um arquivo .xlsx")
    if not source.is_file():
        raise SpreadsheetError(f"Planilha nao encontrada: {source}")
    if max_products < 1:
        raise SpreadsheetError("max_products deve ser maior que zero")

    try:
        workbook = load_workbook(source, read_only=True, data_only=True)
    except Exception as exc:
        raise SpreadsheetError("Nao foi possivel abrir a planilha") from exc

    try:
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise SpreadsheetError(f"Aba nao encontrada: {sheet_name}")
            sheet = workbook[sheet_name]
        else:
            sheet = workbook.active

        header_values = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not header_values:
            raise SpreadsheetError("A planilha esta vazia")
        normalized = [_normalize_header(value) for value in header_values]
        indexes: dict[str, int] = {}
        for canonical, aliases in HEADER_ALIASES.items():
            for index, header in enumerate(normalized):
                if header in aliases:
                    indexes[canonical] = index
                    break
        if "produto" not in indexes:
            raise SpreadsheetError("Coluna obrigatoria 'Produto' nao encontrada")

        products: list[ProductInput] = []
        for row_number, values in enumerate(
            sheet.iter_rows(min_row=2, values_only=True), start=2
        ):
            produto = _value_at(values, indexes.get("produto"))
            marca = _value_at(values, indexes.get("marca"))
            modelo = _value_at(values, indexes.get("modelo"))
            sku = _value_at(values, indexes.get("sku"))
            if not any((produto, marca, modelo, sku)):
                continue
            if not produto:
                raise SpreadsheetError(f"Linha {row_number}: Produto esta vazio")
            products.append(ProductInput(row_number, produto, marca, modelo, sku))
            if len(products) > max_products:
                raise SpreadsheetError(
                    f"A planilha excede o limite de {max_products} produtos"
                )
        if not products:
            raise SpreadsheetError("Nenhum produto preenchido foi encontrado")
        return products
    finally:
        workbook.close()


def _value_at(values: tuple[object, ...], index: int | None) -> str | None:
    if index is None or index >= len(values):
        return None
    return _cell_text(values[index])


def create_template(path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Produtos"
    headers = ["Produto", "Marca", "Modelo", "SKU"]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    notes = {
        "A1": "Obrigatorio. Nome do produto que sera pesquisado.",
        "B1": "Opcional. Ajuda a refinar a busca.",
        "C1": "Opcional. Ajuda a refinar a busca.",
        "D1": "Opcional. Codigo interno ou do fabricante.",
    }
    for coordinate, text in notes.items():
        sheet[coordinate].comment = Comment(text, "IAgentics")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = "A1:D1"
    for index, width in enumerate([42, 22, 24, 22], start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    workbook.save(destination)
    workbook.close()
    return destination


def export_results(rows: list[CollectionRow], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    results_sheet = workbook.active
    results_sheet.title = "Resultados"
    results_sheet.append(RESULT_HEADERS)

    for row in rows:
        item = row.result
        results_sheet.append(
            [
                row.product.row_number,
                row.product.produto,
                row.product.marca,
                row.product.modelo,
                row.product.sku,
                row.product.query,
                row.provider,
                item.rank if item else None,
                item.title if item else None,
                item.description if item else None,
                item.price_min if item else None,
                item.price_max if item else None,
                item.currency if item else "BRL",
                item.seller if item else None,
                item.rating if item else None,
                item.review_count if item else None,
                item.sold_count if item else None,
                item.purchase_url if item else None,
                item.image_url if item else None,
                row.collected_at.replace(microsecond=0).isoformat(),
                row.status,
                row.error,
            ]
        )

    _format_results_sheet(results_sheet)
    _build_summary_sheet(workbook, rows)
    workbook.save(destination)
    workbook.close()
    return destination


def _format_results_sheet(sheet) -> None:
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.row_dimensions[1].height = 32
    widths = [
        12, 28, 18, 20, 18, 36, 18, 10, 42, 42, 16, 16, 10, 22, 12, 18, 18,
        48, 44, 24, 18, 44,
    ]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row_index in range(2, sheet.max_row + 1):
        sheet.cell(row_index, 11).number_format = 'R$ #,##0.00'
        sheet.cell(row_index, 12).number_format = 'R$ #,##0.00'
        sheet.cell(row_index, 15).number_format = "0.0"
        for column in (18, 19):
            cell = sheet.cell(row_index, column)
            if cell.value:
                cell.hyperlink = str(cell.value)
                cell.style = "Hyperlink"
        if sheet.cell(row_index, 21).value == "ERRO":
            for cell in sheet[row_index]:
                cell.fill = ERROR_FILL
    if sheet.max_row >= 2:
        table = Table(displayName="ResultadosColeta", ref=sheet.dimensions)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)


def _build_summary_sheet(workbook: Workbook, rows: list[CollectionRow]) -> None:
    sheet = workbook.create_sheet("Resumo")
    sheet.append(
        [
            "Produto",
            "SKU",
            "Ofertas encontradas",
            "Menor preco",
            "Fonte menor preco",
            "Loja",
            "Link de compra",
        ]
    )
    grouped: dict[tuple[str, str | None], list[CollectionRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.product.produto, row.product.sku)].append(row)

    for (product_name, sku), product_rows in grouped.items():
        successes = [
            row
            for row in product_rows
            if row.result is not None and row.result.price_min is not None
        ]
        cheapest = min(successes, key=lambda row: row.result.price_min) if successes else None
        result = cheapest.result if cheapest else None
        sheet.append(
            [
                product_name,
                sku,
                sum(1 for row in product_rows if row.status == "OK"),
                result.price_min if result else None,
                cheapest.provider if cheapest else None,
                result.seller if result else None,
                result.purchase_url if result else None,
            ]
        )

    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    for index, width in enumerate([34, 18, 22, 18, 22, 22, 50], start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row_index in range(2, sheet.max_row + 1):
        sheet.cell(row_index, 4).number_format = 'R$ #,##0.00'
        link_cell = sheet.cell(row_index, 7)
        if link_cell.value:
            link_cell.hyperlink = str(link_cell.value)
            link_cell.style = "Hyperlink"
    if sheet.max_row >= 2:
        table = Table(displayName="ResumoColeta", ref=sheet.dimensions)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)
