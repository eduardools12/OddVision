"""Carga no schema core (P2: competições, times e partidas; P3: escalações; P4: eventos).

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
from oddvision.transform.events import events_frame
from oddvision.transform.lineups import AttributeConflict, lineups_frame, resolve_players
from oddvision.transform.matches import competitions_frame, matches_frame, teams_frame

# Nomes de tabela e coluna vêm sempre do código, nunca de dados. Mesmo assim são validados: um
# identificador não pode ser passado como parâmetro SQL, então ele é inserido no texto do comando.
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
JSON_COLUMN = "extra"  # coluna JSONB: o dicionário vira texto JSON e é convertido com CAST


class LoadError(Exception):
    """A carga não pode continuar (ex.: a partida ainda não está em core.matches)."""


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
    columns = _check_names(table, frame, [*key_columns, *keep_when_null])
    unknown = [k for k in key_columns if k not in columns]
    if unknown:
        raise ValueError(f"colunas de chave ausentes no DataFrame: {unknown}")
    if frame.empty:
        return 0

    updates = [
        f"{c} = COALESCE(EXCLUDED.{c}, core.{table}.{c})" if c in keep_when_null else f"{c} = EXCLUDED.{c}"
        for c in columns
        if c not in key_columns
    ]
    action = f"DO UPDATE SET {', '.join(updates)}" if updates else "DO NOTHING"
    sql = f"{_insert_sql(table, columns)} ON CONFLICT ({', '.join(key_columns)}) {action}"
    conn.execute(text(sql), _records(frame))
    return len(frame)


def insert(conn: Connection, table: str, frame: pd.DataFrame) -> int:
    """INSERT simples em core.<table>. Uma linha repetida FALHA (não é silenciada): é o par do DELETE por partida."""
    columns = _check_names(table, frame)
    if frame.empty:
        return 0
    conn.execute(text(_insert_sql(table, columns)), _records(frame))
    return len(frame)


def _check_names(table: str, frame: pd.DataFrame, extra_names: Sequence[str] = ()) -> list[str]:
    columns = list(frame.columns)
    for name in (table, *columns, *extra_names):
        _identifier(name)
    return columns


def _insert_sql(table: str, columns: Sequence[str]) -> str:
    values = ", ".join(f"CAST(:{c} AS JSONB)" if c == JSON_COLUMN else f":{c}" for c in columns)
    return f"INSERT INTO core.{table} ({', '.join(columns)}) VALUES ({values})"


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


# ----------------------------------------------------------------------------- P3: escalações

@dataclass(frozen=True)
class MatchResult:
    match_id: int
    players: int  # jogadores relacionados na partida
    starters: int
    played: int  # relacionados que entraram em campo
    events: int  # eventos gravados em core.events
    player_ids: tuple[int, ...]


@dataclass(frozen=True)
class MatchesResult:
    matches: tuple[MatchResult, ...]
    players: int  # jogadores distintos gravados em core.players
    conflicts: tuple[AttributeConflict, ...]  # só dos jogadores gravados


def build_player_table(raw_dir: Path, entries: dict[str, ManifestEntry]) -> tuple[pd.DataFrame, list[AttributeConflict]]:
    """Resolve os atributos de cada jogador olhando TODOS os arquivos de escalação do manifest.

    Todos, e não só as partidas carregadas: assim o nome gravado não muda quando o Passo 13 carregar
    as outras partidas. Cada arquivo tem o hash conferido; um adulterado aborta antes de gravar algo.
    """
    paths = sorted(p for p in entries if p.startswith("lineups/"))
    if not paths:
        raise LoadError("o manifest não tem arquivos de escalação (lineups/*.json): rode `ingest`.")
    files = {int(Path(p).stem): read_verified_json(raw_dir, entries, p) for p in paths}
    return resolve_players(files)


def _mark_loaded(conn: Connection, rel_path: str, when: datetime) -> None:
    result = conn.execute(
        text("UPDATE core.ingestion_log SET loaded_at = :t WHERE file_path = :p"), {"t": when, "p": rel_path}
    )
    if result.rowcount != 1:
        raise LoadError(f"{rel_path} não consta em core.ingestion_log: rode `load` (P2) antes.")


def load_match(
    engine: Engine,
    raw_dir: Path,
    entries: dict[str, ManifestEntry],
    match_id: int,
    players: pd.DataFrame,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> MatchResult:
    """Carrega UMA partida em uma transação (D06): escalações (P3) e eventos (P4).

    Os dois arquivos são lidos e transformados ANTES de abrir a transação. Dentro dela, na ordem das FKs:
    players (upsert) -> DELETE da partida (lineups e events) -> INSERT de lineups e events -> loaded_at.
    Os dados da partida são apagados e inseridos de novo: recarregar nunca duplica nem deixa linhas velhas.
    `players`: tabela de jogadores já resolvida (`build_player_table`); só os da partida são gravados.
    Se qualquer passo falhar, a partida volta ao estado anterior. Outras partidas nunca são tocadas.
    """
    lineups_rel, events_rel = f"lineups/{match_id}.json", f"events/{match_id}.json"
    lineups = lineups_frame(match_id, read_verified_json(raw_dir, entries, lineups_rel))
    events = events_frame(match_id, read_verified_json(raw_dir, entries, events_rel))
    match_players = players[players.player_id.isin(lineups.player_id)]

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT home_team_id, away_team_id FROM core.matches WHERE match_id = :m"), {"m": match_id}
        ).one_or_none()
        if row is None:
            raise LoadError(f"partida {match_id} não existe em core.matches: rode `load` (P2) antes das escalações.")
        in_match = sorted({row.home_team_id, row.away_team_id})
        in_lineups = sorted(set(lineups.team_id))
        if in_lineups != in_match:
            raise LoadError(f"partida {match_id}: a escalação traz os times {in_lineups}, mas a partida é {in_match}.")
        in_events = sorted(set(events.team_id) | set(events.possession_team_id))
        if not set(in_events) <= set(in_match):
            raise LoadError(f"partida {match_id}: há eventos de times {in_events}, mas a partida é {in_match}.")

        upsert(conn, "players", match_players, ["player_id"])
        conn.execute(text("DELETE FROM core.lineups WHERE match_id = :m"), {"m": match_id})  # sempre filtrado
        conn.execute(text("DELETE FROM core.events WHERE match_id = :m"), {"m": match_id})  # sempre filtrado
        insert(conn, "lineups", lineups)
        insert(conn, "events", events)
        _mark_loaded(conn, lineups_rel, now())
        _mark_loaded(conn, events_rel, now())

    return MatchResult(
        match_id=match_id,
        players=len(lineups),
        starters=int(lineups.is_starter.sum()),
        played=int(lineups.played.sum()),
        events=len(events),
        player_ids=tuple(int(p) for p in lineups.player_id),
    )


def load_matches(
    engine: Engine,
    selection: Selection,
    raw_dir: Path,
    manifest_path: Path,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> MatchesResult:
    """P3 e P4: players, lineups e events das partidas de `selection.load_match_ids`, uma transação por partida.

    Entrada: lineups/*.json e events/*.json (hash conferido) e core.matches (P2).
    Saída: core.players, core.lineups e core.events.
    Se uma partida falhar, as anteriores já estão gravadas (cada uma é atômica) e a falha é reportada.
    """
    entries = read_manifest(manifest_path)
    if not entries:
        raise IngestError(f"manifest ausente ou vazio ({manifest_path}): rode `ingest` antes de `load`.")

    players, conflicts = build_player_table(raw_dir, entries)
    results = tuple(
        load_match(engine, raw_dir, entries, match_id, players, now=now) for match_id in selection.load_match_ids
    )
    loaded = {player_id for result in results for player_id in result.player_ids}
    return MatchesResult(
        matches=results,
        players=len(loaded),
        conflicts=tuple(c for c in conflicts if c.player_id in loaded),
    )
