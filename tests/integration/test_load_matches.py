"""Testes da carga P2 (Passo 5): competitions, teams, matches e ingestion_log no PostgreSQL.

Tudo é montado SEM rede: a ingestão roda com um downloader falso que serve as amostras de
tests/fixtures/ (objetos copiados sem alteração da fonte). Depois a carga lê esses arquivos brutos.
"""

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError as DatabaseIntegrityError

from oddvision.config import Selection
from oddvision.ingest import IntegrityError, read_manifest, run_ingest
from oddvision.load import load_p2, upsert
from oddvision.pipeline import main
from oddvision.transform.matches import MATCH_COLUMNS, TEAM_COLUMNS, COMPETITION_COLUMNS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COMMIT = "ab" * 20
SELECTION = Selection("owner/repo", COMMIT, 43, 106, (3869685,))
FINAL = 3869685
LOADED_BY_P2 = {"competitions.json", "matches/43/106.json"}
T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 2, 2, tzinfo=timezone.utc)


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def source_files(matches=None) -> dict[str, bytes]:
    """URL -> conteúdo: 2 arquivos de índice + events e lineups (vazios) de cada partida."""
    matches = fixture("matches_sample.json") if matches is None else matches
    files = {"competitions.json": dump(fixture("competitions_sample.json")), "matches/43/106.json": dump(matches)}
    for match in matches:
        files[f"events/{match['match_id']}.json"] = dump(fixture("events_sample.json"))
        files[f"lineups/{match['match_id']}.json"] = dump(fixture("lineups_sample.json"))
    return {SELECTION.base_url + rel: data for rel, data in files.items()}


def stage(tmp_path, matches=None):
    """Ingestão (sem rede) para tmp_path. Devolve (pasta raw, manifest)."""
    raw, manifest = tmp_path / "raw", tmp_path / "manifests" / "manifest.csv"
    run_ingest(SELECTION, raw, manifest, download=source_files(matches).__getitem__)
    return raw, manifest


def scalar(engine, sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar_one()


def counts(engine):
    return {t: scalar(engine, f"SELECT count(*) FROM core.{t}")
            for t in ("competitions", "teams", "matches", "ingestion_log")}


def snapshot(engine):
    with engine.connect() as c:
        return {
            "competitions": c.execute(text("SELECT * FROM core.competitions ORDER BY 1, 2")).all(),
            "teams": c.execute(text("SELECT * FROM core.teams ORDER BY 1")).all(),
            "matches": c.execute(text("SELECT * FROM core.matches ORDER BY 1")).all(),
        }


# --------------------------------------------------------------------------- carga

def test_load_writes_the_expected_rows(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)

    result = load_p2(fresh_schemas, SELECTION, raw, manifest, now=lambda: T1)

    assert (result.competitions, result.teams, result.matches, result.log_files) == (1, 5, 3, 8)
    # só o par (43, 106) foi carregado; a La Liga da amostra ficou de fora
    assert counts(fresh_schemas) == {"competitions": 1, "teams": 5, "matches": 3, "ingestion_log": 8}


def test_the_final_in_the_database_matches_the_source(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)
    load_p2(fresh_schemas, SELECTION, raw, manifest, now=lambda: T1)

    with fresh_schemas.connect() as c:
        r = c.execute(text("SELECT * FROM core.matches WHERE match_id = :m"), {"m": FINAL}).one()

    assert (r.competition_id, r.season_id) == (43, 106)
    assert r.match_date == date(2022, 12, 18)
    assert r.kick_off == time(17, 0)
    assert (r.home_team_id, r.away_team_id, r.home_score, r.away_score) == (779, 771, 3, 3)
    assert (r.match_week, r.competition_stage, r.stadium_name, r.referee_name) == (7, "Final", "Lusail Stadium", "Szymon Marciniak")
    assert (r.data_version, r.shot_fidelity_version, r.xy_fidelity_version) == ("1.1.0", "2", "2")
    assert r.last_updated == datetime(2024, 12, 16, 10, 15, 11, 55845)
    # JSONB: ida e volta sem perder acentos nem estrutura
    assert r.extra["home_team"]["managers"][0]["name"] == "Lionel Sebastián Scaloni"
    assert r.extra["stadium"]["country"] == {"id": 185, "name": "Qatar"}
    assert "home_score" not in r.extra and "match_id" not in r.extra


def test_teams_are_loaded_once_each(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)
    load_p2(fresh_schemas, SELECTION, raw, manifest)
    with fresh_schemas.connect() as c:
        rows = c.execute(text("SELECT team_id, team_name, team_gender, country_name FROM core.teams ORDER BY 1")).all()
    assert [tuple(r) for r in rows] == [
        (771, "France", "male", "France"), (772, "Spain", "male", "Spain"), (779, "Argentina", "male", "Argentina"),
        (792, "Australia", "male", "Australia"), (795, "Costa Rica", "male", "Costa Rica"),
    ]


def test_a_match_without_referee_is_stored_with_a_null_referee(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)
    load_p2(fresh_schemas, SELECTION, raw, manifest)
    assert scalar(fresh_schemas, "SELECT referee_name FROM core.matches WHERE match_id = 3857291") is None


def test_loading_twice_changes_nothing(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)
    load_p2(fresh_schemas, SELECTION, raw, manifest, now=lambda: T1)
    first = snapshot(fresh_schemas)

    load_p2(fresh_schemas, SELECTION, raw, manifest, now=lambda: T2)

    assert snapshot(fresh_schemas) == first
    assert counts(fresh_schemas) == {"competitions": 1, "teams": 5, "matches": 3, "ingestion_log": 8}


# --------------------------------------------------------------------------- ingestion_log

def test_ingestion_log_mirrors_the_manifest(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)
    load_p2(fresh_schemas, SELECTION, raw, manifest)

    with fresh_schemas.connect() as c:
        rows = {r.file_path: r for r in c.execute(text("SELECT * FROM core.ingestion_log")).all()}
    entries = read_manifest(manifest)

    assert set(rows) == set(entries)
    for path, entry in entries.items():
        r = rows[path]
        assert (r.source_url, r.source_commit, r.sha256, r.size_bytes, r.record_count) == (
            entry.source_url, entry.source_commit, entry.sha256, entry.size_bytes, entry.record_count)
        assert r.downloaded_at == datetime.fromisoformat(entry.downloaded_at)


def test_loaded_at_is_set_only_for_the_files_that_were_loaded(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)
    load_p2(fresh_schemas, SELECTION, raw, manifest, now=lambda: T1)

    with fresh_schemas.connect() as c:
        rows = {r.file_path: r.loaded_at for r in c.execute(text("SELECT file_path, loaded_at FROM core.ingestion_log")).all()}

    assert {p for p, t in rows.items() if t is not None} == LOADED_BY_P2
    assert all(rows[p] == T1 for p in LOADED_BY_P2)


def test_loading_again_refreshes_loaded_at_and_never_erases_a_later_one(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)
    load_p2(fresh_schemas, SELECTION, raw, manifest, now=lambda: T1)
    # simula um passo futuro que carregou os eventos da final
    with fresh_schemas.begin() as c:
        c.execute(text("UPDATE core.ingestion_log SET loaded_at = :t WHERE file_path = 'events/3869685.json'"), {"t": T1})

    load_p2(fresh_schemas, SELECTION, raw, manifest, now=lambda: T2)

    with fresh_schemas.connect() as c:
        rows = {r.file_path: r.loaded_at for r in c.execute(text("SELECT file_path, loaded_at FROM core.ingestion_log")).all()}
    assert rows["competitions.json"] == T2 and rows["matches/43/106.json"] == T2  # recarregados agora
    assert rows["events/3869685.json"] == T1  # não é apagado por quem não o carregou
    assert rows["events/3857291.json"] is None


# --------------------------------------------------------------------------- atomicidade e integridade

def test_a_tampered_raw_file_aborts_before_writing_anything(fresh_schemas, tmp_path):
    raw, manifest = stage(tmp_path)
    (raw / "matches" / "43" / "106.json").write_bytes(b"[]")

    with pytest.raises(IntegrityError, match=r"matches/43/106\.json"):
        load_p2(fresh_schemas, SELECTION, raw, manifest)

    assert counts(fresh_schemas) == {"competitions": 0, "teams": 0, "matches": 0, "ingestion_log": 0}


def test_a_failure_in_the_middle_rolls_everything_back(fresh_schemas, tmp_path):
    matches = fixture("matches_sample.json")
    matches[0]["home_score"] = -1  # passa pela transformação e é recusado pelo CHECK do banco
    raw, manifest = stage(tmp_path, matches=matches)

    with pytest.raises(DatabaseIntegrityError):
        load_p2(fresh_schemas, SELECTION, raw, manifest)

    # competitions e teams já tinham sido gravados quando matches falhou: nada pode ter ficado
    assert counts(fresh_schemas) == {"competitions": 0, "teams": 0, "matches": 0, "ingestion_log": 0}


# --------------------------------------------------------------------------- upsert

def team_frame(team_id, name):
    return pd.DataFrame([{"team_id": team_id, "team_name": name, "team_gender": None, "country_name": None}], dtype=object)


def test_upsert_inserts_then_updates_the_same_row(conn):
    assert upsert(conn, "teams", team_frame(1, "A"), ["team_id"]) == 1
    assert upsert(conn, "teams", team_frame(1, "B"), ["team_id"]) == 1
    rows = conn.execute(text("SELECT team_id, team_name FROM core.teams")).all()
    assert [tuple(r) for r in rows] == [(1, "B")]


def test_upsert_with_no_rows_does_nothing(conn):
    assert upsert(conn, "teams", team_frame(1, "A").iloc[0:0], ["team_id"]) == 0
    assert conn.execute(text("SELECT count(*) FROM core.teams")).scalar_one() == 0


def test_upsert_stores_extra_as_jsonb(conn):
    frame = pd.DataFrame([{
        "competition_id": 1, "season_id": 1, "competition_name": "Copa", "season_name": "2022",
        "country_name": None, "competition_gender": "male", "competition_youth": False,
        "competition_international": True, "extra": {"treinador": "Seleção", "lista": [1, {"a": None}]},
    }], dtype=object)
    upsert(conn, "competitions", frame, ["competition_id", "season_id"])
    assert conn.execute(text("SELECT extra FROM core.competitions")).scalar_one() == {"treinador": "Seleção", "lista": [1, {"a": None}]}


def log_frame(loaded_at):
    return pd.DataFrame([{
        "file_path": "a.json", "source_url": "http://x/a.json", "source_commit": COMMIT, "sha256": "0" * 64,
        "size_bytes": 10, "record_count": 1, "downloaded_at": T1, "loaded_at": loaded_at,
    }], dtype=object)


def test_upsert_can_keep_the_stored_value_when_the_new_one_is_null(conn):
    upsert(conn, "ingestion_log", log_frame(T1), ["file_path"], keep_when_null=["loaded_at"])
    upsert(conn, "ingestion_log", log_frame(None), ["file_path"], keep_when_null=["loaded_at"])
    assert conn.execute(text("SELECT loaded_at FROM core.ingestion_log")).scalar_one() == T1


def test_upsert_overwrites_with_null_unless_told_otherwise(conn):
    upsert(conn, "ingestion_log", log_frame(T1), ["file_path"])
    upsert(conn, "ingestion_log", log_frame(None), ["file_path"])
    assert conn.execute(text("SELECT loaded_at FROM core.ingestion_log")).scalar_one() is None


@pytest.mark.parametrize("table", ["teams; DROP TABLE core.teams", "core.teams", "Teams", ""])
def test_upsert_rejects_unsafe_table_names(conn, table):
    with pytest.raises(ValueError, match="identificador"):
        upsert(conn, table, team_frame(1, "A"), ["team_id"])


def test_upsert_rejects_unsafe_column_names(conn):
    frame = team_frame(1, "A").rename(columns={"team_name": "team_name) VALUES (1); --"})
    with pytest.raises(ValueError, match="identificador"):
        upsert(conn, "teams", frame, ["team_id"])


# --------------------------------------------------------------------------- colunas e CLI

@pytest.mark.parametrize("table, columns", [
    ("competitions", COMPETITION_COLUMNS), ("teams", TEAM_COLUMNS), ("matches", MATCH_COLUMNS)])
def test_frame_columns_follow_the_table_column_order(schemas, table, columns):
    with schemas.connect() as c:
        in_database = list(c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'core' AND table_name = :t ORDER BY ordinal_position"), {"t": table}).scalars())
    assert list(columns) == in_database


def test_load_command_is_repeatable(fresh_schemas, db_config, tmp_path, capsys):
    """`python -m oddvision.pipeline ingest` + `load`, apontados para o banco de TESTES."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "selection.toml").write_text(
        f'[source]\nrepo = "owner/repo"\ncommit = "{COMMIT}"\n\n[competition]\ncompetition_id = 43\n'
        "season_id = 106\n\n[load]\nmatch_ids = [3869685]\n", encoding="utf-8")
    (tmp_path / "config" / "database.toml").write_text(
        f"[connection]\nhost = {json.dumps(db_config.host)}\nport = {db_config.port}\n"
        f"user = {json.dumps(db_config.user)}\npassword = {json.dumps(db_config.password)}\n\n"
        f"[databases]\nmain = {json.dumps(db_config.test_db)}\ntest = {json.dumps(db_config.test_db)}\n", encoding="utf-8")

    assert main(["ingest"], root=tmp_path, download=source_files().__getitem__) == 0
    capsys.readouterr()

    for _ in range(2):
        assert main(["load"], root=tmp_path) == 0
        out = capsys.readouterr().out
        assert "competitions: 1" in out and "teams: 5" in out and "matches: 3" in out
        assert "ingestion_log: 8" in out
        assert db_config.password not in out
    assert counts(fresh_schemas) == {"competitions": 1, "teams": 5, "matches": 3, "ingestion_log": 8}
