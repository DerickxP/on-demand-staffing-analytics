"""Regras de negócio em funções puras e testáveis.

O dashboard reproduz estas mesmas regras no navegador para permitir filtros cruzados.
Aqui elas existem em Python para serem testadas, usadas no relatório de terminal e
servir de referência do que o JavaScript deve fazer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from staffing_analytics.config import LaborSettings
from staffing_analytics.etl.bookings import CANCELLED_STATUSES
from staffing_analytics.etl.dates import iso_week
from staffing_analytics.etl.schema import database

SHIFT_ORDER = ("Manhã", "Tarde", "Noite", "Madrugada")
WEEKDAYS_PT = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")
RISK_LOW, RISK_WARNING, RISK_CRITICAL = "low", "warning", "critical"


@dataclass(frozen=True)
class Frames:
    bookings: pd.DataFrame
    revenue: pd.DataFrame
    headcount: dict[str, int]


@dataclass(frozen=True)
class Recommendation:
    kind: str  # on_demand | evaluate | hire
    label: str
    fte: float
    suggested_headcount: int
    equivalent_cost: float


def shift_for_hour(hour: int | None) -> str:
    if hour is None or pd.isna(hour):
        return "Madrugada"
    hour = int(hour)
    if 6 <= hour < 12:
        return "Manhã"
    if 12 <= hour < 18:
        return "Tarde"
    if 18 <= hour < 24:
        return "Noite"
    return "Madrugada"


def is_cancelled(status: str | None) -> bool:
    return str(status or "").strip().upper() in CANCELLED_STATUSES


def distribute_hours(start_hour: int, hours: float) -> dict[int, float]:
    """Reparte a duração de um agendamento hora a hora a partir da hora de início.

    Um turno das 18h com 6 horas computadas contribui 1 hora para 18h, 19h, ..., 23h.
    É o que permite comparar custo e faturamento na mesma faixa horária.
    """
    allocation: dict[int, float] = {}
    remaining = float(hours or 0)
    current = int(start_hour) % 24
    while remaining > 1e-9:
        share = min(1.0, remaining)
        allocation[current] = allocation.get(current, 0.0) + share
        remaining -= share
        current = (current + 1) % 24
    return allocation


def cost_by_hour(bookings: pd.DataFrame) -> dict[int, float]:
    """Custo distribuído por hora do dia, ignorando cancelados e sem horas."""
    result: dict[int, float] = {}
    for row in bookings.itertuples(index=False):
        if row.cancelled or not row.computed_hours or pd.isna(row.hour):
            continue
        per_hour = float(row.cost) / float(row.computed_hours)
        for hour, share in distribute_hours(int(row.hour), float(row.computed_hours)).items():
            result[hour] = result.get(hour, 0.0) + share * per_hour
    return result


def cost_by_shift(bookings: pd.DataFrame) -> dict[str, float]:
    result = {shift: 0.0 for shift in SHIFT_ORDER}
    for hour, value in cost_by_hour(bookings).items():
        result[shift_for_hour(hour)] += value
    return result


def cost_share_by_store(bookings: pd.DataFrame, revenue: pd.DataFrame) -> pd.DataFrame:
    """Custo, horas e agendamentos por loja, com a participação do custo na receita."""
    active = bookings[~bookings["cancelled"]]
    cost = active.groupby("store").agg(
        cost=("cost", "sum"), hours=("computed_hours", "sum"), bookings=("booking_key", "count")
    )
    net = (
        revenue.groupby("store")["net"].sum().rename("revenue")
        if len(revenue)
        else pd.Series(dtype=float, name="revenue")
    )
    table = cost.join(net, how="outer").fillna(
        {"cost": 0.0, "hours": 0.0, "bookings": 0, "revenue": 0.0}
    )
    table["share_pct"] = pd.Series(
        [(row.cost / row.revenue * 100) if row.revenue > 0 else None for row in table.itertuples()],
        index=table.index,
        dtype=object,
    )
    table["bookings"] = table["bookings"].astype(int)
    return table.sort_values("revenue", ascending=False).reset_index()


def recurrence_risk(
    bookings: pd.DataFrame, *, warning_days: int = 3, critical_days: int = 4
) -> pd.DataFrame:
    """Frequência semanal por prestador e classificação de risco de vínculo.

    A recomendação jurídica adotada é limitar a prestação a poucos dias por semana; um
    prestador que trabalha quase toda semana em regime de rotina se parece com um
    empregado. ``peak_days_per_week`` é o maior número de dias distintos trabalhados em
    uma mesma semana ISO.
    """
    active = bookings[~bookings["cancelled"] & bookings["start"].notna()].copy()
    if active.empty:
        return pd.DataFrame(
            columns=["worker_name", "active_weeks", "peak_days_per_week", "stores", "roles", "risk"]
        )
    active["week"] = active["start"].map(iso_week)
    active["day"] = active["start"].dt.strftime("%Y-%m-%d")
    per_week = active.groupby(["worker_name", "week"])["day"].nunique()
    peaks = per_week.groupby("worker_name").max().rename("peak_days_per_week")
    weeks = per_week.groupby("worker_name").size().rename("active_weeks")
    stores = (
        active.groupby("worker_name")["store"].agg(lambda s: tuple(sorted(set(s)))).rename("stores")
    )
    roles = (
        active.groupby("worker_name")["role"]
        .agg(lambda s: tuple(sorted({r for r in s if r})))
        .rename("roles")
    )
    table = pd.concat([weeks, peaks, stores, roles], axis=1).reset_index()

    def classify(peak: int) -> str:
        if peak >= critical_days:
            return RISK_CRITICAL
        if peak >= warning_days:
            return RISK_WARNING
        return RISK_LOW

    table["risk"] = table["peak_days_per_week"].map(classify)
    return table.sort_values(
        ["peak_days_per_week", "worker_name"], ascending=[False, True]
    ).reset_index(drop=True)


def hiring_recommendation(
    hours: float, cost: float, *, labor: LaborSettings, permanent_role: bool
) -> Recommendation:
    """Sugere contratar efetivos quando as horas sob demanda viram rotina cara.

    ``fte`` é o equivalente em funcionários de jornada completa (horas ÷ jornada mensal).
    Para a função de referência, compara-se o custo sob demanda com o custo de contratar
    o número inteiro de efetivos equivalente.
    """
    fte = float(hours) / labor.monthly_hours if labor.monthly_hours else 0.0
    suggested = max(math.ceil(fte), 1) if hours > 0 else 0
    equivalent_cost = suggested * labor.permanent_monthly_cost

    if permanent_role:
        if hours < labor.on_demand_max_hours:
            return Recommendation(
                "on_demand", "Sob demanda (ideal)", fte, suggested, equivalent_cost
            )
        if cost >= equivalent_cost * labor.hire_cost_ratio:
            return Recommendation(
                "hire", f"Contratar {suggested} efetivo(s)", fte, suggested, equivalent_cost
            )
        if hours >= labor.evaluate_threshold_hours:
            return Recommendation(
                "evaluate", f"Avaliar {suggested} efetivo(s)", fte, suggested, equivalent_cost
            )
        return Recommendation("on_demand", "Sob demanda", fte, suggested, equivalent_cost)

    if hours >= labor.evaluate_threshold_hours:
        return Recommendation(
            "evaluate", f"Considerar {suggested} efetivo(s)", fte, suggested, equivalent_cost
        )
    return Recommendation("on_demand", "Sob demanda", fte, suggested, equivalent_cost)


def workforce_by_store_role(bookings: pd.DataFrame) -> pd.DataFrame:
    active = bookings[~bookings["cancelled"]]
    table = active.groupby(["store", "role"]).agg(
        hours=("computed_hours", "sum"), cost=("cost", "sum")
    )
    return table[table["hours"] > 0].sort_values("hours", ascending=False).reset_index()


def _enrich_bookings(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["start"] = pd.to_datetime(frame["start_at"], errors="coerce")
    frame["cancelled"] = frame["status"].map(is_cancelled)
    frame["hour"] = frame["start"].dt.hour
    frame["shift"] = frame["hour"].map(shift_for_hour)
    frame["weekday"] = frame["start"].map(
        lambda v: WEEKDAYS_PT[v.weekday()] if not pd.isna(v) else ""
    )
    frame["cost"] = pd.to_numeric(frame["cost"], errors="coerce").fillna(0.0)
    frame["computed_hours"] = pd.to_numeric(frame["computed_hours"], errors="coerce").fillna(0.0)
    return frame


def load_frames(db_path: Path, stores: Iterable[str] | None = None) -> Frames:
    with database(db_path) as conn:
        bookings = pd.read_sql_query("SELECT * FROM bookings ORDER BY start_at", conn)
        revenue = pd.read_sql_query("SELECT * FROM revenue ORDER BY sale_date, hour", conn)
        headcount = dict(conn.execute("SELECT store, permanent FROM headcount").fetchall())
    bookings = _enrich_bookings(bookings)
    if stores is not None:
        wanted = set(stores)
        bookings = bookings[bookings["store"].isin(wanted)]
        revenue = revenue[revenue["store"].isin(wanted)]
    return Frames(bookings=bookings, revenue=revenue, headcount=headcount)
