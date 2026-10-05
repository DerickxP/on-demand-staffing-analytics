"""Leitura e normalização do faturamento exportado do ERP.

O export traz todas as movimentações, não só vendas. Para bater com o BI da empresa:

* só entram os códigos de operação de venda configurados; devoluções entram com valor
  negativo para subtrair;
* clientes internos (por exemplo, o consumidor fictício do autoatendimento) e lojas que
  não vendem ao público (balcão, galpão) ficam de fora;
* os nomes de loja passam pelo catálogo, que resolve apelidos e aponta renomeações.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from staffing_analytics.config import RevenueSettings
from staffing_analytics.etl.dates import DateParseStats, future_mask, parse_mixed_dates
from staffing_analytics.etl.stores import RenameSuspect, StoreCatalog
from staffing_analytics.etl.text import (
    clean_text,
    compact_key,
    optional_column,
    pick_sheet,
    to_float,
    to_int,
)

log = logging.getLogger(__name__)

REVENUE_COLUMNS: dict[str, tuple[str, ...]] = {
    "store": ("Empresa", "Loja", "Store"),
    "client": ("Cliente", "Client"),
    "sale_date": ("Data", "Date"),
    "weekday": ("Dia da Semana", "Weekday"),
    "hour": ("Hora do Dia", "Hora", "Hour"),
    "operation_code": (
        "CGO",
        "Código de Operação",
        "Codigo de Operacao",
        "Operação",
        "Operation code",
    ),
    "quantity": ("Quantidade", "Quantity"),
    "gross": ("Valor Bruto", "Gross"),
    "discount": ("Valor Desconto", "Desconto", "Discount"),
    "net": ("Valor Liquido", "Valor Líquido", "Net"),
}
REQUIRED = ("store", "sale_date", "net")
REVENUE_OUTPUT = [
    "revenue_key",
    "store",
    "sale_date",
    "weekday",
    "hour",
    "operation_code",
    "quantity",
    "gross",
    "discount",
    "net",
]
MAPPING_RAW = ("Lojas no Sistema", "Loja Sistema", "Nome no sistema", "Raw")
MAPPING_CANONICAL = ("Lojas no Banco", "Loja", "Nome canônico", "Canonical")
WEEKDAYS_PT = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")


@dataclass(frozen=True)
class RevenueLoadStats:
    rows_in: int
    excluded_clients: int
    excluded_codes: int
    excluded_stores: int
    future_dropped: int
    duplicates: int
    rows_out: int
    rename_suspects: tuple[RenameSuspect, ...]
    new_stores: tuple[str, ...]
    date_stats: DateParseStats


@dataclass(frozen=True)
class RevenueWorkbook:
    frame: pd.DataFrame
    catalog: StoreCatalog


def _part(value, spec: str) -> str:
    if value is None or pd.isna(value):
        return ""
    return format(int(value) if spec == "d" else float(value), spec)


def revenue_key(store: str, sale_date: str, hour, code, quantity, net: float) -> str:
    basis = "|".join(
        [
            store,
            sale_date,
            _part(hour, "d"),
            _part(code, "d"),
            _part(quantity, ".3f"),
            f"{float(net):.2f}",
        ]
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def build_catalog(mapping: pd.DataFrame | None, settings: RevenueSettings) -> StoreCatalog:
    if mapping is None:
        return StoreCatalog(
            settings.store_aliases,
            ignored=settings.ignored_stores,
            exclude_patterns=settings.exclude_store_patterns,
        )
    return StoreCatalog.from_mapping_frame(
        mapping,
        MAPPING_RAW,
        MAPPING_CANONICAL,
        extra_aliases=settings.store_aliases,
        ignored=settings.ignored_stores,
        exclude_patterns=settings.exclude_store_patterns,
    )


def read_revenue_workbook(path, settings: RevenueSettings) -> RevenueWorkbook:
    workbook = pd.ExcelFile(path)
    sheet = pick_sheet(workbook.sheet_names, [settings.sheet])
    if sheet is None:
        raise ValueError(f"Aba '{settings.sheet}' não encontrada em {path}.")
    frame = pd.read_excel(path, sheet_name=sheet)
    frame.columns = [" ".join(str(column).split()) for column in frame.columns]
    mapping_sheet = pick_sheet(workbook.sheet_names, [settings.store_mapping_sheet])
    mapping = pd.read_excel(path, sheet_name=mapping_sheet) if mapping_sheet else None
    return RevenueWorkbook(frame=frame, catalog=build_catalog(mapping, settings))


def normalize_revenue(
    frame: pd.DataFrame,
    catalog: StoreCatalog,
    settings: RevenueSettings,
    *,
    today: date | None = None,
) -> tuple[pd.DataFrame, RevenueLoadStats]:
    frame = frame.copy()
    frame.columns = [" ".join(str(column).split()) for column in frame.columns]
    columns = {
        name: optional_column(frame, candidates) for name, candidates in REVENUE_COLUMNS.items()
    }
    missing = [name for name in REQUIRED if columns[name] is None]
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes na planilha de faturamento: {missing}")

    rows_in = len(frame)
    keep = pd.Series(True, index=frame.index)

    excluded_clients = 0
    if columns["client"] and settings.excluded_clients:
        blocked = {compact_key(client) for client in settings.excluded_clients}
        client_mask = frame[columns["client"]].map(compact_key).isin(blocked)
        excluded_clients = int(client_mask.sum())
        keep &= ~client_mask

    excluded_codes = 0
    codes = None
    if columns["operation_code"]:
        codes = frame[columns["operation_code"]].map(to_int)
        code_mask = codes.isin(list(settings.allowed_operation_codes))
        excluded_codes = int((keep & ~code_mask).sum())
        keep &= code_mask

    raw_store = frame[columns["store"]].map(clean_text)
    resolved = raw_store.map(catalog.resolve)
    store_mask = resolved.notna()
    excluded_stores = int((keep & ~store_mask).sum())
    keep &= store_mask

    unmapped = sorted({name for name in raw_store[keep] if name and not catalog.is_mapped(name)})
    suspects, new_stores = catalog.detect_renames(unmapped)

    sale_date, date_stats = parse_mixed_dates(frame[columns["sale_date"]])
    future = future_mask(sale_date, 0, today=today)
    future_dropped = int((keep & future).sum())
    keep &= ~future & sale_date.notna()

    net = frame[columns["net"]].map(to_float)
    keep &= net.notna()

    out = pd.DataFrame(index=frame.index)
    out["store"] = resolved
    out["sale_date"] = sale_date.dt.strftime("%Y-%m-%d")
    out["hour"] = frame[columns["hour"]].map(to_int) if columns["hour"] else None
    out["operation_code"] = codes if codes is not None else None
    out["quantity"] = frame[columns["quantity"]].map(to_float) if columns["quantity"] else None
    out["gross"] = frame[columns["gross"]].map(to_float) if columns["gross"] else None
    out["discount"] = frame[columns["discount"]].map(to_float) if columns["discount"] else None
    out["net"] = net
    if columns["weekday"]:
        out["weekday"] = frame[columns["weekday"]].map(clean_text)
    else:
        out["weekday"] = sale_date.map(lambda v: WEEKDAYS_PT[v.weekday()] if not pd.isna(v) else "")
    out = out[keep].copy()

    out["revenue_key"] = [
        revenue_key(row.store, row.sale_date, row.hour, row.operation_code, row.quantity, row.net)
        for row in out.itertuples(index=False)
    ]
    before = len(out)
    out = out.drop_duplicates(subset="revenue_key", keep="first")
    stats = RevenueLoadStats(
        rows_in=rows_in,
        excluded_clients=excluded_clients,
        excluded_codes=excluded_codes,
        excluded_stores=excluded_stores,
        future_dropped=future_dropped,
        duplicates=before - len(out),
        rows_out=len(out),
        rename_suspects=tuple(suspects),
        new_stores=tuple(new_stores),
        date_stats=date_stats,
    )
    return out[REVENUE_OUTPUT].reset_index(drop=True), stats
