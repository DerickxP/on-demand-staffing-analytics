"""Catálogo de lojas: apelidos, exclusões e detecção de renomeações.

O ERP identifica lojas por um nome que começa com o número da loja ("03.LJ SUL"). Quando
o cadastro é renomeado ("03.SUL NOVO"), o nome novo não está no mapeamento e a loja
aparece duplicada no dashboard: o histórico antigo com um nome, o mês novo com outro.
O catálogo resolve apelidos e, para nomes desconhecidos, avisa quando o número da loja já
existe no cadastro, que é o sinal quase certo de renomeação.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import pandas as pd

from staffing_analytics.etl.text import clean_text, compact_key, find_column, strip_accents


@dataclass(frozen=True)
class RenameSuspect:
    raw_name: str
    code: str
    known_names: tuple[str, ...]


def store_code(name: str) -> str | None:
    """Número da loja no prefixo do nome ("03.LJ SUL" -> "3"). ``None`` se não houver."""
    match = re.match(r"\s*(\d+)", clean_text(name))
    if not match:
        return None
    return match.group(1).lstrip("0") or "0"


class StoreCatalog:
    def __init__(
        self,
        aliases: Mapping[str, str] | None = None,
        *,
        ignored: Iterable[str] = (),
        exclude_patterns: Iterable[str] = (),
    ) -> None:
        self._aliases = {
            compact_key(raw): clean_text(canonical) for raw, canonical in (aliases or {}).items()
        }
        self._raw_names = {compact_key(raw): clean_text(raw) for raw in (aliases or {})}
        self._ignored = {compact_key(name) for name in ignored if clean_text(name)}
        self._patterns = [
            strip_accents(clean_text(p)).upper() for p in exclude_patterns if clean_text(p)
        ]

    @classmethod
    def from_mapping_frame(
        cls,
        frame: pd.DataFrame,
        raw_candidates: Iterable[str],
        canonical_candidates: Iterable[str],
        *,
        extra_aliases: Mapping[str, str] | None = None,
        ignored: Iterable[str] = (),
        exclude_patterns: Iterable[str] = (),
    ) -> StoreCatalog:
        raw_column = find_column(frame, raw_candidates)
        canonical_column = find_column(frame, canonical_candidates)
        aliases: dict[str, str] = {}
        for raw, canonical in zip(frame[raw_column], frame[canonical_column], strict=True):
            if clean_text(raw) and clean_text(canonical):
                aliases.setdefault(clean_text(raw), clean_text(canonical))
        aliases.update(extra_aliases or {})
        return cls(aliases, ignored=ignored, exclude_patterns=exclude_patterns)

    @property
    def canonical_names(self) -> set[str]:
        return set(self._aliases.values())

    @property
    def raw_names(self) -> tuple[str, ...]:
        return tuple(self._raw_names.values())

    def is_ignored(self, name: str) -> bool:
        text = clean_text(name)
        if not text:
            return True
        if compact_key(text) in self._ignored:
            return True
        upper = strip_accents(text).upper()
        return any(pattern in upper for pattern in self._patterns)

    def is_mapped(self, name: str) -> bool:
        return compact_key(name) in self._aliases

    def resolve(self, name: str) -> str | None:
        """Nome canônico da loja; ``None`` quando a loja deve ficar de fora."""
        if self.is_ignored(name):
            return None
        return self._aliases.get(compact_key(name), clean_text(name))

    def detect_renames(
        self, unmapped_names: Iterable[str]
    ) -> tuple[list[RenameSuspect], list[str]]:
        """Separa nomes desconhecidos em prováveis renomeações e lojas realmente novas."""
        known_by_code: dict[str, list[str]] = {}
        for raw in self._raw_names.values():
            code = store_code(raw)
            if code:
                known_by_code.setdefault(code, []).append(raw)
        suspects: list[RenameSuspect] = []
        new_stores: list[str] = []
        for name in unmapped_names:
            code = store_code(name)
            if code and code in known_by_code:
                suspects.append(RenameSuspect(clean_text(name), code, tuple(known_by_code[code])))
            else:
                new_stores.append(clean_text(name))
        return suspects, new_stores
