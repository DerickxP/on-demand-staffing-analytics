from __future__ import annotations

import pandas as pd

from staffing_analytics.etl.stores import StoreCatalog, store_code


def test_store_code():
    assert store_code("03.LJ SUL") == "3"
    assert store_code(" 010.CD REGIONAL") == "10"
    assert store_code("Loja Centro") is None


def test_catalog_resolves_aliases_ignores_and_patterns():
    catalog = StoreCatalog(
        {"03.LJ SUL": "Loja Sul", "03.LJ SUL NOVO": "Loja Sul"},
        ignored=["99.GALPAO"],
        exclude_patterns=["BALCAO"],
    )
    assert catalog.resolve("03.LJ SUL") == "Loja Sul"
    assert catalog.resolve(" 03.lj sul novo ") == "Loja Sul"
    assert catalog.resolve("99.GALPAO") is None
    assert catalog.resolve("15.BALCÃO") is None
    assert catalog.resolve("Unidade Balcão") is None
    assert catalog.resolve("21.LJ NOVA") == "21.LJ NOVA"
    assert catalog.resolve("") is None
    assert catalog.is_mapped("03.LJ SUL") and not catalog.is_mapped("21.LJ NOVA")
    assert catalog.canonical_names == {"Loja Sul"}


def test_detect_renames_by_store_number_prefix():
    catalog = StoreCatalog({"03.LJ SUL": "Loja Sul", "04.LJ LESTE": "Loja Leste"})
    suspects, new_stores = catalog.detect_renames(["03.SUL RENOMEADA", "21.LJ NOVA", "Sem número"])
    assert len(suspects) == 1
    assert suspects[0].raw_name == "03.SUL RENOMEADA"
    assert suspects[0].code == "3"
    assert suspects[0].known_names == ("03.LJ SUL",)
    assert new_stores == ["21.LJ NOVA", "Sem número"]


def test_catalog_from_mapping_frame_with_extra_aliases():
    frame = pd.DataFrame([{"Lojas no Sistema": "01.LJ CENTRO", "Lojas no Banco": "Loja Centro"}])
    catalog = StoreCatalog.from_mapping_frame(
        frame, ["Lojas no Sistema"], ["Lojas no Banco"], extra_aliases={"01.CENTRO": "Loja Centro"}
    )
    assert catalog.resolve("01.LJ CENTRO") == "Loja Centro"
    assert catalog.resolve("01.CENTRO") == "Loja Centro"
