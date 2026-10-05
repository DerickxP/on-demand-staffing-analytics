"""Gerador de dados sintéticos com "verdade" conhecida.

Produz o que o pipeline recebe na vida real: várias planilhas de agendamentos exportadas
por período (com sobreposição e um conflito de referência), a planilha de mapeamento de
lojas, o quadro de efetivos e o export de faturamento do ERP com tudo o que precisa ser
filtrado (clientes internos, operações que não são venda, balcão, galpão) e uma loja
renomeada no meio do período. O gerador registra quais prestadores têm perfil de alta
recorrência e qual loja foi renomeada, para os testes conferirem o resultado.
"""

from __future__ import annotations

import random
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from staffing_analytics.config import Settings
from staffing_analytics.etl.consolidate import BOOKING_EXPORT_COLUMNS

FIRST_NAMES = (
    "Ana",
    "Bruno",
    "Carla",
    "Daniel",
    "Eduarda",
    "Felipe",
    "Gabriela",
    "Henrique",
    "Isabela",
    "João",
    "Karina",
    "Lucas",
    "Mariana",
    "Nicolas",
    "Olívia",
    "Paulo",
    "Rafaela",
    "Samuel",
    "Tatiana",
    "Vinícius",
    "Yasmin",
    "Caio",
    "Letícia",
    "Marcos",
    "Natália",
    "Otávio",
    "Priscila",
    "Rodrigo",
    "Sofia",
    "Thiago",
)
LAST_NAMES = (
    "Almeida",
    "Andrade",
    "Cardoso",
    "Dias",
    "Esteves",
    "Ferreira",
    "Gomes",
    "Lopes",
    "Machado",
    "Jesus",
    "Lima",
    "Martins",
    "Nascimento",
    "Oliveira",
    "Pereira",
    "Queiroz",
    "Ribeiro",
    "Santos",
    "Teixeira",
    "Vieira",
    "Xavier",
    "Azevedo",
    "Batista",
    "Castro",
    "Duarte",
    "Fonseca",
    "Guimarães",
    "Moraes",
    "Nunes",
    "Rocha",
)

# (nome no ERP, nome na plataforma, nome canônico, peso de faturamento, efetivos)
STORES = (
    ("01.LJ CENTRO", "Unidade Centro", "Loja Centro", 1.6, 5),
    ("02.LJ NORTE", "Unidade Norte", "Loja Norte", 1.2, 4),
    ("03.LJ SUL", "Unidade Sul", "Loja Sul", 1.0, 3),
    ("04.LJ LESTE", "Unidade Leste", "Loja Leste", 0.8, 2),
    ("05.LJ OESTE", "Unidade Oeste", "Loja Oeste", 0.7, 2),
    ("06.LJ SHOPPING", "Unidade Shopping", "Loja Shopping", 1.4, 4),
    ("07.LJ PRAIA", "Unidade Praia", "Loja Praia", 0.6, 1),
    ("08.LJ JARDIM", "Unidade Jardim", "Loja Jardim", 0.9, 0),
)
RENAMED_STORE = ("03.LJ SUL", "03.LJ SUL NOVO", "Loja Sul")
COUNTER_STORE = ("15.BALCAO", "Unidade Balcão")
WAREHOUSE_STORE = "99.GALPAO"
EXCLUDED_CLIENT = "CONSUMIDOR FINAL - AUTOATENDIMENTO"
REGULAR_CLIENT = "CONSUMIDOR FINAL"

ROLES = (
    ("Empacotador", 50, 13.0),
    ("Operador de Caixa", 20, 15.0),
    ("Repositor", 15, 14.0),
    ("Auxiliar de Depósito", 10, 14.5),
    ("Açougueiro", 5, 19.0),
)
SHIFT_STARTS = ((7, 30), (13, 30), (17, 15), (0, 2))  # (hora, peso)
HOUR_REVENUE_WEIGHTS = {
    8: 3,
    9: 5,
    10: 7,
    11: 9,
    12: 8,
    13: 6,
    14: 6,
    15: 7,
    16: 9,
    17: 11,
    18: 12,
    19: 10,
    20: 7,
    21: 4,
}
SALES_CODES = (100, 101, 102, 110)
RETURN_CODE = 190
INTERNAL_CODES = (300, 210)
CANCEL_REASONS = ("Prestador não compareceu", "Loja cancelou", "Reagendado")


@dataclass(frozen=True)
class WorkerProfile:
    name: str
    home_store: str  # nome na plataforma
    second_store: str | None
    role: str
    days_per_week: int  # perfil de recorrência: 1-2 baixo, 3 atenção, 4-5 crítico


@dataclass(frozen=True)
class DemoDataset:
    settings: Settings
    booking_files: tuple[Path, ...]
    bookings: int
    workers: int
    revenue_rows: int
    profiles: tuple[WorkerProfile, ...]
    range_start: date
    range_end: date
    rename_date: date

    @property
    def platform_to_canonical(self) -> dict[str, str]:
        return {platform: canonical for _, platform, canonical, _, _ in STORES}


def _month_starts(months: int, anchor: date) -> list[date]:
    first = anchor.replace(day=1)
    starts: list[date] = []
    for _ in range(months):
        first = (first - timedelta(days=1)).replace(day=1)
        starts.append(first)
    return sorted(starts)


def _month_end(day: date) -> date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def _build_profiles(rng: random.Random, count: int) -> list[WorkerProfile]:
    combos = [(f, s) for f in FIRST_NAMES for s in LAST_NAMES]
    chosen = rng.sample(combos, min(count, len(combos)))
    platform_names = [platform for _, platform, _, _, _ in STORES]
    role_names = [name for name, _, _ in ROLES]
    role_weights = [weight for _, weight, _ in ROLES]
    profiles: list[WorkerProfile] = []
    for first, last in chosen:
        draw = rng.random()
        days = (
            5
            if draw < 0.06
            else 4
            if draw < 0.12
            else 3
            if draw < 0.27
            else rng.choice((1, 1, 2, 2))
        )
        home = rng.choice(platform_names)
        second = (
            rng.choice([s for s in platform_names if s != home]) if rng.random() < 0.3 else None
        )
        profiles.append(
            WorkerProfile(
                name=f"{first} {last}",
                home_store=home,
                second_store=second,
                role=rng.choices(role_names, weights=role_weights)[0],
                days_per_week=days,
            )
        )
    return profiles


def _mixed_date_text(seed: int, moment: datetime):
    """Simula a coluna vinda do Excel: datetime real, texto ISO ou texto brasileiro.

    A escolha é determinística por ``seed`` para que o mesmo agendamento tenha a mesma
    representação em dois exports sobrepostos (e seja reconhecido como duplicata exata).
    """
    bucket = seed % 20
    if bucket < 12:
        return moment
    if bucket < 17:
        return moment.strftime("%Y-%m-%d %H:%M:%S")
    return moment.strftime("%d/%m/%Y %H:%M")


def _generate_bookings(
    rng: random.Random,
    profiles: list[WorkerProfile],
    range_start: date,
    range_end: date,
    target: int,
) -> list[dict]:
    """Uma escala semanal por prestador, calibrada para chegar perto de ``target`` agendamentos."""
    weeks: list[date] = []
    cursor = range_start - timedelta(days=range_start.weekday())
    while cursor <= range_end:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    expected = sum(p.days_per_week for p in profiles) * len(weeks)
    keep_ratio = min(1.0, target / expected) if expected else 1.0
    rates = {name: rate for name, _, rate in ROLES}
    starts = [h for h, _ in SHIFT_STARTS]
    start_weights = [w for _, w in SHIFT_STARTS]

    rows: list[dict] = []
    ref = 100000
    for week_start in weeks:
        for profile in profiles:
            days = rng.sample(range(7), profile.days_per_week)
            for day_offset in days:
                if rng.random() > keep_ratio:
                    continue
                day = week_start + timedelta(days=day_offset)
                if day < range_start or day > range_end:
                    continue
                hour = rng.choices(starts, weights=start_weights)[0]
                start = datetime(day.year, day.month, day.day, hour, rng.choice((0, 15, 30)))
                duration = rng.choice((4.0, 5.0, 6.0, 6.0, 8.0))
                cancelled = rng.random() < 0.07
                store = (
                    profile.home_store
                    if rng.random() < 0.8 or not profile.second_store
                    else profile.second_store
                )
                cost = (
                    0.0
                    if cancelled
                    else round(duration * rates[profile.role] * rng.uniform(0.95, 1.08), 2)
                )
                ref += 1
                rows.append(
                    {
                        "Nome": profile.name,
                        "Estado": "SP",
                        "Loja": store,
                        "Vaga": profile.role,
                        "Início": start,
                        "Término": start + timedelta(hours=duration),
                        "Ref Agendamento": f"AG-{ref}",
                        "Agendado em": start - timedelta(days=rng.randint(1, 6)),
                        "Iniciado em": None
                        if cancelled
                        else start + timedelta(minutes=rng.randint(-5, 12)),
                        "Concluido em": None
                        if cancelled
                        else start + timedelta(hours=duration, minutes=rng.randint(-10, 20)),
                        "Valor": cost,
                        "Fração de hora computada": 0.0 if cancelled else duration,
                        "Status": "CANCELADO" if cancelled else "FINALIZADO",
                        "Data do cancelamento": start - timedelta(hours=rng.randint(2, 30))
                        if cancelled
                        else None,
                        "Motivo": rng.choice(CANCEL_REASONS) if cancelled else None,
                        "Responsável pelo cancelamento": rng.choice(("Loja", "Prestador"))
                        if cancelled
                        else None,
                    }
                )
    rows.sort(key=lambda r: r["Início"])
    return rows


def _write_booking_exports(
    rows: list[dict],
    month_starts: list[date],
    directory: Path,
    platform_mapping: pd.DataFrame,
    headcount: pd.DataFrame,
) -> list[Path]:
    """Um arquivo por mês, incluindo os 3 últimos dias do mês anterior (sobreposição real)."""
    directory.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    conflict_injected = False
    for month_start in month_starts:
        window_start = datetime.combine(month_start - timedelta(days=3), datetime.min.time())
        window_end = datetime.combine(_month_end(month_start), datetime.max.time())
        subset = [dict(r) for r in rows if window_start <= r["Início"] <= window_end]
        if subset and not conflict_injected and month_start != month_starts[0]:
            # mesma referência com status diferente entre dois exports: vai para a aba CONFLITOS
            clone = dict(subset[0])
            clone["Status"] = "AGENDADO"
            clone["Valor"] = 0.0
            subset.append(clone)
            conflict_injected = True
        frame = pd.DataFrame(subset, columns=list(BOOKING_EXPORT_COLUMNS))
        for offset, column in enumerate(("Início", "Término", "Agendado em")):
            frame[column] = [
                _mixed_date_text(int(str(ref).split("-")[-1]) + offset * 7, value)
                if isinstance(value, datetime)
                else value
                for ref, value in zip(frame["Ref Agendamento"], frame[column], strict=True)
            ]
        path = directory / f"agendamentos_{month_start:%Y_%m}.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="BD", index=False)
            platform_mapping.to_excel(writer, sheet_name="MapeamentoLojas", index=False)
            headcount.to_excel(writer, sheet_name="QuadroCLT", index=False)
        files.append(path)
    return files


def _generate_revenue(
    rng: random.Random, range_start: date, range_end: date, rename_date: date
) -> tuple[list[dict], pd.DataFrame]:
    rows: list[dict] = []
    weekdays = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")
    day = range_start
    while day <= range_end:
        weekday_factor = 1.35 if day.weekday() >= 5 else 1.0
        for erp_name, _, _, weight, _ in STORES:
            store_name = erp_name
            if erp_name == RENAMED_STORE[0] and day >= rename_date:
                store_name = RENAMED_STORE[1]
            for hour, hour_weight in HOUR_REVENUE_WEIGHTS.items():
                gross = round(weight * hour_weight * weekday_factor * rng.uniform(180, 260), 2)
                discount = round(gross * rng.uniform(0.0, 0.04), 2)
                rows.append(
                    _revenue_row(
                        store_name,
                        day,
                        weekdays[day.weekday()],
                        hour,
                        rng.choice(SALES_CODES),
                        rng.randint(20, 90),
                        gross,
                        discount,
                        REGULAR_CLIENT,
                    )
                )
                if rng.random() < 0.08:  # devolução: valor negativo, entra para subtrair
                    value = -round(gross * rng.uniform(0.02, 0.1), 2)
                    rows.append(
                        _revenue_row(
                            store_name,
                            day,
                            weekdays[day.weekday()],
                            hour,
                            RETURN_CODE,
                            1,
                            value,
                            0.0,
                            REGULAR_CLIENT,
                        )
                    )
                if rng.random() < 0.05:  # movimentação interna: fora da lista de vendas
                    rows.append(
                        _revenue_row(
                            store_name,
                            day,
                            weekdays[day.weekday()],
                            hour,
                            rng.choice(INTERNAL_CODES),
                            5,
                            400.0,
                            0.0,
                            REGULAR_CLIENT,
                        )
                    )
                if rng.random() < 0.05:  # cliente interno excluído por configuração
                    rows.append(
                        _revenue_row(
                            store_name,
                            day,
                            weekdays[day.weekday()],
                            hour,
                            SALES_CODES[0],
                            3,
                            120.0,
                            0.0,
                            EXCLUDED_CLIENT,
                        )
                    )
        rows.append(
            _revenue_row(
                COUNTER_STORE[0],
                day,
                weekdays[day.weekday()],
                10,
                SALES_CODES[0],
                400,
                9000.0,
                0.0,
                REGULAR_CLIENT,
            )
        )
        if day.day == 1:
            rows.append(
                _revenue_row(
                    WAREHOUSE_STORE,
                    day,
                    weekdays[day.weekday()],
                    9,
                    SALES_CODES[0],
                    1,
                    50.0,
                    0.0,
                    REGULAR_CLIENT,
                )
            )
        day += timedelta(days=1)
    for index, row in enumerate(rows):
        row["Data"] = _mixed_date_text(index, datetime.combine(row["Data"], datetime.min.time()))
    mapping = pd.DataFrame(
        [
            {"Lojas no Sistema": erp, "Lojas no Banco": canonical}
            for erp, _, canonical, _, _ in STORES
        ]
        + [{"Lojas no Sistema": COUNTER_STORE[0], "Lojas no Banco": "Balcão"}]
    )
    return rows, mapping


def _revenue_row(store, day, weekday, hour, code, quantity, gross, discount, client) -> dict:
    return {
        "Empresa": store,
        "Cliente": client,
        "Data": day,
        "Dia da Semana": weekday,
        "Hora do Dia": hour,
        "CGO": code,
        "Quantidade": quantity,
        "Valor Bruto": gross,
        "Valor Desconto": discount,
        "Valor Liquido": round(gross - discount, 2),
    }


def generate_demo_dataset(
    settings: Settings,
    *,
    seed: int = 42,
    months: int = 6,
    workers: int = 60,
    bookings_per_month: int = 400,
    anchor: date | None = None,
) -> DemoDataset:
    rng = random.Random(seed)
    month_starts = _month_starts(max(months, 1), anchor or date.today())
    range_start, range_end = month_starts[0], _month_end(month_starts[-1])
    rename_date = (
        month_starts[len(month_starts) // 2]
        if len(month_starts) > 1
        else range_end + timedelta(days=1)
    )

    profiles = _build_profiles(rng, workers)
    bookings = _generate_bookings(
        rng, profiles, range_start, range_end, bookings_per_month * max(months, 1)
    )
    platform_mapping = pd.DataFrame(
        [{"Loja Sistema": platform, "Loja": canonical} for _, platform, canonical, _, _ in STORES]
        + [{"Loja Sistema": COUNTER_STORE[1], "Loja": "Balcão"}]
    )
    headcount = pd.DataFrame(
        [{"Loja": canonical, "Efetivos": count} for _, _, canonical, _, count in STORES]
    )
    # alguns agendamentos no balcão, que o filtro de padrões deve descartar
    for row in bookings[::97]:
        row["Loja"] = COUNTER_STORE[1]

    paths = settings.paths
    files = _write_booking_exports(
        bookings, month_starts, paths.bookings_dir, platform_mapping, headcount
    )

    revenue_rows, revenue_mapping = _generate_revenue(rng, range_start, range_end, rename_date)
    paths.revenue_workbook.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(paths.revenue_workbook, engine="openpyxl") as writer:
        pd.DataFrame(revenue_rows).to_excel(writer, sheet_name="BD", index=False)
        revenue_mapping.to_excel(writer, sheet_name="Lojas", index=False)

    revenue_settings = replace(
        settings.revenue,
        sales_operation_codes=SALES_CODES,
        return_operation_codes=(RETURN_CODE,),
        excluded_clients=(EXCLUDED_CLIENT,),
        exclude_store_patterns=("BALCAO",),
        ignored_stores=(WAREHOUSE_STORE,),
        store_aliases={RENAMED_STORE[1]: RENAMED_STORE[2]},
    )
    effective = replace(settings, revenue=revenue_settings)
    _write_effective_config(effective)
    return DemoDataset(
        settings=effective,
        booking_files=tuple(files),
        bookings=len(
            {(r["Nome"], r["Início"], r["Loja"]) for r in bookings if r["Loja"] != COUNTER_STORE[1]}
        ),
        workers=len(profiles),
        revenue_rows=len(revenue_rows),
        profiles=tuple(profiles),
        range_start=range_start,
        range_end=range_end,
        rename_date=rename_date,
    )


def _write_effective_config(settings: Settings) -> None:
    """Grava o config.json usado pela demo, para o usuário ver as regras aplicadas."""
    import json
    from dataclasses import asdict

    payload = {
        "paths": {key: str(value) for key, value in asdict(settings.paths).items()},
        "bookings": asdict(settings.bookings),
        "revenue": asdict(settings.revenue),
        "labor": asdict(settings.labor),
        "dashboard": {**asdict(settings.dashboard), "logo": None},
    }
    settings.base_dir.mkdir(parents=True, exist_ok=True)
    (settings.base_dir / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
