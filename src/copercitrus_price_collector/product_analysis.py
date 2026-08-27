"""Normalizacao e classificacao dos produtos encontrados pelo RPA."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import ProductInput


STOP_WORDS = {
    "a",
    "as",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "o",
    "os",
    "para",
    "por",
}


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.casefold())).strip()


def parse_price(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d[\d.\s]*(?:,\d{1,2})?|\d+(?:\.\d{1,2})", value)
    if not match:
        return None
    number = match.group(0).replace(" ", "")
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif number.count(".") > 1:
        number = number.replace(".", "")
    elif "." in number and len(number.rsplit(".", 1)[1]) == 3:
        number = number.replace(".", "")
    try:
        return float(number)
    except ValueError:
        return None


def extract_package_quantity(text: str | None) -> str | None:
    if not text:
        return None
    patterns = (
        r"\b(?:kit|pack|caixa|fardo)\s*(?:com|c/|de)?\s*(\d{1,4})\s*(?:unidades?|un\.?|pcs?)?\b",
        r"\b(\d{1,4})\s*(?:unidades?|un\.?|pcs?|pecas?)\b",
        r"\b(\d+(?:[.,]\d+)?)\s*(kg|g|mg|l|ml)\b",
        r"\b(\d{1,3})\s*[xX]\b",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if index == 2:
            return f"{match.group(1)} {match.group(2).lower()}"
        return f"{match.group(1)} un"
    return None


def identify_brand(title: str, requested_brand: str | None) -> str | None:
    normalized_title = normalize_text(title)
    if requested_brand and normalize_text(requested_brand) in normalized_title:
        return requested_brand.strip()
    explicit = re.search(
        r"\bmarca\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9._-]{1,30})",
        title,
        flags=re.IGNORECASE,
    )
    return explicit.group(1) if explicit else None


def similarity_score(product: ProductInput, found_title: str) -> float:
    requested = " ".join(
        value for value in (product.produto, product.marca, product.modelo) if value
    )
    requested_normalized = normalize_text(requested)
    found_normalized = normalize_text(found_title)
    if not requested_normalized or not found_normalized:
        return 0.0

    requested_tokens = {
        token for token in requested_normalized.split() if token not in STOP_WORDS
    }
    found_tokens = {token for token in found_normalized.split() if token not in STOP_WORDS}
    union = requested_tokens | found_tokens
    token_score = len(requested_tokens & found_tokens) / len(union) if union else 0.0
    sequence_score = SequenceMatcher(None, requested_normalized, found_normalized).ratio()
    score = (token_score * 60.0) + (sequence_score * 40.0)

    if product.modelo and normalize_text(product.modelo) in found_normalized:
        score += 10.0
    if product.marca and normalize_text(product.marca) in found_normalized:
        score += 5.0
    return round(min(score, 100.0), 1)


def classify_match(score: float) -> str:
    if score >= 80.0:
        return "COMPATIVEL"
    if score >= 50.0:
        return "SIMILAR"
    return "DIVERGENTE"
