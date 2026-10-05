from __future__ import annotations

from datetime import date

import pandas as pd

from staffing_analytics.config import RevenueSettings
from staffing_analytics.etl.revenue import build_catalog, normalize_revenue
from tests.helpers import REVENUE_MAPPING, revenue_row

SETTINGS = RevenueSettings(
    sales_operation_codes=(100, 101),
    return_operation_codes=(190,),
    excluded_clients=("CONSUMIDOR FINAL - AUTOATENDIMENTO",),
    exclude_store_patterns=("BALCAO",),
    ignored_stores=("99.GALPAO",),
    store_aliases={"03.LJ SUL NOVO": "Loja Sul"},
)


def test_normalize_revenue_filters_and_resolves_stores():
    frame = pd.DataFrame(
        [
            revenue_row(),
            revenue_row(
                **{"CGO": 190, "Valor Bruto": -50.0, "Valor Desconto": 0.0, "Valor Liquido": -50.0}
            ),
            revenue_row(**{"CGO": 300}),  # movimentação interna
            revenue_row(**{"Cliente": "CONSUMIDOR FINAL - AUTOATENDIMENTO"}),
            revenue_row(**{"Empresa": "15.BALCAO"}),
            revenue_row(**{"Empresa": "99.GALPAO"}),
            revenue_row(**{"Empresa": "03.LJ SUL NOVO", "Data": "11/07/2026"}),
            revenue_row(**{"Empresa": "04.LESTE RENOMEADA"}),
            revenue_row(**{"Empresa": "21.LJ NOVA", "Data": "2026-12-25"}),
        ]
    )
    catalog = build_catalog(
        pd.concat(
            [
                REVENUE_MAPPING,
                pd.DataFrame([{"Lojas no Sistema": "04.LJ LESTE", "Lojas no Banco": "Loja Leste"}]),
            ]
        ),
        SETTINGS,
    )
    rows, stats = normalize_revenue(frame, catalog, SETTINGS, today=date(2026, 8, 1))

    assert stats.rows_in == 9
    assert stats.excluded_clients == 1
    assert stats.excluded_codes == 1
    assert stats.excluded_stores == 2
    assert stats.future_dropped == 1
    assert stats.rows_out == 4
    assert sorted(rows.store) == ["04.LESTE RENOMEADA", "Loja Centro", "Loja Centro", "Loja Sul"]
    assert rows[rows.store == "Loja Sul"].iloc[0].sale_date == "2026-07-11"
    assert rows.net.sum() == 980.0 * 3 - 50.0
    assert [s.raw_name for s in stats.rename_suspects] == ["04.LESTE RENOMEADA"]
    assert stats.new_stores == ("21.LJ NOVA",)
    assert rows.revenue_key.is_unique
