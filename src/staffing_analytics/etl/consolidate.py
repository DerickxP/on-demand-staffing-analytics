"""Consolidação de várias planilhas de agendamentos em uma única.

A plataforma exporta um arquivo por período. Antes da carga, os arquivos são unidos com
regras conservadoras: só duplicatas exatas são removidas; a mesma referência com dados
diferentes não é descartada, e sim reportada em uma aba de conflitos para revisão. Ao
final, validações garantem que nenhuma linha ou referência se perdeu no caminho. Se uma
validação falha, o arquivo de saída não é gerado.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from staffing_analytics.etl.text import find_column, pick_sheet

log = logging.getLogger(__name__)

BOOKING_EXPORT_COLUMNS: tuple[str, ...] = (
    "Nome",
    "Estado",
    "Loja",
    "Vaga",
    "Início",
    "Término",
    "Ref Agendamento",
    "Agendado em",
    "Iniciado em",
    "Concluido em",
    "Valor",
    "Fração de hora computada",
    "Status",
    "Data do cancelamento",
    "Motivo",
    "Responsável pelo cancelamento",
)
KEY_COLUMN = "Ref Agendamento"
DEFAULT_CARRY_SHEETS = ("MapeamentoLojas", "QuadroCLT")
SOURCE_COLUMN = "Arquivo de origem"


class ConsolidationError(ValueError):
    """Alguma validação falhou; o arquivo consolidado não foi gerado."""


@dataclass
class ConsolidationResult:
    files: int
    rows_in: int
    rows_out: int
    exact_duplicates: int
    conflicting_keys: tuple[str, ...]
    output: Path
    per_file: dict[str, int] = field(default_factory=dict)


def list_workbooks(input_dir: Path, output: Path | None = None) -> list[Path]:
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Pasta de entrada não encontrada: {input_dir}")
    files = []
    for path in sorted(input_dir.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        if output is not None and path.resolve() == Path(output).resolve():
            continue
        files.append(path)
    return files


def read_export(path: Path, *, sheet: str, columns: Sequence[str]) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name=sheet)
    frame.columns = [str(column).strip() for column in frame.columns]
    selected = {}
    for column in columns:
        try:
            selected[column] = frame[find_column(frame, [column])]
        except KeyError as exc:
            raise ConsolidationError(
                f"'{path.name}' não tem a coluna obrigatória '{column}'."
            ) from exc
    out = pd.DataFrame(selected)
    out[SOURCE_COLUMN] = path.name
    return out


def _carry_sheets(files: Sequence[Path], names: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Abas auxiliares (mapeamento de lojas, quadro fixo) do export mais recente que as tiver."""
    carried: dict[str, pd.DataFrame] = {}
    for name in names:
        for path in reversed(files):
            found = pick_sheet(pd.ExcelFile(path).sheet_names, [name])
            if found is not None:
                carried[name] = pd.read_excel(path, sheet_name=found)
                break
    return carried


def consolidate_workbooks(
    input_dir: Path,
    output: Path,
    *,
    sheet: str = "BD",
    columns: Sequence[str] = BOOKING_EXPORT_COLUMNS,
    key: str = KEY_COLUMN,
    carry_sheets: Sequence[str] = DEFAULT_CARRY_SHEETS,
) -> ConsolidationResult:
    output = Path(output)
    files = list_workbooks(input_dir, output)
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo .xlsx encontrado em {input_dir}")

    parts = [read_export(path, sheet=sheet, columns=columns) for path in files]
    combined = pd.concat(parts, ignore_index=True)
    rows_in = len(combined)
    keys_in = set(combined[key].dropna().astype(str))

    empty_keys = int(combined[key].isna().sum())
    if empty_keys:
        log.warning("%d linha(s) sem '%s' foram mantidas.", empty_keys, key)

    final = combined.drop_duplicates(subset=list(columns), keep="first").reset_index(drop=True)
    exact_duplicates = rows_in - len(final)

    conflict_mask = final[key].notna() & final.duplicated(key, keep=False)
    conflicts = final[conflict_mask].sort_values(key)
    conflicting_keys = tuple(sorted(conflicts[key].astype(str).unique()))

    errors: list[str] = []
    if rows_in != len(final) + exact_duplicates:
        errors.append(f"contagem não fecha: {rows_in} != {len(final)} + {exact_duplicates}")
    keys_out = set(final[key].dropna().astype(str))
    if keys_in - keys_out:
        errors.append(f"referências perdidas: {sorted(keys_in - keys_out)[:10]}")
    if final.duplicated(subset=list(columns)).any():
        errors.append("ainda existem linhas exatamente iguais na saída")
    present = set(final[SOURCE_COLUMN])
    missing_files = [path.name for path in files if path.name not in present]
    if missing_files:
        errors.append(f"arquivos sem nenhuma linha na saída: {missing_files}")
    if errors:
        raise ConsolidationError("Validações falharam: " + "; ".join(errors))

    output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        final.to_excel(writer, sheet_name=sheet, index=False)
        summary = (
            final[SOURCE_COLUMN].value_counts().rename_axis("Arquivo").reset_index(name="Linhas")
        )
        summary.loc[len(summary)] = ["TOTAL", len(final)]
        summary.to_excel(writer, sheet_name="Resumo", index=False)
        if len(conflicts):
            conflicts.to_excel(writer, sheet_name="CONFLITOS", index=False)
        for name, frame in _carry_sheets(files, carry_sheets).items():
            frame.to_excel(writer, sheet_name=name, index=False)

    return ConsolidationResult(
        files=len(files),
        rows_in=rows_in,
        rows_out=len(final),
        exact_duplicates=exact_duplicates,
        conflicting_keys=conflicting_keys,
        output=output,
        per_file={path.name: int((final[SOURCE_COLUMN] == path.name).sum()) for path in files},
    )
