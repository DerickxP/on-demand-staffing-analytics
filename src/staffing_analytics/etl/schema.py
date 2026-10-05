"""Esquema do banco SQLite.

* ``bookings``: um agendamento por linha, com chave de conteúdo única (idempotência).
* ``revenue``: faturamento por loja, data, hora e código de operação, também com chave.
* ``headcount``: quadro fixo (funcionários efetivos da função de referência) por loja.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DDL = (
    """
    CREATE TABLE IF NOT EXISTS bookings (
        booking_key     TEXT PRIMARY KEY,
        booking_ref     TEXT,
        worker_name     TEXT NOT NULL,
        state           TEXT,
        store           TEXT NOT NULL,
        role            TEXT,
        start_at        TEXT NOT NULL,
        end_at          TEXT,
        scheduled_at    TEXT,
        started_at      TEXT,
        completed_at    TEXT,
        cost            REAL NOT NULL DEFAULT 0,
        computed_hours  REAL NOT NULL DEFAULT 0,
        status          TEXT,
        cancelled_at    TEXT,
        cancel_reason   TEXT,
        cancelled_by    TEXT,
        source_file     TEXT,
        loaded_at       TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS revenue (
        revenue_key     TEXT PRIMARY KEY,
        store           TEXT NOT NULL,
        sale_date       TEXT NOT NULL,
        weekday         TEXT,
        hour            INTEGER,
        operation_code  INTEGER,
        quantity        REAL,
        gross           REAL,
        discount        REAL,
        net             REAL NOT NULL,
        loaded_at       TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS headcount (
        store       TEXT PRIMARY KEY,
        permanent   INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bookings_store ON bookings(store)",
    "CREATE INDEX IF NOT EXISTS idx_bookings_start ON bookings(start_at)",
    "CREATE INDEX IF NOT EXISTS idx_bookings_worker ON bookings(worker_name)",
    "CREATE INDEX IF NOT EXISTS idx_revenue_store_date ON revenue(store, sale_date)",
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


@contextmanager
def database(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    with database(db_path) as conn:
        for statement in DDL:
            conn.execute(statement)
        conn.commit()
