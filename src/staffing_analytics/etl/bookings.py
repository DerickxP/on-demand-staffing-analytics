"""Leitura e normalização da planilha de agendamentos da plataforma."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from staffing_analytics.config import BookingsSettings
from staffing_analytics.etl.dates import EMPTY_STATS, DateParseStats, future_mask, parse_mixed_dates
from staffing_analytics.etl.stores import StoreCatalog
from staffing_analytics.etl.text import (
    clean_text,
    find_column,
    optional_column,
    pick_sheet,
    to_float,
    to_int,
)

log = logging.getLogger(__name__)

BOOKING_COLUMNS: dict[str, tuple[str, ...]] = {
    "worker_name": ("Nome", "Prestador", "Worker"),
    "state": ("Estado", "UF", "State"),
    "store": ("Loja", "Unidade", "Store"),
    "role": ("Vaga", "Função", "Funcao", "Role"),
    "start_at": ("Início", "Inicio", "Start"),
    "end_at": ("Término", "Termino", "Fim", "End"),
    "booking_ref": ("Ref Agendamento", "Referência", "Referencia", "Ref", "Booking ref"),
    "scheduled_at": ("Agendado em", "Scheduled at"),
    "started_at": ("Iniciado em", "Started at"),
    "completed_at": ("Concluido em", "Concluído em", "Completed at"),
    "cost": ("Valor", "Valor Plataforma", "Custo", "Cost"),
    "computed_hours": ("Fração de hora computada", "Horas computadas", "Horas", "Hours"),
    "status": ("Status",),
    "cancelled_at": ("Data do cancelamento", "Cancelled at"),
    "cancel_reason": ("Motivo", "Reason"),
    "cancelled_by": (
        "Responsável pelo cancelamento",
        "Responsavel pelo cancelamento",
        "Cancelled by",
    ),
    "source_file": ("Arquivo de origem", "Source file"),
}
REQUIRED = ("worker_name", "store", "start_at")
DATE_COLUMNS = ("start_at", "end_at", "scheduled_at", "started_at", "completed_at", "cancelled_at")
BOOKING_OUTPUT = [
    "booking_key",
    "booking_ref",
    "worker_name",
    "state",
    "store",
    "role",
    "start_at",
    "end_at",
    "scheduled_at",
    "started_at",
    "completed_at",
    "cost",
    "computed_hours",
    "status",
    "cancelled_at",
    "cancel_reason",
    "cancelled_by",
    "source_file",
]
CANCELLED_STATUSES = frozenset({"CANCELADO", "CANCELLED", "CANCELED"})
MAPPING_RAW = ("Loja Sistema", "Loja no Sistema", "Nome no sistema", "Raw")
MAPPING_CANONICAL = ("Loja", "Loja no Banco", "Nome canônico", "Canonical")
HEADCOUNT_STORE = ("Loja", "Store")
HEADCOUNT_VALUE = ("Efetivos", "CLT", "Quadro", "Permanent", "Quantidade")


@dataclass(frozen=True)
class BookingsLoadStats:
    rows_in: int
    excluded_stores: int
    future_dropped: int
    duplicates: int
    rows_out: int
    date_stats: DateParseStats


@dataclass(frozen=True)
class BookingsWorkbook:
    frame: pd.DataFrame
    catalog: StoreCatalog
    headcount: dict[str, int]


def booking_key(ref: str, worker: str, start: str, store: str) -> str:
    """Chave de conteúdo: a referência da plataforma quando existe, senão pessoa+início+loja."""
    basis = f"ref:{ref}" if ref else f"row:{worker}|{start}|{store}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _timestamp_text(value) -> str | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def read_bookings_workbook(path, settings: BookingsSettings) -> BookingsWorkbook:
    workbook = pd.ExcelFile(path)
    sheet = pick_sheet(workbook.sheet_names, [settings.sheet])
    if sheet is None:
        raise ValueError(f"Aba '{settings.sheet}' não encontrada em {path}.")
    frame = pd.read_excel(path, sheet_name=sheet)
    frame.columns = [str(column).strip() for column in frame.columns]

    mapping_sheet = pick_sheet(workbook.sheet_names, [settings.store_mapping_sheet])
    if mapping_sheet is not None:
        catalog = StoreCatalog.from_mapping_frame(
            pd.read_excel(path, sheet_name=mapping_sheet),
            MAPPING_RAW,
            MAPPING_CANONICAL,
            exclude_patterns=settings.exclude_store_patterns,
        )
    else:
        log.info(
            "Aba de mapeamento '%s' ausente; lojas usadas como vieram.",
            settings.store_mapping_sheet,
        )
        catalog = StoreCatalog(exclude_patterns=settings.exclude_store_patterns)

    headcount: dict[str, int] = {}
    headcount_sheet = pick_sheet(workbook.sheet_names, [settings.headcount_sheet])
    if headcount_sheet is not None:
        quadro = pd.read_excel(path, sheet_name=headcount_sheet)
        store_column = find_column(quadro, HEADCOUNT_STORE)
        value_column = find_column(quadro, HEADCOUNT_VALUE)
        for store, value in zip(quadro[store_column], quadro[value_column], strict=True):
            canonical = catalog.resolve(clean_text(store))
            count = to_int(value)
            if canonical and count is not None:
                headcount[canonical] = max(count, 0)
    return BookingsWorkbook(frame=frame, catalog=catalog, headcount=headcount)


def normalize_bookings(
    frame: pd.DataFrame,
    catalog: StoreCatalog,
    settings: BookingsSettings,
    *,
    today: date | None = None,
) -> tuple[pd.DataFrame, BookingsLoadStats]:
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    columns = {
        name: optional_column(frame, candidates) for name, candidates in BOOKING_COLUMNS.items()
    }
    missing = [name for name in REQUIRED if columns[name] is None]
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes na planilha de agendamentos: {missing}")

    def text(name: str) -> pd.Series:
        column = columns[name]
        if column is None:
            return pd.Series([""] * len(frame), index=frame.index, dtype=object)
        return frame[column].map(clean_text)

    out = pd.DataFrame(index=frame.index)
    out["worker_name"] = text("worker_name")
    out["state"] = text("state").where(text("state") != "", settings.state)
    out["role"] = text("role")
    out["booking_ref"] = text("booking_ref")
    out["status"] = text("status").str.upper()
    out["cancel_reason"] = text("cancel_reason")
    out["cancelled_by"] = text("cancelled_by")
    out["source_file"] = text("source_file")
    out["cost"] = frame[columns["cost"]].map(to_float) if columns["cost"] else 0.0
    out["computed_hours"] = (
        frame[columns["computed_hours"]].map(to_float) if columns["computed_hours"] else 0.0
    )

    date_stats = EMPTY_STATS
    for name in DATE_COLUMNS:
        column = columns[name]
        if column is None:
            out[name] = pd.NaT
            continue
        converted, stats = parse_mixed_dates(frame[column])
        date_stats = date_stats + stats
        out[name] = converted

    rows_in = len(out)
    resolved = text("store").map(catalog.resolve)
    keep_store = resolved.notna()
    excluded_stores = int((~keep_store).sum())
    out["store"] = resolved

    future = future_mask(out["start_at"], settings.max_future_months, today=today)
    if future.any():
        months = out.loc[future, "start_at"].dt.strftime("%Y-%m").value_counts().sort_index()
        log.warning(
            "%d agendamento(s) com início além do limite futuro descartados (%s). "
            "Confira o formato da coluna de início no Excel.",
            int(future.sum()),
            ", ".join(f"{month}: {count}" for month, count in months.items()),
        )

    valid = keep_store & ~future & (out["worker_name"] != "") & out["start_at"].notna()
    out = out[valid].copy()
    out["cost"] = pd.to_numeric(out["cost"], errors="coerce").fillna(0.0)
    out["computed_hours"] = pd.to_numeric(out["computed_hours"], errors="coerce").fillna(0.0)
    for name in DATE_COLUMNS:
        out[name] = out[name].map(_timestamp_text)

    before = len(out)
    out = out.drop_duplicates(subset=["worker_name", "start_at", "store"], keep="first")
    duplicates = before - len(out)

    out["booking_key"] = [
        booking_key(row.booking_ref, row.worker_name, row.start_at, row.store)
        for row in out.itertuples(index=False)
    ]
    out = out.drop_duplicates(subset="booking_key", keep="first")
    stats = BookingsLoadStats(
        rows_in=rows_in,
        excluded_stores=excluded_stores,
        future_dropped=int(future.sum()),
        duplicates=duplicates,
        rows_out=len(out),
        date_stats=date_stats,
    )
    return out[BOOKING_OUTPUT].reset_index(drop=True), stats
