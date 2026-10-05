from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from staffing_analytics.config import BookingsSettings
from staffing_analytics.etl.bookings import normalize_bookings, read_bookings_workbook
from staffing_analytics.etl.stores import StoreCatalog
from tests.helpers import STORE_MAPPING, booking_row, write_workbook

SETTINGS = BookingsSettings(state="SP", max_future_months=2, exclude_store_patterns=("BALCAO",))
CATALOG = StoreCatalog({"Unidade Centro": "Loja Centro"}, exclude_patterns=("BALCAO",))


def test_normalize_bookings_applies_catalog_dates_and_filters():
    frame = pd.DataFrame(
        [
            booking_row(),
            booking_row(**{"Ref Agendamento": "AG-9", "Loja": "Unidade Balcão"}),
            booking_row(**{"Ref Agendamento": "AG-10", "Início": "2027-05-01 08:00:00"}),
            booking_row(
                **{
                    "Ref Agendamento": None,
                    "Nome": "Bia Lima",
                    "Início": datetime(2026, 7, 11, 9),
                    "Estado": "",
                }
            ),
            booking_row(**{"Ref Agendamento": "AG-1"}),  # mesma pessoa/início/loja: duplicata
        ]
    )
    rows, stats = normalize_bookings(frame, CATALOG, SETTINGS, today=date(2026, 8, 1))

    assert stats.rows_in == 5
    assert stats.excluded_stores == 1
    assert stats.future_dropped == 1
    assert stats.duplicates == 1
    assert stats.rows_out == 2
    ana = rows[rows.worker_name == "Ana Souza"].iloc[0]
    assert ana.store == "Loja Centro"
    assert ana.start_at == "2026-07-10 08:00:00"
    assert ana.cost == 78.0 and ana.computed_hours == 6.0
    assert ana.status == "FINALIZADO"
    bia = rows[rows.worker_name == "Bia Lima"].iloc[0]
    assert bia.state == "SP"  # padrão quando vazio
    assert bia.booking_ref == ""
    assert len(bia.booking_key) == 40 and bia.booking_key != ana.booking_key


def test_read_bookings_workbook_loads_mapping_and_headcount(tmp_path):
    headcount = pd.DataFrame(
        [{"Loja": "Loja Centro", "Efetivos": 4}, {"Loja": "Unidade Balcão", "Efetivos": 9}]
    )
    path = write_workbook(
        tmp_path / "b.xlsx",
        {
            "BD": pd.DataFrame([booking_row()]),
            "MapeamentoLojas": STORE_MAPPING,
            "QuadroCLT": headcount,
        },
    )
    source = read_bookings_workbook(path, SETTINGS)
    assert source.catalog.resolve("Unidade Sul") == "Loja Sul"
    assert source.headcount == {"Loja Centro": 4}
    rows, _ = normalize_bookings(source.frame, source.catalog, SETTINGS, today=date(2026, 8, 1))
    assert rows.iloc[0].store == "Loja Centro"
