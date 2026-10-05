from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from staffing_analytics.config import default_settings
from staffing_analytics.demo.synthetic import DemoDataset, generate_demo_dataset


@pytest.fixture
def small_dataset(tmp_path: Path) -> DemoDataset:
    """Três meses fechados antes de ago/2026, sem afinamento de escala (keep_ratio = 1)."""
    return generate_demo_dataset(
        default_settings(tmp_path / "demo"),
        seed=11,
        months=3,
        workers=20,
        bookings_per_month=5000,
        anchor=date(2026, 8, 15),
    )
