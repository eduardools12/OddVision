"""CLI do pipeline: `python -m oddvision.pipeline <comando>`.

Comandos disponíveis: `ingest`. Os demais (init-db, load, check, all) entram nos Passos 4 a 9.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from oddvision.config import PROJECT_ROOT, ConfigError, load_selection, manifest_path, raw_dir, selection_path
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


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path = PROJECT_ROOT,
    download: Callable[[str], bytes] = http_download,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m oddvision.pipeline", description="Pipeline do OddVision.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ingest", help="baixa os JSONs brutos do StatsBomb para data/raw/ e gera o manifest")

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _cmd_ingest(root, download)
    raise AssertionError(f"comando não tratado: {args.command}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
