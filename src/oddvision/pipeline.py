"""CLI do pipeline: `python -m oddvision.pipeline <comando>`.

Comandos disponíveis: `ingest` e `init-db`. Os demais (load, check, all) entram nos Passos 5 a 9.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from oddvision.config import (
    PROJECT_ROOT,
    ConfigError,
    database_config_path,
    ddl_dir,
    load_selection,
    manifest_path,
    raw_dir,
    selection_path,
)
from oddvision.db import apply_ddl, core_table_names, ddl_files, load_database_config, make_engine
from oddvision.ingest import IngestError, http_download, run_ingest


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
    except SQLAlchemyError as exc:
        reason = " ".join(str(getattr(exc, "orig", exc)).split())[:300]  # a senha nunca faz parte dessa mensagem
        print(
            f"erro: não foi possível aplicar o DDL no banco {config.main_db} "
            f"({config.host}:{config.port}, usuário {config.user}): {reason}",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()

    print(f"banco: {config.main_db} em {config.host}:{config.port} (usuário {config.user})")
    print(f"DDL aplicado: {', '.join(applied)}")
    print(f"core: {len(tables)} tabelas")
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

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _cmd_ingest(root, download)
    if args.command == "init-db":
        return _cmd_init_db(root)
    raise AssertionError(f"comando não tratado: {args.command}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
