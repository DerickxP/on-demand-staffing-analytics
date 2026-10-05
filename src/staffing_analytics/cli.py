"""Interface de linha de comando.

Cada etapa é um subcomando para poder ser executada e depurada isoladamente::

    consolidate    une várias planilhas de agendamentos em uma, com validações
    load-bookings  carrega os agendamentos (e o quadro fixo por loja) no SQLite
    load-revenue   carrega o faturamento exportado do ERP no SQLite
    dashboard      gera o dashboard HTML a partir do banco
    report         imprime custo por loja, participação na receita e risco de recorrência
    pipeline       executa consolidate -> load-bookings -> load-revenue -> dashboard
    demo           gera dados sintéticos e roda o pipeline inteiro
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from staffing_analytics import __version__
from staffing_analytics.config import ConfigError, Settings, load_settings

log = logging.getLogger("staffing_analytics")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ----------------------------------------------------------------------------- etapas


def run_consolidate(settings: Settings, input_dir: Path, output: Path) -> None:
    from staffing_analytics.etl.consolidate import consolidate_workbooks

    result = consolidate_workbooks(
        input_dir,
        output,
        sheet=settings.bookings.sheet,
        carry_sheets=(settings.bookings.store_mapping_sheet, settings.bookings.headcount_sheet),
    )
    log.info(
        "Consolidação: %d arquivo(s), %d linha(s) lidas, %d gravadas, %d duplicata(s) exata(s), "
        "%d referência(s) em conflito -> %s",
        result.files,
        result.rows_in,
        result.rows_out,
        result.exact_duplicates,
        len(result.conflicting_keys),
        result.output,
    )


def run_load_bookings(settings: Settings, workbook: Path, db: Path) -> None:
    from staffing_analytics.etl.load import load_bookings

    result = load_bookings(workbook, db, settings.bookings)
    stats = result.stats
    log.info(
        "Agendamentos: %d linha(s) lidas, %d fora de lojas excluídas, %d com data futura "
        "descartadas, %d válidas, %d nova(s) no banco; quadro fixo: %d loja(s)",
        stats.rows_in,
        stats.excluded_stores,
        stats.future_dropped,
        stats.rows_out,
        result.inserted,
        result.headcount_stores,
    )
    if stats.date_stats.lost:
        log.warning(
            "%d data(s) não puderam ser convertidas e viraram vazio.", stats.date_stats.lost
        )


def run_load_revenue(settings: Settings, workbook: Path, db: Path) -> None:
    from staffing_analytics.etl.load import load_revenue

    result = load_revenue(workbook, db, settings.revenue)
    stats = result.stats
    log.info(
        "Faturamento: %d linha(s) lidas, %d de clientes excluídos, %d de operações fora da "
        "lista, %d de lojas excluídas, %d com data futura, %d válidas, %d nova(s) no banco",
        stats.rows_in,
        stats.excluded_clients,
        stats.excluded_codes,
        stats.excluded_stores,
        stats.future_dropped,
        stats.rows_out,
        result.inserted,
    )
    if result.consolidated or result.removed:
        log.info(
            "Catálogo de lojas aplicado ao banco: %d linha(s) consolidadas, %d removidas",
            result.consolidated,
            result.removed,
        )
    for suspect in stats.rename_suspects:
        log.warning(
            "Loja '%s' parece ser a loja %s renomeada (já cadastrada como %s). "
            "Adicione um apelido em 'revenue.store_aliases'.",
            suspect.raw_name,
            suspect.code,
            ", ".join(suspect.known_names),
        )
    for name in stats.new_stores:
        log.warning("Loja sem correspondência no mapeamento (possível loja nova): '%s'", name)


def run_dashboard(settings: Settings, db: Path, output: Path) -> None:
    from staffing_analytics.analytics.export import build_dashboard

    result = build_dashboard(db, output, settings)
    log.info(
        "Dashboard gerado: %s (%d agendamentos, %d linhas de faturamento)",
        result.output,
        result.bookings,
        result.revenue_rows,
    )


def run_report(settings: Settings, db: Path) -> None:
    from staffing_analytics.analytics.report import render_report

    print(render_report(db, settings.labor))


# --------------------------------------------------------------------------- comandos


def cmd_init_db(settings: Settings, args: argparse.Namespace) -> int:
    from staffing_analytics.etl.schema import init_db

    db = Path(args.db) if args.db else settings.paths.database
    init_db(db)
    log.info("Banco pronto em %s", db)
    return 0


def cmd_consolidate(settings: Settings, args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir) if args.input_dir else settings.paths.bookings_dir
    output = Path(args.output) if args.output else settings.paths.consolidated_workbook
    run_consolidate(settings, input_dir, output)
    return 0


def cmd_load_bookings(settings: Settings, args: argparse.Namespace) -> int:
    workbook = Path(args.workbook) if args.workbook else settings.paths.bookings_workbook
    run_load_bookings(settings, workbook, Path(args.db) if args.db else settings.paths.database)
    return 0


def cmd_load_revenue(settings: Settings, args: argparse.Namespace) -> int:
    workbook = Path(args.workbook) if args.workbook else settings.paths.revenue_workbook
    run_load_revenue(settings, workbook, Path(args.db) if args.db else settings.paths.database)
    return 0


def cmd_dashboard(settings: Settings, args: argparse.Namespace) -> int:
    db = Path(args.db) if args.db else settings.paths.database
    output = Path(args.output) if args.output else settings.paths.dashboard
    run_dashboard(settings, db, output)
    return 0


def cmd_report(settings: Settings, args: argparse.Namespace) -> int:
    run_report(settings, Path(args.db) if args.db else settings.paths.database)
    return 0


def cmd_pipeline(settings: Settings, args: argparse.Namespace) -> int:
    paths = settings.paths
    bookings_workbook = paths.bookings_workbook
    if args.skip_consolidate:
        log.info("Consolidação pulada (--skip-consolidate).")
    elif paths.bookings_dir.is_dir():
        run_consolidate(settings, paths.bookings_dir, paths.consolidated_workbook)
        bookings_workbook = paths.consolidated_workbook
    else:
        log.info(
            "Pasta %s não existe; usando %s diretamente.", paths.bookings_dir, bookings_workbook
        )

    run_load_bookings(settings, bookings_workbook, paths.database)
    if paths.revenue_workbook.exists():
        run_load_revenue(settings, paths.revenue_workbook, paths.database)
    else:
        log.warning(
            "Planilha de faturamento não encontrada (%s). O dashboard sai sem receita.",
            paths.revenue_workbook,
        )
    run_dashboard(settings, paths.database, paths.dashboard)
    return 0


def cmd_demo(_settings: Settings | None, args: argparse.Namespace) -> int:
    from staffing_analytics.config import DashboardSettings, default_settings
    from staffing_analytics.demo.synthetic import generate_demo_dataset

    output_dir = Path(args.output_dir).resolve()
    base = default_settings(output_dir)
    settings = Settings(
        base_dir=base.base_dir,
        paths=base.paths,
        bookings=base.bookings,
        revenue=base.revenue,
        labor=base.labor,
        dashboard=DashboardSettings(
            subtitle="Custo de prestadores versus faturamento por loja (dados sintéticos)",
            brand="Demo",
        ),
    )
    dataset = generate_demo_dataset(
        settings,
        seed=args.seed,
        months=args.months,
        workers=args.workers,
        bookings_per_month=args.bookings_per_month,
    )
    settings = dataset.settings
    log.info(
        "Dados sintéticos: %d planilha(s) de agendamento, %d prestador(es), %d agendamento(s), "
        "%d linha(s) de faturamento",
        len(dataset.booking_files),
        dataset.workers,
        dataset.bookings,
        dataset.revenue_rows,
    )
    run_consolidate(settings, settings.paths.bookings_dir, settings.paths.consolidated_workbook)
    run_load_bookings(settings, settings.paths.consolidated_workbook, settings.paths.database)
    run_load_revenue(settings, settings.paths.revenue_workbook, settings.paths.database)
    run_dashboard(settings, settings.paths.database, settings.paths.dashboard)
    run_report(settings, settings.paths.database)
    log.info("Abra %s no navegador.", settings.paths.dashboard)
    return 0


# ------------------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="staffing-analytics",
        description="Custo de mão de obra sob demanda versus faturamento por loja.",
    )
    parser.add_argument("--config", help="caminho do config.json (padrão: ./config.json)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log detalhado")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db", help="cria o banco SQLite e as tabelas")
    p.add_argument("--db")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("consolidate", help="une as planilhas de agendamentos de uma pasta")
    p.add_argument("--input-dir")
    p.add_argument("--output")
    p.set_defaults(func=cmd_consolidate)

    p = sub.add_parser("load-bookings", help="carrega agendamentos e quadro fixo no banco")
    p.add_argument("--workbook")
    p.add_argument("--db")
    p.set_defaults(func=cmd_load_bookings)

    p = sub.add_parser("load-revenue", help="carrega o faturamento do ERP no banco")
    p.add_argument("--workbook")
    p.add_argument("--db")
    p.set_defaults(func=cmd_load_revenue)

    p = sub.add_parser("dashboard", help="gera o dashboard HTML")
    p.add_argument("--db")
    p.add_argument("--output")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("report", help="imprime um resumo no terminal")
    p.add_argument("--db")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("pipeline", help="executa todas as etapas em sequência")
    p.add_argument("--skip-consolidate", action="store_true")
    p.set_defaults(func=cmd_pipeline)

    p = sub.add_parser("demo", help="gera dados sintéticos e roda o pipeline completo")
    p.add_argument("--output-dir", default="demo_output")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--workers", type=int, default=60)
    p.add_argument("--bookings-per-month", type=int, default=400)
    p.set_defaults(func=cmd_demo, needs_config=False)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    settings: Settings | None = None
    if getattr(args, "needs_config", True):
        try:
            settings = load_settings(args.config)
        except ConfigError as exc:
            parser.error(str(exc))

    try:
        return int(args.func(settings, args))
    except KeyboardInterrupt:
        log.warning("Interrompido pelo usuário.")
        return 130
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
