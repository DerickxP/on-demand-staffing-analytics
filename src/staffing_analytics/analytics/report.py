"""Resumo em texto para o terminal (útil em automações e para conferir o banco)."""

from __future__ import annotations

from pathlib import Path

from staffing_analytics.analytics.metrics import (
    RISK_CRITICAL,
    RISK_WARNING,
    cost_share_by_store,
    hiring_recommendation,
    load_frames,
    recurrence_risk,
    workforce_by_store_role,
)
from staffing_analytics.config import LaborSettings
from staffing_analytics.etl.text import normalize_key


def brl(value: float) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.2f}%".replace(".", ",")


def hours_text(value: float) -> str:
    return f"{value:,.0f} h".replace(",", ".")


def render_report(db_path: Path, labor: LaborSettings, *, top: int = 8) -> str:
    frames = load_frames(db_path)
    bookings, revenue = frames.bookings, frames.revenue
    active = bookings[~bookings["cancelled"]]
    lines: list[str] = []

    total_cost = float(active["cost"].sum())
    total_hours = float(active["computed_hours"].sum())
    total_revenue = float(revenue["net"].sum()) if len(revenue) else 0.0
    share = pct(total_cost / total_revenue * 100) if total_revenue > 0 else "n/d"
    lines.append("RESUMO GERAL")
    lines.append(f"  Agendamentos ativos: {len(active)} de {len(bookings)}")
    lines.append(f"  Custo sob demanda:   {brl(total_cost)}  ({hours_text(total_hours)})")
    lines.append(f"  Faturamento líquido: {brl(total_revenue)}")
    lines.append(f"  Custo / faturamento: {share}")

    lines.append("")
    lines.append("CUSTO POR LOJA (participação na receita)")
    table = cost_share_by_store(bookings, revenue)
    for row in table.head(top).itertuples(index=False):
        lines.append(
            f"  {row.store:<24} custo {brl(row.cost):>16}  receita {brl(row.revenue):>18}  "
            f"{pct(row.share_pct):>8}"
        )

    lines.append("")
    risk = recurrence_risk(
        bookings,
        warning_days=labor.recurrence_warning_days,
        critical_days=labor.recurrence_critical_days,
    )
    critical = risk[risk["risk"] == RISK_CRITICAL]
    warning = risk[risk["risk"] == RISK_WARNING]
    lines.append(
        f"RISCO DE RECORRÊNCIA: {len(critical)} crítico(s) "
        f"(≥ {labor.recurrence_critical_days} dias/semana), {len(warning)} em atenção "
        f"(≥ {labor.recurrence_warning_days}), {len(risk)} prestador(es) ativos"
    )
    for row in critical.head(top).itertuples(index=False):
        lines.append(
            f"  {row.worker_name:<28} pico {row.peak_days_per_week} dias/semana em "
            f"{row.active_weeks} semana(s) ativa(s) | {', '.join(row.stores)}"
        )

    lines.append("")
    lines.append(f"SUGESTÕES DE CONTRATAÇÃO (função de referência: {labor.permanent_role})")
    permanent_key = normalize_key(labor.permanent_role)
    suggestions = []
    for row in workforce_by_store_role(bookings).itertuples(index=False):
        rec = hiring_recommendation(
            row.hours,
            row.cost,
            labor=labor,
            permanent_role=normalize_key(row.role) == permanent_key,
        )
        if rec.kind != "on_demand":
            suggestions.append((row.store, row.role, row.hours, row.cost, rec))
    if not suggestions:
        lines.append("  Nenhuma função ultrapassa os limiares configurados.")
    for store, role, hours, cost, rec in suggestions[:top]:
        lines.append(f"  {store:<24} {role:<20} {hours:>7.1f} h  {brl(cost):>14}  -> {rec.label}")
    return "\n".join(lines)
