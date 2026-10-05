from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from staffing_analytics.etl.dates import future_mask, iso_week, parse_mixed_dates


def test_mixed_column_is_parsed_without_swapping_day_and_month():
    series = pd.Series(
        [
            datetime(2026, 1, 10, 8, 0),
            "2026-01-10 08:00:00",
            "10/01/2026 08:00",
            "2025-11-30",
            None,
            "não é data",
        ]
    )
    converted, stats = parse_mixed_dates(series)
    assert converted.iloc[0] == converted.iloc[1] == converted.iloc[2]
    assert converted.iloc[0].strftime("%Y-%m-%d") == "2026-01-10"
    assert converted.iloc[3].strftime("%Y-%m-%d") == "2025-11-30"  # dayfirst quebraria aqui
    assert pd.isna(converted.iloc[4]) and pd.isna(converted.iloc[5])
    assert stats.total == 5
    assert stats.text_values == 4
    assert stats.parsed_as_iso == 2
    assert stats.lost == 1


def test_future_mask_flags_only_dates_beyond_the_horizon():
    series = pd.to_datetime(pd.Series(["2026-08-01", "2026-10-31", "2026-11-01", None]))
    mask = future_mask(series, 2, today=date(2026, 8, 31))
    assert mask.tolist() == [False, False, True, False]


def test_iso_week():
    assert iso_week(pd.Timestamp("2026-01-01")) == "2026-W01"
    assert iso_week(pd.Timestamp("2024-12-30")) == "2025-W01"
    assert iso_week(pd.Timestamp("2026-08-16")) == "2026-W33"
