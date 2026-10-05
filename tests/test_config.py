from __future__ import annotations

import json

import pytest

from staffing_analytics.config import (
    ConfigError,
    default_settings,
    load_settings,
    settings_from_dict,
)


def test_defaults_and_relative_paths(tmp_path):
    settings = default_settings(tmp_path)
    assert settings.paths.database == (tmp_path / "data" / "staffing.db").resolve()
    assert settings.revenue.allowed_operation_codes == (100, 101, 102, 110, 190)
    assert settings.labor.permanent_hourly_cost == pytest.approx(2500.0 / 220)


@pytest.mark.parametrize(
    "data",
    [
        {"labor": {"recurrence_warning_days": 4, "recurrence_critical_days": 4}},
        {"revenue": {"sales_operation_codes": ["x"]}},
        {"revenue": {"store_aliases": ["a", "b"]}},
        {"revenue": {"sales_operation_codes": []}},
        {"bookings": {"max_future_months": -1}},
    ],
)
def test_invalid_configurations(tmp_path, data):
    with pytest.raises(ConfigError):
        settings_from_dict(data, tmp_path)


def test_load_settings_from_file(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "revenue": {"store_aliases": {"03.X": "Loja X"}},
                "labor": {"permanent_monthly_cost": 3000},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STAFFING_ANALYTICS_CONFIG", raising=False)
    settings = load_settings()
    assert settings.revenue.store_aliases == {"03.X": "Loja X"}
    assert settings.labor.permanent_monthly_cost == 3000.0
