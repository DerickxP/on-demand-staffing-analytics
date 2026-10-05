from __future__ import annotations

import pandas as pd
import pytest

from staffing_analytics.etl.text import compact_key, find_column, pick_sheet, to_float, to_int


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", 1234.56),
        ("12.5", 12.5),
        (7, 7.0),
        ("R$ -8,10", -8.10),
        ("", None),
        (None, None),
    ],
)
def test_to_float(raw, expected):
    assert to_float(raw) == expected


def test_to_int_and_compact_key():
    assert to_int("3,0") == 3
    assert to_int("x") is None
    assert compact_key(" Loja Sul - 03 ") == "LOJASUL03"
    assert compact_key("Balcão") == "BALCAO"


def test_find_column_and_pick_sheet_ignore_accents_and_case():
    frame = pd.DataFrame(columns=["Início", " Valor Líquido "])
    assert find_column(frame, ["inicio"]) == "Início"
    assert find_column(frame, ["Valor Liquido"]) == " Valor Líquido "
    with pytest.raises(KeyError):
        find_column(frame, ["Nome"])
    assert (
        pick_sheet(["BD", "Mapeamento Lojas"], ["mapeamentolojas", "mapeamento lojas"])
        == "Mapeamento Lojas"
    )
    assert pick_sheet(["BD"], ["Lojas"]) is None
