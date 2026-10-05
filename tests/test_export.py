from __future__ import annotations

import pandas as pd

from staffing_analytics.analytics.export import build_dashboard
from staffing_analytics.config import BookingsSettings, RevenueSettings, default_settings
from staffing_analytics.etl.load import load_bookings, load_revenue
from tests.helpers import REVENUE_MAPPING, STORE_MAPPING, booking_row, revenue_row, write_workbook


def test_build_dashboard_embeds_everything_and_escapes(tmp_path):
    settings = default_settings(tmp_path)
    bookings = write_workbook(
        tmp_path / "b.xlsx",
        {
            "BD": pd.DataFrame([booking_row(**{"Nome": "Ana </script> Souza"})]),
            "MapeamentoLojas": STORE_MAPPING,
            "QuadroCLT": pd.DataFrame([{"Loja": "Loja Centro", "Efetivos": 2}]),
        },
    )
    revenue = write_workbook(
        tmp_path / "r.xlsx", {"BD": pd.DataFrame([revenue_row()]), "Lojas": REVENUE_MAPPING}
    )
    db = tmp_path / "s.db"
    load_bookings(bookings, db, BookingsSettings())
    load_revenue(revenue, db, RevenueSettings(sales_operation_codes=(100,)))

    result = build_dashboard(db, tmp_path / "out" / "dash.html", settings)
    html = result.output.read_text(encoding="utf-8")
    assert result.bookings == 1 and result.revenue_rows == 1
    for token in (
        "__TITLE__",
        "__STYLES__",
        "__SCRIPT__",
        "__BOOKINGS_JSON__",
        "__REVENUE_JSON__",
        "__LABOR_JSON__",
        "__HEADCOUNT_JSON__",
    ):
        assert token not in html
    assert '"worker": "Ana <\\/script> Souza"' in html
    assert '"permanent_monthly_cost": 2500.0' in html
    assert 'window.HEADCOUNT = {"Loja Centro": 2}' in html
    assert '"store": "Loja Centro"' in html
    assert settings.dashboard.title in html
