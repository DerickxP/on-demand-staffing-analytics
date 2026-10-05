"""Normalização de texto e leitura tolerante de colunas."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

import pandas as pd


def is_na(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def clean_text(value: Any) -> str:
    """Texto para armazenamento: sem NA, sem espaços nas pontas, espaços internos únicos."""
    if is_na(value):
        return ""
    text = " ".join(str(value).split())
    return "" if text.lower() in {"nan", "none", "<na>", "nat"} else text


def normalize_key(value: Any) -> str:
    """Chave de comparação: sem acentos, minúscula, espaços únicos."""
    return " ".join(strip_accents(clean_text(value)).lower().split())


def compact_key(value: Any) -> str:
    """Chave ainda mais tolerante: só letras e dígitos, em caixa alta."""
    return re.sub(r"[^A-Z0-9]", "", strip_accents(clean_text(value)).upper())


def find_column(df: pd.DataFrame, candidates: Iterable[str]) -> str:
    candidates = list(candidates)
    lookup = {normalize_key(column): column for column in df.columns}
    for candidate in candidates:
        key = normalize_key(candidate)
        if key in lookup:
            return lookup[key]
    raise KeyError(
        f"Coluna não encontrada. Procuradas={candidates} | Disponíveis={list(df.columns)}"
    )


def optional_column(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    try:
        return find_column(df, candidates)
    except KeyError:
        return None


def pick_sheet(sheet_names: Iterable[str], candidates: Iterable[str]) -> str | None:
    lookup = {normalize_key(name): name for name in sheet_names}
    for candidate in candidates:
        found = lookup.get(normalize_key(candidate))
        if found is not None:
            return found
    return None


def to_float(value: Any) -> float | None:
    """Número a partir de float, int ou texto em formato brasileiro ("1.234,56")."""
    if is_na(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = clean_text(value).replace("R$", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("()-+")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return None if number is None else int(number)
