from __future__ import annotations

import pandas as pd
import pytest

from staffing_analytics.analytics.metrics import (
    RISK_CRITICAL,
    RISK_LOW,
    RISK_WARNING,
    cost_by_hour,
    cost_by_shift,
    cost_share_by_store,
    distribute_hours,
    hiring_recommendation,
    recurrence_risk,
    shift_for_hour,
)
from staffing_analytics.config import LaborSettings

LABOR = LaborSettings(permanent_monthly_cost=2200.0, monthly_hours=220)


def _bookings(rows):
    frame = pd.DataFrame(rows)
    frame["start"] = pd.to_datetime(frame["start_at"])
    frame["hour"] = frame["start"].dt.hour
    if "cancelled" in frame.columns:
        frame["cancelled"] = frame["cancelled"].fillna(False).astype(bool)
    else:
        frame["cancelled"] = False
    frame["booking_key"] = [f"k{i}" for i in range(len(frame))]
    return frame


def test_shift_and_distribution():
    assert [shift_for_hour(h) for h in (0, 5, 6, 11, 12, 17, 18, 23, None)] == [
        "Madrugada",
        "Madrugada",
        "Manhã",
        "Manhã",
        "Tarde",
        "Tarde",
        "Noite",
        "Noite",
        "Madrugada",
    ]
    assert distribute_hours(22, 3.5) == {22: 1.0, 23: 1.0, 0: 1.0, 1: 0.5}
    assert distribute_hours(8, 0) == {}


def test_cost_by_hour_and_shift_skip_cancelled():
    bookings = _bookings(
        [
            {
                "worker_name": "A",
                "store": "S",
                "role": "R",
                "start_at": "2026-07-01 17:00",
                "cost": 40.0,
                "computed_hours": 2.0,
            },
            {
                "worker_name": "B",
                "store": "S",
                "role": "R",
                "start_at": "2026-07-01 17:00",
                "cost": 99.0,
                "computed_hours": 2.0,
                "cancelled": True,
            },
        ]
    )
    assert cost_by_hour(bookings) == {17: 20.0, 18: 20.0}
    assert cost_by_shift(bookings) == {"Manhã": 0.0, "Tarde": 20.0, "Noite": 20.0, "Madrugada": 0.0}


def test_cost_share_by_store():
    bookings = _bookings(
        [
            {
                "worker_name": "A",
                "store": "Loja X",
                "role": "R",
                "start_at": "2026-07-01 08:00",
                "cost": 100.0,
                "computed_hours": 5.0,
            },
            {
                "worker_name": "B",
                "store": "Loja Y",
                "role": "R",
                "start_at": "2026-07-02 08:00",
                "cost": 50.0,
                "computed_hours": 4.0,
            },
        ]
    )
    revenue = pd.DataFrame([{"store": "Loja X", "net": 5000.0}, {"store": "Loja Z", "net": 100.0}])
    table = cost_share_by_store(bookings, revenue).set_index("store")
    assert table.loc["Loja X", "share_pct"] == pytest.approx(2.0)
    assert table.loc["Loja Y", "share_pct"] is None
    assert table.loc["Loja Z", "cost"] == 0.0 and table.loc["Loja Z", "bookings"] == 0


def test_recurrence_risk_uses_distinct_days_per_iso_week():
    rows = []
    for day in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"):  # 4 dias na mesma semana
        rows.append(
            {
                "worker_name": "Crítico",
                "store": "S",
                "role": "R",
                "start_at": f"{day} 08:00",
                "cost": 1,
                "computed_hours": 1,
            }
        )
    rows.append(
        {
            "worker_name": "Crítico",
            "store": "S",
            "role": "R",
            "start_at": "2026-08-03 14:00",
            "cost": 1,
            "computed_hours": 1,
        }
    )  # mesmo dia
    for day in ("2026-08-03", "2026-08-05", "2026-08-07"):
        rows.append(
            {
                "worker_name": "Atenção",
                "store": "S",
                "role": "R",
                "start_at": f"{day} 08:00",
                "cost": 1,
                "computed_hours": 1,
            }
        )
    rows.append(
        {
            "worker_name": "Baixo",
            "store": "S",
            "role": "R",
            "start_at": "2026-08-03 08:00",
            "cost": 1,
            "computed_hours": 1,
        }
    )
    rows.append(
        {
            "worker_name": "Cancelado",
            "store": "S",
            "role": "R",
            "start_at": "2026-08-03 08:00",
            "cost": 1,
            "computed_hours": 1,
            "cancelled": True,
        }
    )
    table = recurrence_risk(_bookings(rows), warning_days=3, critical_days=4).set_index(
        "worker_name"
    )
    assert (
        table.loc["Crítico", "peak_days_per_week"] == 4
        and table.loc["Crítico", "risk"] == RISK_CRITICAL
    )
    assert table.loc["Atenção", "risk"] == RISK_WARNING
    assert table.loc["Baixo", "risk"] == RISK_LOW
    assert "Cancelado" not in table.index
    assert table.loc["Crítico", "active_weeks"] == 1


def test_hiring_recommendation():
    ideal = hiring_recommendation(20, 300.0, labor=LABOR, permanent_role=True)
    assert ideal.kind == "on_demand" and "ideal" in ideal.label
    hire = hiring_recommendation(200, 2000.0, labor=LABOR, permanent_role=True)
    assert hire.kind == "hire" and hire.suggested_headcount == 1 and hire.equivalent_cost == 2200.0
    evaluate = hiring_recommendation(160, 900.0, labor=LABOR, permanent_role=True)
    assert evaluate.kind == "evaluate"
    cheap = hiring_recommendation(100, 500.0, labor=LABOR, permanent_role=True)
    assert cheap.kind == "on_demand"
    other = hiring_recommendation(160, 900.0, labor=LABOR, permanent_role=False)
    assert other.kind == "evaluate" and other.label.startswith("Considerar")
    none = hiring_recommendation(0, 0.0, labor=LABOR, permanent_role=True)
    assert none.suggested_headcount == 0
