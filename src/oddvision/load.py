"""Carga no schema core (P2 em diante).

Duas ideias organizam este módulo:

1. **Ler e transformar primeiro, gravar depois.** Os arquivos brutos são lidos (com o hash conferido
   contra o manifest) e transformados em DataFrames ANTES de abrir a transação. Um arquivo adulterado
   ou um campo obrigatório ausente aborta sem encostar no banco.
2. **Uma transação por carga.** Tudo o que uma carga grava entra junto ou não entra: se qualquer
   tabela falhar, o banco volta ao estado anterior (nunca fica pela metade).

Dimensões compartilhadas (competitions, teams) e o ingestion_log usam UPSERT (`INSERT … ON CONFLICT
DO UPDATE`): repetir a carga é seguro. Os dados por partida (a partir do Passo 6) usarão DELETE +
INSERT dentro da transação (D06).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import Connection, Engine, text

from oddvision.config import Selection
from oddvision.ingest import IngestError, ManifestEntry, read_manifest, read_verified_json
from oddvision.transform.matches import competitions_frame, matches_frame, teams_frame

# Nomes de tabela e coluna vêm sempre do código, nunca de dados. Mesmo assim são validados: um
# identificador não pode ser passado como parâmetro SQL, então ele é inserido no texto do comando.
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
JSON_COLUMN = "extra"  # coluna JSONB: o dicionário vira texto JSON e é convertido com CAST


def _identifier(name: str) -> str:
    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"identificador SQL inválido: {name!r}")
    return name


def _records(frame: pd.DataFrame) -> list[dict]:
    records = frame.to_dict("records")
    for record in records:
        for column, value in record.items():
            if column == JSON_COLUMN:
                record[column] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, float) and math.isnan(value):
                raise ValueError(f"coluna {column}: NaN não pode virar NULL em silêncio")
    return records


def upsert(
    conn: Connection,
    table: str,
    frame: pd.DataFrame,
    key_columns: Sequence[str],
    *,
    keep_when_null: Sequence[str] = (),
) -> int:
    """INSERT … ON CONFLICT (chave) DO UPDATE em core.<table>. Devolve o nº de linhas enviadas.

    `keep_when_null`: colunas que, se o valor novo for NULL, mantêm o valor já gravado
    (ex.: ingestion_log.loaded_at, que um passo posterior pode ter preenchido).
    """
    _identifier(table)
    columns = list(frame.columns)
    for name in (*columns, *key_columns, *keep_when_null):
        _identifier(name)
    unknown = [k for k in key_columns if k not in columns]
    if unknown:
        raise ValueError(f"colunas de chave ausentes no DataFrame: {unknown}")
    if frame.empty:
        return 0

    values = ", ".join(f"CAST(:{c} AS JSONB)" if c == JSON_COLUMN else f":{c}" for c in columns)
    updates = [
        f"{c} = COALESCE(EXCLUDED.{c}, core.{table}.{c})" if c in keep_when_null else f"{c} = EXCLUDED.{c}"
        for c in columns
        if c not in key_columns
    ]
    action = f"DO UPDATE SET {', '.join(updates)}" if updates else "DO NOTHING"
    sql = (
        f"INSERT INTO core.{table} ({', '.join(columns)}) VALUES ({values}) "
        f"ON CONFLICT ({', '.join(key_columns)}) {action}"
    )
    conn.execute(text(sql), _records(frame))
    return len(frame)


# ----------------------------------------------------------------------------- ingestion_log

INGESTION_LOG_COLUMNS = (
    "file_path", "source_url", "source_commit", "sha256", "size_bytes", "record_count", "downloaded_at", "loaded_at",
)


def _ingestion_log_frame(
    entries: dict[str, ManifestEntry], loaded_files: set[str], loaded_at: datetime
) -> pd.DataFrame:
    """Uma linha por arquivo do manifest. `loaded_at` só é preenchido para os arquivos carregados agora."""
    rows = [
        {
            "file_path": e.file_path,
            "source_url": e.source_url,
            "source_commit": e.source_commit,
            "sha256": e.sha256,
            "size_bytes": e.size_bytes,
            "record_count": e.record_count,
            "downloaded_at": datetime.fromisoformat(e.downloaded_at),
            "loaded_at": loaded_at if e.file_path in loaded_files else None,
        }
        for e in (entries[key] for key in sorted(entries))
    ]
    return pd.DataFrame(rows, columns=list(INGESTION_LOG_COLUMNS), dtype=object)


# ----------------------------------------------------------------------------- P2

@dataclass(frozen=True)
class LoadResult:
    competitions: int
    teams: int
    matches: int
    log_files: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_p2(
    engine: Engine,
    selection: Selection,
    raw_dir: Path,
    manifest_path: Path,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> LoadResult:
    """P2: competitions, teams, matches e ingestion_log, em uma única transação.

    Entrada: competitions.json e matches/{competição}/{temporada}.json (hash conferido) + o manifest.
    Saída: core.competitions (o par selecionado), core.teams, core.matches (todas as partidas do
    arquivo) e core.ingestion_log (todos os arquivos do manifest; `loaded_at` só dos que foram lidos aqui).
    """
    entries = read_manifest(manifest_path)
    if not entries:
        raise IngestError(f"manifest ausente ou vazio ({manifest_path}): rode `ingest` antes de `load`.")

    matches_rel = f"matches/{selection.competition_id}/{selection.season_id}.json"
    competitions_json = read_verified_json(raw_dir, entries, "competitions.json")
    matches_json = read_verified_json(raw_dir, entries, matches_rel)

    competitions = competitions_frame(competitions_json, selection.competition_id, selection.season_id)
    teams = teams_frame(matches_json)
    matches = matches_frame(matches_json, selection.competition_id, selection.season_id)
    log = _ingestion_log_frame(entries, {"competitions.json", matches_rel}, now())

    with engine.begin() as conn:  # tudo ou nada: ordem das FKs (dimensões -> partidas)
        upsert(conn, "competitions", competitions, ["competition_id", "season_id"])
        upsert(conn, "teams", teams, ["team_id"])
        upsert(conn, "matches", matches, ["match_id"])
        upsert(conn, "ingestion_log", log, ["file_path"], keep_when_null=["loaded_at"])

    return LoadResult(len(competitions), len(teams), len(matches), len(log))
