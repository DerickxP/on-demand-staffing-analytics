"""Utilitários compartilhados pelos testes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_workbook(path: Path, sheets: dict[str, pd.DataFrame]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return path


def booking_row(**overrides) -> dict:
    row = {
        "Nome": "Ana Souza",
        "Estado": "SP",
        "Loja": "Unidade Centro",
        "Vaga": "Empacotador",
        "Início": "2026-07-10 08:00:00",
        "Término": "2026-07-10 14:00:00",
        "Ref Agendamento": "AG-1",
        "Agendado em": "2026-07-05 10:00:00",
        "Iniciado em": "2026-07-10 08:02:00",
        "Concluido em": "2026-07-10 14:05:00",
        "Valor": 78.0,
        "Fração de hora computada": 6.0,
        "Status": "FINALIZADO",
        "Data do cancelamento": None,
        "Motivo": None,
        "Responsável pelo cancelamento": None,
    }
    row.update(overrides)
    return row


def revenue_row(**overrides) -> dict:
    row = {
        "Empresa": "01.LJ CENTRO",
        "Cliente": "CONSUMIDOR FINAL",
        "Data": "2026-07-10",
        "Dia da Semana": "Sexta",
        "Hora do Dia": 10,
        "CGO": 100,
        "Quantidade": 30,
        "Valor Bruto": 1000.0,
        "Valor Desconto": 20.0,
        "Valor Liquido": 980.0,
    }
    row.update(overrides)
    return row


STORE_MAPPING = pd.DataFrame(
    [
        {"Loja Sistema": "Unidade Centro", "Loja": "Loja Centro"},
        {"Loja Sistema": "Unidade Sul", "Loja": "Loja Sul"},
    ]
)
REVENUE_MAPPING = pd.DataFrame(
    [
        {"Lojas no Sistema": "01.LJ CENTRO", "Lojas no Banco": "Loja Centro"},
        {"Lojas no Sistema": "03.LJ SUL", "Lojas no Banco": "Loja Sul"},
    ]
)
