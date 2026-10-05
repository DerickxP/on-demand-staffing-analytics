"""Geração do dashboard: um único arquivo HTML com dados, estilos e script embutidos."""

from __future__ import annotations

import base64
import html
import json
import math
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from staffing_analytics.analytics.metrics import load_frames
from staffing_analytics.config import Settings

ASSETS_DIR = Path(__file__).resolve().parents[1] / "dashboard" / "assets"

DEFAULT_LOGO_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M4 20h16"/><path d="M6 20V9l6-4 6 4v11"/><path d="M10 20v-5h4v5"/></svg>'
)


@dataclass(frozen=True)
class DashboardBuild:
    output: Path
    bookings: int
    revenue_rows: int


def _native(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _clean(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: _native(value) for key, value in row.items()} for row in records]


def bookings_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    out = pd.DataFrame(
        {
            "worker": frame["worker_name"],
            "state": frame["state"],
            "store": frame["store"],
            "role": frame["role"],
            "start": frame["start"].dt.strftime("%Y-%m-%d %H:%M"),
            "ref": frame["booking_ref"],
            "cost": pd.to_numeric(frame["cost"], errors="coerce").round(2),
            "hours": pd.to_numeric(frame["computed_hours"], errors="coerce").round(3),
            "status": frame["status"],
            "cancelled": frame["cancelled"].astype(bool),
            "reason": frame["cancel_reason"],
        }
    )
    return _clean(out.to_dict(orient="records"))


def revenue_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    out = pd.DataFrame(
        {
            "store": frame["store"],
            "date": frame["sale_date"],
            "hour": frame["hour"],
            "code": frame["operation_code"],
            "net": pd.to_numeric(frame["net"], errors="coerce").round(2),
        }
    )
    return _clean(out.to_dict(orient="records"))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _logo_html(logo: Path | None) -> str:
    if logo and Path(logo).exists():
        mime = mimetypes.guess_type(str(logo))[0] or "image/png"
        encoded = base64.b64encode(Path(logo).read_bytes()).decode("ascii")
        return f'<img src="data:{mime};base64,{encoded}" alt="logo">'
    return DEFAULT_LOGO_SVG


def render_html(
    *,
    bookings: list[dict[str, Any]],
    revenue: list[dict[str, Any]],
    headcount: dict[str, int],
    settings: Settings,
) -> str:
    template = (ASSETS_DIR / "template.html").read_text(encoding="utf-8")
    styles = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    script = (ASSETS_DIR / "app.js").read_text(encoding="utf-8")
    dashboard = settings.dashboard
    page = (
        template.replace("__TITLE__", html.escape(dashboard.title))
        .replace("__SUBTITLE__", html.escape(dashboard.subtitle))
        .replace("__BRAND__", html.escape(dashboard.brand))
        .replace("__LOGO__", _logo_html(dashboard.logo))
        .replace("__STYLES__", styles)
        .replace("__SCRIPT__", script)
        .replace("__LABOR_JSON__", _json(asdict(settings.labor)))
        .replace("__HEADCOUNT_JSON__", _json(headcount))
    )
    return page.replace("__REVENUE_JSON__", _json(revenue)).replace(
        "__BOOKINGS_JSON__", _json(bookings)
    )


def build_dashboard(db_path: Path, output: Path, settings: Settings) -> DashboardBuild:
    frames = load_frames(db_path)
    bookings = bookings_records(frames.bookings)
    revenue = revenue_records(frames.revenue)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_html(
            bookings=bookings, revenue=revenue, headcount=frames.headcount, settings=settings
        ),
        encoding="utf-8",
    )
    return DashboardBuild(output=output, bookings=len(bookings), revenue_rows=len(revenue))
