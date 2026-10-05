"""Carga incremental no SQLite.

As chaves de conteúdo tornam a carga idempotente: reprocessar a mesma planilha não
duplica nada. Antes de inserir, o catálogo de lojas é aplicado ao que já está no banco
(apelidos novos consolidam o histórico; lojas ignoradas são removidas), então corrigir
um mapeamento não exige recriar o banco.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from staffing_analytics.config import BookingsSettings, RevenueSettings
from staffing_analytics.etl.bookings import (
    BookingsLoadStats,
    normalize_bookings,
    read_bookings_workbook,
)
from staffing_analytics.etl.revenue import (
    RevenueLoadStats,
    normalize_revenue,
    read_revenue_workbook,
)
from staffing_analytics.etl.schema import database, init_db
from staffing_analytics.etl.stores import StoreCatalog

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BookingsLoadResult:
    stats: BookingsLoadStats
    inserted: int
    headcount_stores: int


@dataclass(frozen=True)
class RevenueLoadResult:
    stats: RevenueLoadStats
    inserted: int
    consolidated: int
    removed: int


def _none_if_nan(value):
    return None if value is None or pd.isna(value) else value


def apply_store_catalog(
    conn, catalog: StoreCatalog, tables=("revenue", "bookings")
) -> tuple[int, int]:
    """Reaponta apelidos e remove lojas ignoradas nas linhas já carregadas."""
    consolidated = removed = 0
    for table in tables:
        stores = [row[0] for row in conn.execute(f"SELECT DISTINCT store FROM {table}")]
        for store in stores:
            if store is None:
                continue
            target = catalog.resolve(store)
            if target is None:
                removed += conn.execute(f"DELETE FROM {table} WHERE store = ?", (store,)).rowcount
            elif target != store:
                consolidated += conn.execute(
                    f"UPDATE {table} SET store = ? WHERE store = ?", (target, store)
                ).rowcount
    conn.commit()
    return consolidated, removed


def insert_bookings(conn, bookings: pd.DataFrame) -> int:
    if bookings.empty:
        return 0
    before = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    rows = [
        (
            row.booking_key,
            row.booking_ref or None,
            row.worker_name,
            row.state or None,
            row.store,
            row.role or None,
            row.start_at,
            row.end_at,
            row.scheduled_at,
            row.started_at,
            row.completed_at,
            float(row.cost),
            float(row.computed_hours),
            row.status or None,
            row.cancelled_at,
            row.cancel_reason or None,
            row.cancelled_by or None,
            row.source_file or None,
        )
        for row in bookings.itertuples(index=False)
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO bookings (
            booking_key, booking_ref, worker_name, state, store, role, start_at, end_at,
            scheduled_at, started_at, completed_at, cost, computed_hours, status,
            cancelled_at, cancel_reason, cancelled_by, source_file
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] - before


def replace_headcount(conn, headcount: Mapping[str, int]) -> int:
    conn.execute("DELETE FROM headcount")
    conn.executemany(
        "INSERT INTO headcount (store, permanent) VALUES (?, ?)",
        [(store, int(value)) for store, value in headcount.items()],
    )
    conn.commit()
    return len(headcount)


def insert_revenue(conn, revenue: pd.DataFrame) -> int:
    if revenue.empty:
        return 0
    before = conn.execute("SELECT COUNT(*) FROM revenue").fetchone()[0]
    rows = [
        (
            row.revenue_key,
            row.store,
            row.sale_date,
            row.weekday or None,
            _none_if_nan(row.hour),
            _none_if_nan(row.operation_code),
            _none_if_nan(row.quantity),
            _none_if_nan(row.gross),
            _none_if_nan(row.discount),
            float(row.net),
        )
        for row in revenue.itertuples(index=False)
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO revenue (
            revenue_key, store, sale_date, weekday, hour, operation_code,
            quantity, gross, discount, net
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM revenue").fetchone()[0] - before


def load_bookings(workbook: Path, db_path: Path, settings: BookingsSettings) -> BookingsLoadResult:
    init_db(db_path)
    source = read_bookings_workbook(workbook, settings)
    bookings, stats = normalize_bookings(source.frame, source.catalog, settings)
    with database(db_path) as conn:
        apply_store_catalog(conn, source.catalog, tables=("bookings",))
        inserted = insert_bookings(conn, bookings)
        headcount_stores = replace_headcount(conn, source.headcount) if source.headcount else 0
    return BookingsLoadResult(stats=stats, inserted=inserted, headcount_stores=headcount_stores)


def load_revenue(workbook: Path, db_path: Path, settings: RevenueSettings) -> RevenueLoadResult:
    init_db(db_path)
    source = read_revenue_workbook(workbook, settings)
    revenue, stats = normalize_revenue(source.frame, source.catalog, settings)
    with database(db_path) as conn:
        consolidated, removed = apply_store_catalog(conn, source.catalog, tables=("revenue",))
        inserted = insert_revenue(conn, revenue)
    return RevenueLoadResult(
        stats=stats, inserted=inserted, consolidated=consolidated, removed=removed
    )
