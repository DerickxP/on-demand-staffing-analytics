from __future__ import annotations

import pandas as pd
import pytest

from staffing_analytics.etl.consolidate import ConsolidationError, consolidate_workbooks
from tests.helpers import booking_row, write_workbook


def test_consolidation_removes_exact_duplicates_and_reports_conflicts(tmp_path):
    first = pd.DataFrame(
        [booking_row(), booking_row(**{"Ref Agendamento": "AG-2", "Nome": "Bia Lima"})]
    )
    second = pd.DataFrame(
        [
            booking_row(),  # duplicata exata do primeiro arquivo
            booking_row(
                **{"Ref Agendamento": "AG-2", "Nome": "Bia Lima", "Status": "CANCELADO"}
            ),  # conflito
            booking_row(**{"Ref Agendamento": None, "Nome": "Caio Melo"}),  # sem referência
        ]
    )
    mapping = pd.DataFrame([{"Loja Sistema": "Unidade Centro", "Loja": "Loja Centro"}])
    write_workbook(tmp_path / "in" / "01_jul.xlsx", {"BD": first, "MapeamentoLojas": mapping})
    write_workbook(tmp_path / "in" / "02_ago.xlsx", {"BD": second})
    output = tmp_path / "out" / "consolidado.xlsx"

    result = consolidate_workbooks(
        tmp_path / "in", output, carry_sheets=("MapeamentoLojas", "QuadroCLT")
    )

    assert result.files == 2
    assert result.rows_in == 5
    assert result.exact_duplicates == 1
    assert result.rows_out == 4
    assert result.conflicting_keys == ("AG-2",)
    assert result.per_file == {"01_jul.xlsx": 2, "02_ago.xlsx": 2}
    sheets = pd.ExcelFile(output).sheet_names
    assert sheets == ["BD", "Resumo", "CONFLITOS", "MapeamentoLojas"]
    assert len(pd.read_excel(output, sheet_name="CONFLITOS")) == 2


def test_consolidation_fails_when_a_file_contributes_nothing(tmp_path):
    rows = pd.DataFrame([booking_row()])
    write_workbook(tmp_path / "in" / "a.xlsx", {"BD": rows})
    write_workbook(tmp_path / "in" / "b.xlsx", {"BD": rows})  # 100% duplicado
    with pytest.raises(ConsolidationError, match="sem nenhuma linha"):
        consolidate_workbooks(tmp_path / "in", tmp_path / "out.xlsx")
    assert not (tmp_path / "out.xlsx").exists()


def test_consolidation_requires_all_columns(tmp_path):
    frame = pd.DataFrame([booking_row()]).drop(columns=["Valor"])
    write_workbook(tmp_path / "in" / "a.xlsx", {"BD": frame})
    with pytest.raises(ConsolidationError, match="Valor"):
        consolidate_workbooks(tmp_path / "in", tmp_path / "out.xlsx")
