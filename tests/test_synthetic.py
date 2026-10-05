from __future__ import annotations

from staffing_analytics.analytics.export import build_dashboard
from staffing_analytics.analytics.metrics import (
    RISK_CRITICAL,
    RISK_LOW,
    RISK_WARNING,
    load_frames,
    recurrence_risk,
)
from staffing_analytics.analytics.report import render_report
from staffing_analytics.etl.consolidate import consolidate_workbooks
from staffing_analytics.etl.load import load_bookings, load_revenue


def test_pipeline_reproduces_the_generators_truth(small_dataset, tmp_path):
    settings = small_dataset.settings
    paths = settings.paths

    consolidation = consolidate_workbooks(paths.bookings_dir, paths.consolidated_workbook)
    assert consolidation.files == 3
    assert consolidation.exact_duplicates > 0  # sobreposição entre exports
    assert len(consolidation.conflicting_keys) == 1  # conflito injetado

    bookings = load_bookings(paths.consolidated_workbook, paths.database, settings.bookings)
    assert bookings.inserted == small_dataset.bookings
    assert bookings.stats.excluded_stores > 0  # agendamentos no balcão
    assert bookings.stats.date_stats.text_values > 0 and bookings.stats.date_stats.lost == 0

    revenue = load_revenue(paths.revenue_workbook, paths.database, settings.revenue)
    assert revenue.stats.excluded_clients > 0 and revenue.stats.excluded_codes > 0
    assert revenue.stats.excluded_stores > 0
    assert revenue.stats.rename_suspects == ()  # apelido configurado resolve a renomeação

    frames = load_frames(paths.database)
    stores = set(frames.revenue["store"])
    assert "03.LJ SUL NOVO" not in stores and "Loja Sul" in stores
    sul = frames.revenue[frames.revenue["store"] == "Loja Sul"]
    rename = small_dataset.rename_date.isoformat()
    assert (sul["sale_date"] < rename).any() and (sul["sale_date"] >= rename).any()
    assert not any(name in stores for name in ("Balcão", "99.GALPAO"))
    assert set(frames.revenue["operation_code"]).issubset(
        set(settings.revenue.allowed_operation_codes)
    )
    assert set(frames.bookings["store"]).issubset(set(small_dataset.platform_to_canonical.values()))

    risk = recurrence_risk(
        frames.bookings,
        warning_days=settings.labor.recurrence_warning_days,
        critical_days=settings.labor.recurrence_critical_days,
    ).set_index("worker_name")
    expected = {p.name: p.days_per_week for p in small_dataset.profiles}
    for worker, row in risk.iterrows():
        days = expected[worker]
        if days >= 4:
            assert row.risk == RISK_CRITICAL, (worker, days, row.peak_days_per_week)
        elif days == 3:
            assert row.risk == RISK_WARNING, (worker, days, row.peak_days_per_week)
        else:
            assert row.risk == RISK_LOW, (worker, days, row.peak_days_per_week)
    assert (risk["risk"] == RISK_CRITICAL).any()

    result = build_dashboard(paths.database, paths.dashboard, settings)
    assert result.output.stat().st_size > 100_000
    assert "RESUMO GERAL" in render_report(paths.database, settings.labor)
