"""Configuração (``config.json``) validada em dataclasses imutáveis.

Tudo o que é regra do negócio e muda de empresa para empresa fica aqui, fora do código:
códigos de operação que contam como venda, clientes e lojas excluídos, apelidos de loja,
parâmetros de custo de pessoal e limiares de risco de recorrência.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_ENV_VAR = "STAFFING_ANALYTICS_CONFIG"
DEFAULT_CONFIG_FILES = ("config.json", "config.example.json")


class ConfigError(ValueError):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class PathSettings:
    bookings_dir: Path
    consolidated_workbook: Path
    bookings_workbook: Path
    revenue_workbook: Path
    database: Path
    dashboard: Path


@dataclass(frozen=True)
class BookingsSettings:
    sheet: str = "BD"
    store_mapping_sheet: str = "MapeamentoLojas"
    headcount_sheet: str = "QuadroCLT"
    state: str = "SP"
    max_future_months: int = 2
    exclude_store_patterns: tuple[str, ...] = ("BALCAO",)


@dataclass(frozen=True)
class RevenueSettings:
    sheet: str = "BD"
    store_mapping_sheet: str = "Lojas"
    sales_operation_codes: tuple[int, ...] = (100, 101, 102, 110)
    return_operation_codes: tuple[int, ...] = (190,)
    excluded_clients: tuple[str, ...] = ()
    exclude_store_patterns: tuple[str, ...] = ("BALCAO",)
    ignored_stores: tuple[str, ...] = ()
    store_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def allowed_operation_codes(self) -> tuple[int, ...]:
        return tuple(self.sales_operation_codes) + tuple(self.return_operation_codes)


@dataclass(frozen=True)
class LaborSettings:
    permanent_role: str = "Empacotador"
    permanent_monthly_cost: float = 2500.0
    monthly_hours: int = 220
    on_demand_max_hours: float = 44.0
    evaluate_threshold_hours: float = 150.0
    hire_cost_ratio: float = 0.85
    recurrence_warning_days: int = 3
    recurrence_critical_days: int = 4

    @property
    def permanent_hourly_cost(self) -> float:
        return self.permanent_monthly_cost / self.monthly_hours


@dataclass(frozen=True)
class DashboardSettings:
    title: str = "Mão de obra sob demanda"
    subtitle: str = "Custo de prestadores versus faturamento por loja"
    brand: str = "Demo"
    logo: Path | None = None


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    paths: PathSettings
    bookings: BookingsSettings
    revenue: RevenueSettings
    labor: LaborSettings
    dashboard: DashboardSettings


def _resolve(base_dir: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def _str_tuple(values: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if values is None:
        return default
    if not isinstance(values, list):
        raise ConfigError(f"Esperada uma lista, recebido {type(values).__name__}.")
    return tuple(str(value).strip() for value in values if str(value).strip())


def _int_tuple(values: Any, default: tuple[int, ...]) -> tuple[int, ...]:
    if values is None:
        return default
    if not isinstance(values, list):
        raise ConfigError(f"Esperada uma lista de inteiros, recebido {type(values).__name__}.")
    try:
        return tuple(int(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Códigos de operação devem ser inteiros: {values}") from exc


def default_paths(base_dir: Path) -> PathSettings:
    return PathSettings(
        bookings_dir=_resolve(base_dir, "data/bookings"),
        consolidated_workbook=_resolve(base_dir, "data/bookings_consolidated.xlsx"),
        bookings_workbook=_resolve(base_dir, "data/bookings.xlsx"),
        revenue_workbook=_resolve(base_dir, "data/revenue.xlsx"),
        database=_resolve(base_dir, "data/staffing.db"),
        dashboard=_resolve(base_dir, "output/dashboard.html"),
    )


def settings_from_dict(data: dict[str, Any], base_dir: Path) -> Settings:
    defaults = default_paths(base_dir)
    paths_raw = data.get("paths", {})
    paths = PathSettings(
        bookings_dir=_resolve(base_dir, paths_raw.get("bookings_dir", defaults.bookings_dir)),
        consolidated_workbook=_resolve(
            base_dir, paths_raw.get("consolidated_workbook", defaults.consolidated_workbook)
        ),
        bookings_workbook=_resolve(
            base_dir, paths_raw.get("bookings_workbook", defaults.bookings_workbook)
        ),
        revenue_workbook=_resolve(
            base_dir, paths_raw.get("revenue_workbook", defaults.revenue_workbook)
        ),
        database=_resolve(base_dir, paths_raw.get("database", defaults.database)),
        dashboard=_resolve(base_dir, paths_raw.get("dashboard", defaults.dashboard)),
    )

    b_raw = data.get("bookings", {})
    bookings = BookingsSettings(
        sheet=str(b_raw.get("sheet", BookingsSettings.sheet)),
        store_mapping_sheet=str(
            b_raw.get("store_mapping_sheet", BookingsSettings.store_mapping_sheet)
        ),
        headcount_sheet=str(b_raw.get("headcount_sheet", BookingsSettings.headcount_sheet)),
        state=str(b_raw.get("state", BookingsSettings.state)),
        max_future_months=int(b_raw.get("max_future_months", BookingsSettings.max_future_months)),
        exclude_store_patterns=_str_tuple(
            b_raw.get("exclude_store_patterns"), BookingsSettings.exclude_store_patterns
        ),
    )
    if bookings.max_future_months < 0:
        raise ConfigError("'bookings.max_future_months' não pode ser negativo.")

    r_raw = data.get("revenue", {})
    aliases_raw = r_raw.get("store_aliases") or {}
    if not isinstance(aliases_raw, dict):
        raise ConfigError(
            "'revenue.store_aliases' deve ser um objeto {nome_no_erp: nome_canonico}."
        )
    revenue = RevenueSettings(
        sheet=str(r_raw.get("sheet", RevenueSettings.sheet)),
        store_mapping_sheet=str(
            r_raw.get("store_mapping_sheet", RevenueSettings.store_mapping_sheet)
        ),
        sales_operation_codes=_int_tuple(
            r_raw.get("sales_operation_codes"), RevenueSettings.sales_operation_codes
        ),
        return_operation_codes=_int_tuple(
            r_raw.get("return_operation_codes"), RevenueSettings.return_operation_codes
        ),
        excluded_clients=_str_tuple(r_raw.get("excluded_clients"), ()),
        exclude_store_patterns=_str_tuple(
            r_raw.get("exclude_store_patterns"), RevenueSettings.exclude_store_patterns
        ),
        ignored_stores=_str_tuple(r_raw.get("ignored_stores"), ()),
        store_aliases={str(k).strip(): str(v).strip() for k, v in aliases_raw.items()},
    )
    if not revenue.sales_operation_codes:
        raise ConfigError("Informe ao menos um código em 'revenue.sales_operation_codes'.")

    l_raw = data.get("labor", {})
    labor = LaborSettings(
        permanent_role=str(l_raw.get("permanent_role", LaborSettings.permanent_role)),
        permanent_monthly_cost=float(
            l_raw.get("permanent_monthly_cost", LaborSettings.permanent_monthly_cost)
        ),
        monthly_hours=int(l_raw.get("monthly_hours", LaborSettings.monthly_hours)),
        on_demand_max_hours=float(
            l_raw.get("on_demand_max_hours", LaborSettings.on_demand_max_hours)
        ),
        evaluate_threshold_hours=float(
            l_raw.get("evaluate_threshold_hours", LaborSettings.evaluate_threshold_hours)
        ),
        hire_cost_ratio=float(l_raw.get("hire_cost_ratio", LaborSettings.hire_cost_ratio)),
        recurrence_warning_days=int(
            l_raw.get("recurrence_warning_days", LaborSettings.recurrence_warning_days)
        ),
        recurrence_critical_days=int(
            l_raw.get("recurrence_critical_days", LaborSettings.recurrence_critical_days)
        ),
    )
    if labor.monthly_hours <= 0 or labor.permanent_monthly_cost <= 0:
        raise ConfigError(
            "'labor.monthly_hours' e 'labor.permanent_monthly_cost' devem ser positivos."
        )
    if labor.recurrence_critical_days <= labor.recurrence_warning_days:
        raise ConfigError(
            "'recurrence_critical_days' deve ser maior que 'recurrence_warning_days'."
        )

    d_raw = data.get("dashboard", {})
    logo = d_raw.get("logo")
    dashboard = DashboardSettings(
        title=str(d_raw.get("title", DashboardSettings.title)),
        subtitle=str(d_raw.get("subtitle", DashboardSettings.subtitle)),
        brand=str(d_raw.get("brand", DashboardSettings.brand)),
        logo=_resolve(base_dir, logo) if logo else None,
    )

    return Settings(
        base_dir=base_dir,
        paths=paths,
        bookings=bookings,
        revenue=revenue,
        labor=labor,
        dashboard=dashboard,
    )


def default_settings(base_dir: Path) -> Settings:
    """Configuração padrão apontando para ``base_dir`` (usada pela demonstração e testes)."""
    return settings_from_dict({}, base_dir)


def find_config_file(explicit: str | Path | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise ConfigError(f"Arquivo de configuração não encontrado: {path}")
        return path
    env_value = os.environ.get(CONFIG_ENV_VAR)
    if env_value:
        return find_config_file(env_value)
    for name in DEFAULT_CONFIG_FILES:
        candidate = Path.cwd() / name
        if candidate.exists():
            return candidate
    raise ConfigError(
        "Nenhum config.json encontrado. Copie config.example.json para config.json e ajuste."
    )


def load_settings(path: str | Path | None = None) -> Settings:
    config_file = find_config_file(path)
    with open(config_file, encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"JSON inválido em {config_file}: {exc}") from exc
    return settings_from_dict(data, config_file.resolve().parent)
