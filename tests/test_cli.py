from __future__ import annotations

import pytest

from staffing_analytics.cli import main


def test_demo_command_runs_the_whole_pipeline(tmp_path, capsys):
    output = tmp_path / "demo"
    code = main(
        [
            "demo",
            "--output-dir",
            str(output),
            "--months",
            "2",
            "--workers",
            "10",
            "--bookings-per-month",
            "60",
            "--seed",
            "3",
        ]
    )
    assert code == 0
    assert (output / "output" / "dashboard.html").exists()
    assert (output / "data" / "staffing.db").exists()
    assert (output / "config.json").exists()
    assert "RESUMO GERAL" in capsys.readouterr().out


def test_missing_config_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STAFFING_ANALYTICS_CONFIG", raising=False)
    with pytest.raises(SystemExit) as raised:
        main(["init-db"])
    assert raised.value.code == 2
