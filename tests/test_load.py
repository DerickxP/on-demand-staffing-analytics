from __future__ import annotations

from dataclasses import replace

import pandas as pd

from staffing_analytics.config import BookingsSettings, RevenueSettings
from staffing_analytics.etl.load import load_bookings, load_revenue
from staffing_analytics.etl.schema import database
from tests.helpers import REVENUE_MAPPING, STORE_MAPPING, booking_row, revenue_row, write_workbook


def test_load_bookings_is_idempotent(tmp_path):
    workbook = write_workbook(
        tmp_path / "b.xlsx",
        {
            "BD": pd.DataFrame(
                [booking_row(), booking_row(**{"Ref Agendamento": "AG-2", "Nome": "Bia Lima"})]
            ),
            "MapeamentoLojas": STORE_MAPPING,
            "QuadroCLT": pd.DataFrame([{"Loja": "Loja Centro", "Efetivos": 3}]),
        },
    )
    db = tmp_path / "s.db"
    first = load_bookings(workbook, db, BookingsSettings())
    second = load_bookings(workbook, db, BookingsSettings())
    assert first.inserted == 2 and first.headcount_stores == 1
    assert second.inserted == 0
    with database(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 2
        assert conn.execute("SELECT permanent FROM headcount").fetchone() == (3,)


def test_load_revenue_is_idempotent_and_new_aliases_consolidate_history(tmp_path):
    workbook = write_workbook(
        tmp_path / "r.xlsx",
        {
            "BD": pd.DataFrame(
                [revenue_row(), revenue_row(**{"Empresa": "03.LJ SUL NOVO", "Hora do Dia": 11})]
            ),
            "Lojas": REVENUE_MAPPING,
        },
    )
    db = tmp_path / "s.db"
    settings = RevenueSettings(sales_operation_codes=(100,))
    first = load_revenue(workbook, db, settings)
    assert first.inserted == 2
    assert [s.raw_name for s in first.stats.rename_suspects] == ["03.LJ SUL NOVO"]
    with database(db) as conn:
        assert sorted(r[0] for r in conn.execute("SELECT DISTINCT store FROM revenue")) == [
            "03.LJ SUL NOVO",
            "Loja Centro",
        ]

    with_alias = replace(settings, store_aliases={"03.LJ SUL NOVO": "Loja Sul"})
    second = load_revenue(workbook, db, with_alias)
    assert second.consolidated == 1
    assert second.inserted == 1  # a linha renomeada agora tem outra chave (loja canônica)
    with database(db) as conn:
        stores = sorted(r[0] for r in conn.execute("SELECT DISTINCT store FROM revenue"))
    assert stores == ["Loja Centro", "Loja Sul"]
    third = load_revenue(workbook, db, with_alias)
    assert third.inserted == 0 and third.consolidated == 0
