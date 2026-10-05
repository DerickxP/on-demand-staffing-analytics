"""Conversão de datas vindas do Excel sem trocar dia por mês.

Uma mesma coluna costuma chegar misturada: parte como data real do Excel, parte como
texto ISO ("2026-01-10 08:00:00") e parte como texto digitado no formato brasileiro
("10/01/2026"). Aplicar ``dayfirst=True`` na coluna inteira corrompe justamente o texto
ISO: "2026-01-10" vira 10 de outubro e "2025-11-30" vira nulo, porque não existe mês 30.
Foi assim que agendamentos "do futuro" apareceram no banco sem nenhum aviso.

Aqui cada origem é tratada separadamente: data real passa direto, texto ISO é lido como
ISO e só o restante segue a regra brasileira. Um contador informa quantos valores vieram
em texto e quantos não puderam ser convertidos, para o problema nunca voltar em silêncio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class DateParseStats:
    total: int
    text_values: int
    parsed_as_iso: int
    lost: int

    def __add__(self, other: DateParseStats) -> DateParseStats:
        return DateParseStats(
            total=self.total + other.total,
            text_values=self.text_values + other.text_values,
            parsed_as_iso=self.parsed_as_iso + other.parsed_as_iso,
            lost=self.lost + other.lost,
        )


EMPTY_STATS = DateParseStats(0, 0, 0, 0)


def parse_mixed_dates(series: pd.Series) -> tuple[pd.Series, DateParseStats]:
    """Converte uma coluna com datas reais, texto ISO e texto brasileiro misturados."""
    series = series.copy()
    is_text = series.map(lambda value: isinstance(value, str))
    non_empty = series.map(lambda value: not pd.isna(value) and str(value).strip() != "")

    already_dates = pd.to_datetime(series.where(~is_text), errors="coerce")
    text = series.where(is_text).map(lambda v: v.strip() if isinstance(v, str) else v)
    as_iso = pd.to_datetime(text, format="ISO8601", errors="coerce")
    as_brazilian = pd.to_datetime(text.where(as_iso.isna()), dayfirst=True, errors="coerce")

    converted = already_dates.fillna(as_iso).fillna(as_brazilian)
    stats = DateParseStats(
        total=int(non_empty.sum()),
        text_values=int((is_text & non_empty).sum()),
        parsed_as_iso=int(as_iso.notna().sum()),
        lost=int(non_empty.sum() - converted.notna().sum()),
    )
    return converted, stats


def future_mask(series: pd.Series, max_months: int, today: date | None = None) -> pd.Series:
    """Marca datas além de ``hoje + max_months`` (sinal clássico de dia e mês invertidos)."""
    limit = pd.Timestamp(today or date.today()).normalize() + pd.DateOffset(months=max_months)
    return series.notna() & (series > limit)


def iso_week(timestamp: pd.Timestamp) -> str:
    """Semana ISO no formato ``AAAA-Www``, usada na análise de recorrência."""
    iso = timestamp.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
