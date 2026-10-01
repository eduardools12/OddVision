"""CLI do pipeline: `python -m oddvision.pipeline <comando>`.

Comandos: `ingest` (P1), `init-db`, `load` (P2 a P5: competições, times, partidas, escalações, eventos e eventos
especializados), `check` (P6: checks de qualidade) e `all` (os quatro, em sequência, parando no primeiro que falhar).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from oddvision.checks import format_report, has_errors, run_checks
from oddvision.config import (
    PROJECT_ROOT,
    ConfigError,
    analytics_dir,
    checks_dir,
    database_config_path,
    ddl_dir,
    load_selection,
    manifest_path,
    raw_dir,
    selection_path,
)
from oddvision.db import apply_analytics, apply_ddl, core_table_names, ddl_files, load_database_config, make_engine
from oddvision.ingest import IngestError, http_download, read_manifest, run_ingest
from oddvision.load import LoadError, load_matches, load_p2
from oddvision.transform.common import TransformError


def _cmd_ingest(root: Path, download: Callable[[str], bytes]) -> int:
    try:
        selection = load_selection(selection_path(root))
        result = run_ingest(
            selection,
            raw_dir(root),
            manifest_path(root),
            download=download,
            on_file=lambda action, path: action == "baixado" and print(f"baixado  {path}"),
        )
    except (ConfigError, IngestError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    print(f"{result.downloaded} baixados, {result.existing} existentes ({result.total} arquivos)")
    print(f"manifest: {manifest_path(root).relative_to(root).as_posix()}")
    return 0


def _cmd_init_db(root: Path) -> int:
    """Cria (ou completa) os schemas core e analytics no banco principal. Nunca apaga dados."""
    try:
        config = load_database_config(database_config_path(root))
        ddl_files(ddl_dir(root))  # confere a pasta de DDL antes de tentar conectar
    except ConfigError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    engine = make_engine(config, config.main_db)
    try:
        applied = apply_ddl(engine, ddl_dir(root))
        tables = core_table_names(engine)
        with engine.begin() as conn:  # as views de analytics são recriadas dos arquivos (D29)
            analytics = apply_analytics(conn, analytics_dir(root))
    except SQLAlchemyError as exc:
        print(
            f"erro: não foi possível aplicar o DDL no banco {config.main_db} "
            f"({config.host}:{config.port}, usuário {config.user}): {_database_reason(exc)}",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()

    print(f"banco: {config.main_db} em {config.host}:{config.port} (usuário {config.user})")
    print(f"DDL aplicado: {', '.join(applied)}")
    print(f"core: {len(tables)} tabelas")
    if analytics:
        print(f"analytics: {len(analytics)} arquivo{'' if len(analytics) == 1 else 's'} aplicado{'' if len(analytics) == 1 else 's'}: {', '.join(analytics)}")
    return 0


def _database_reason(exc: SQLAlchemyError) -> str:
    return " ".join(str(getattr(exc, "orig", exc)).split())[:300]  # a senha nunca faz parte dessa mensagem


def _cmd_load(root: Path) -> int:
    """Carrega no core o que foi baixado: competições, times e partidas (P2). Repetível."""
    try:
        selection = load_selection(selection_path(root))
        config = load_database_config(database_config_path(root))
    except ConfigError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    engine = make_engine(config, config.main_db)
    try:
        result = load_p2(engine, selection, raw_dir(root), manifest_path(root))
        lineups = load_matches(engine, selection, raw_dir(root), manifest_path(root))
    except (IngestError, TransformError, LoadError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(
            f"erro: não foi possível carregar no banco {config.main_db} "
            f"({config.host}:{config.port}, usuário {config.user}): {_database_reason(exc)}",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()

    print(f"banco: {config.main_db} em {config.host}:{config.port} (usuário {config.user})")
    print(f"competitions: {result.competitions}, teams: {result.teams}, matches: {result.matches}")
    print(f"ingestion_log: {result.log_files} arquivos registrados")
    for match in lineups.matches:
        print(
            f"lineups: partida {match.match_id}: {match.players} jogadores "
            f"({match.starters} titulares, {match.played} entraram em campo)"
        )
        print(
            f"events: partida {match.match_id}: {match.events} eventos | shots {match.shots}, passes {match.passes}, "
            f"carries {match.carries}, cards {match.cards}, substitutions {match.substitutions}"
        )
    print(f"players: {lineups.players}")
    for conflict in lineups.conflicts:  # não é erro: a regra do valor mais frequente já decidiu
        seen = ", ".join(f"{value!r} em {n}" for value, n in sorted(conflict.counts.items(), key=lambda kv: -kv[1]))
        print(
            f"aviso: jogador {conflict.player_id}: {conflict.attribute} diverge entre arquivos ({seen}); "
            f"gravado {conflict.chosen!r}",
            file=sys.stderr,
        )
    return 0


def _cmd_check(root: Path) -> int:
    """Executa os checks de qualidade e imprime o relatório. Código 1 se algum check de nível `error` falhar."""
    try:
        config = load_database_config(database_config_path(root))
    except ConfigError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    manifest = manifest_path(root)
    # O C11 lê os arquivos brutos de escalação: só roda se a ingestão já aconteceu.
    with_raw = manifest.exists() and any(p.startswith("lineups/") for p in read_manifest(manifest))
    engine = make_engine(config, config.main_db)
    try:
        with engine.connect() as conn:
            results = run_checks(
                conn, checks_dir(root),
                raw_dir=raw_dir(root) if with_raw else None, manifest_path=manifest if with_raw else None,
            )
    except (ConfigError, IngestError, TransformError, LoadError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(
            f"erro: não foi possível executar os checks no banco {config.main_db} "
            f"({config.host}:{config.port}, usuário {config.user}): {_database_reason(exc)}",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()

    print(f"banco: {config.main_db} em {config.host}:{config.port} (usuário {config.user})")
    if not with_raw:
        print("C11   PULADO  sem arquivos brutos de escalação (rode `ingest`)")
    print(format_report(results))
    return 1 if has_errors(results) else 0


def _cmd_all(root: Path, download: Callable[[str], bytes]) -> int:
    """ingest -> init-db -> load -> check. Para no primeiro passo que falhar e devolve o código dele."""
    for name, step in (
        ("ingest", lambda: _cmd_ingest(root, download)),
        ("init-db", lambda: _cmd_init_db(root)),
        ("load", lambda: _cmd_load(root)),
        ("check", lambda: _cmd_check(root)),
    ):
        print(f"\n== {name} ==")
        code = step()
        if code != 0:
            print(f"\n`all` parou em `{name}` (código {code}).", file=sys.stderr)
            return code
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path = PROJECT_ROOT,
    download: Callable[[str], bytes] = http_download,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m oddvision.pipeline", description="Pipeline do OddVision.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ingest", help="baixa os JSONs brutos do StatsBomb para data/raw/ e gera o manifest")
    commands.add_parser("init-db", help="cria os schemas core e analytics no banco principal (repetível; nunca apaga dados)")
    commands.add_parser("load", help="carrega competições, times, partidas, escalações, eventos e eventos especializados (repetível)")
    commands.add_parser("check", help="executa os checks de qualidade; termina com código 1 se algum check de erro falhar")
    commands.add_parser("all", help="ingest + init-db + load + check, parando no primeiro que falhar")

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _cmd_ingest(root, download)
    if args.command == "init-db":
        return _cmd_init_db(root)
    if args.command == "load":
        return _cmd_load(root)
    if args.command == "check":
        return _cmd_check(root)
    if args.command == "all":
        return _cmd_all(root, download)
    raise AssertionError(f"comando não tratado: {args.command}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
