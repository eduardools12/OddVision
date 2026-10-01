"""Testes da carga P4 (Passo 7): core.events das partidas-sentinela, na mesma transação das escalações.

Tudo é montado SEM rede: a ingestão roda com um downloader falso que serve as amostras de tests/fixtures/
(19 eventos reais da final e 7 jogadores reais, copiados sem alteração).
"""

import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError as DatabaseIntegrityError

from oddvision.config import Selection
from oddvision.ingest import IntegrityError, run_ingest
from oddvision.load import LoadError, load_matches, load_p2
from oddvision.pipeline import main
from oddvision.transform.events import EVENT_COLUMNS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COMMIT = "ab" * 20
SELECTION = Selection("owner/repo", COMMIT, 43, 106, (3869685,))
FINAL, ARG_AUS, NO_REFEREE = 3869685, 3869151, 3857291
T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Fatos conhecidos da amostra de 19 eventos (contados à mão a partir do JSON da final)
TYPE_COUNTS = {
    "Starting XI": 1, "Half Start": 1, "Carry": 1, "Pass": 3, "Ball Receipt*": 1, "Foul Committed": 3,
    "Goal Keeper": 1, "Shot": 2, "Player Off": 1, "Player On": 1, "Pressure": 1, "Tactical Shift": 1,
    "Duel": 1, "Bad Behaviour": 1,
}
PASS_OF_MESSI = 88


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def stage(tmp_path, events=None):
    """Ingestão (sem rede). `events`: {match_id: JSON} substitui os eventos padrão de uma partida."""
    matches = fixture("matches_sample.json")
    by_match = {m["match_id"]: fixture("events_sample.json") for m in matches}
    by_match.update(events or {})
    files = {"competitions.json": dump(fixture("competitions_sample.json")), "matches/43/106.json": dump(matches)}
    for match_id, content in by_match.items():
        files[f"events/{match_id}.json"] = dump(content)
        files[f"lineups/{match_id}.json"] = dump(fixture("lineups_sample.json"))
    served = {SELECTION.base_url + rel: data for rel, data in files.items()}
    raw, manifest = tmp_path / "raw", tmp_path / "manifests" / "manifest.csv"
    run_ingest(SELECTION, raw, manifest, download=served.__getitem__)
    return raw, manifest, served


def prepare(tmp_path, engine, events=None):
    """Ingestão + P2 (as partidas precisam existir em core.matches antes das escalações e dos eventos)."""
    raw, manifest, _ = stage(tmp_path, events)
    load_p2(engine, SELECTION, raw, manifest, now=lambda: T1)
    return raw, manifest


def scalar(engine, sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar_one()


def rows(engine, sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).all()


def nothing_written(engine):
    return [scalar(engine, f"SELECT count(*) FROM core.{t}") for t in ("players", "lineups", "events")] == [0, 0, 0]


def events_with(**changes):
    """A amostra com uma alteração no evento 88 (o passe do Messi)."""
    content = fixture("events_sample.json")
    event = next(e for e in content if e["index"] == PASS_OF_MESSI)
    for path, value in changes.items():
        node = event
        *parents, leaf = path.split("__")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return content


# --------------------------------------------------------------------------- carga

def test_load_writes_the_events_of_the_sentinel(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)

    result = load_matches(fresh_schemas, SELECTION, raw, manifest, now=lambda: T1)

    assert [(m.match_id, m.events) for m in result.matches] == [(FINAL, 19)]
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.events") == 19
    by_type = {r.type_name: r.n for r in rows(fresh_schemas, "SELECT type_name, count(*) AS n FROM core.events GROUP BY 1")}
    assert by_type == TYPE_COUNTS  # todos os tipos preservados, com as contagens da fonte


def test_event_ids_are_unique_and_belong_to_the_match(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert scalar(fresh_schemas, "SELECT count(DISTINCT event_id) FROM core.events") == 19
    assert scalar(fresh_schemas, "SELECT count(DISTINCT match_id) FROM core.events") == 1
    assert scalar(fresh_schemas, "SELECT match_id FROM core.events LIMIT 1") == FINAL
    stored = {str(r.event_id) for r in rows(fresh_schemas, "SELECT event_id FROM core.events")}
    assert stored == {e["id"] for e in fixture("events_sample.json")}


def test_a_pass_is_stored_with_the_right_types_and_values(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)

    r = rows(fresh_schemas, "SELECT * FROM core.events WHERE idx = :i", i=PASS_OF_MESSI)[0]
    source = next(e for e in fixture("events_sample.json") if e["index"] == PASS_OF_MESSI)

    assert isinstance(r.event_id, uuid.UUID) and str(r.event_id) == source["id"]
    assert (r.match_id, r.period, r.minute, r.second) == (FINAL, 1, 2, 16)
    assert r.ts_in_period == timedelta(seconds=136, microseconds=985000)  # INTERVAL exato
    assert (r.type_name, r.team_id, r.player_id, r.position_name) == ("Pass", 779, 5503, "Right Wing")
    assert (r.possession, r.possession_team_id, r.play_pattern) == (8, 779, "From Throw In")
    assert (r.x, r.y, r.duration, r.under_pressure) == (76.6, 35.7, 4.15978, True)
    assert r.extra["type"] == {"id": 30} and r.extra["related_events"] == source["related_events"]
    assert "pass" not in r.extra and "team" not in r.extra  # objeto da tabela própria e nome da dimensão


def test_nulls_flags_and_periods_are_stored_as_in_the_source(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)

    counts = rows(fresh_schemas, """
        SELECT count(*) FILTER (WHERE x IS NULL AND y IS NULL) AS no_location,
               count(*) FILTER (WHERE player_id IS NULL) AS no_player,
               count(*) FILTER (WHERE duration IS NULL) AS no_duration,
               count(*) FILTER (WHERE under_pressure) AS pressured,
               count(*) FILTER (WHERE period = 5) AS shootout,
               count(*) FILTER (WHERE possession_team_id <> team_id) AS other_team_possession
        FROM core.events""")[0]
    assert (counts.no_location, counts.no_player, counts.no_duration, counts.pressured, counts.shootout) == (6, 3, 1, 3, 2)
    assert counts.other_team_possession == 7  # Half Start, falta, Player Off, Pressure, Tactical Shift, Duel, falta


def test_extra_keeps_objects_and_drops_the_cards(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)
    extra = lambda idx: scalar(fresh_schemas, "SELECT extra FROM core.events WHERE idx = :i", i=idx)

    assert "duel" in extra(1521) and "goalkeeper" in extra(465) and "tactics" in extra(1)
    assert "foul_committed" not in extra(3396) and "bad_behaviour" not in extra(4401)  # só tinham o cartão
    assert "card" not in extra(3160)["foul_committed"] and len(extra(3160)["foul_committed"]) >= 1
    assert all(not {"shot", "pass", "carry", "substitution"} & set(r.extra) for r in rows(fresh_schemas, "SELECT extra FROM core.events"))


def test_loading_twice_changes_nothing(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)
    first = rows(fresh_schemas, "SELECT * FROM core.events ORDER BY idx")

    load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert rows(fresh_schemas, "SELECT * FROM core.events ORDER BY idx") == first


def test_reloading_replaces_the_match_events_and_leaves_other_matches_alone(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)
    insert = ("INSERT INTO core.events (event_id, match_id, idx, period, ts_in_period, minute, second, type_name, team_id, "
              "possession, possession_team_id, play_pattern) VALUES (:e, :m, :i, 1, interval '1 second', 0, 1, 'Pass', 779, 1, 779, 'Regular Play')")
    with fresh_schemas.begin() as c:  # um evento velho na partida recarregada e um evento em OUTRA partida
        c.execute(text(insert), {"e": uuid.uuid4(), "m": FINAL, "i": 99999})
        c.execute(text(insert), {"e": uuid.uuid4(), "m": NO_REFEREE, "i": 1})

    load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert scalar(fresh_schemas, "SELECT count(*) FROM core.events WHERE match_id = :m AND idx = 99999", m=FINAL) == 0
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.events WHERE match_id = :m", m=FINAL) == 19
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.events WHERE match_id = :m", m=NO_REFEREE) == 1  # intacta


def test_only_the_loaded_matches_get_events(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)
    assert [r.match_id for r in rows(fresh_schemas, "SELECT DISTINCT match_id FROM core.events")] == [FINAL]


# --------------------------------------------------------------------------- atomicidade e integridade

def test_a_failure_while_inserting_events_rolls_the_whole_match_back(fresh_schemas, tmp_path):
    # O jogador 424242 não existe: a FK recusa no INSERT dos eventos, depois de players, DELETEs e lineups.
    raw, manifest = prepare(tmp_path, fresh_schemas, {FINAL: events_with(player__id=424242)})

    with pytest.raises(DatabaseIntegrityError):
        load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert nothing_written(fresh_schemas)  # as escalações e os players também foram desfeitos
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.ingestion_log WHERE file_path LIKE 'lineups/%' AND loaded_at IS NOT NULL") == 0


def test_events_of_a_team_outside_the_match_are_refused(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas, {FINAL: events_with(team__id=792)})  # a Austrália não joga a final

    with pytest.raises(LoadError, match="792"):
        load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert nothing_written(fresh_schemas)


def test_a_tampered_events_file_aborts_before_writing_anything(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    (raw / "events" / f"{FINAL}.json").write_bytes(b"[]")

    with pytest.raises(IntegrityError, match=rf"events/{FINAL}\.json"):
        load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert nothing_written(fresh_schemas)


def test_an_invalid_event_aborts_before_writing_anything(fresh_schemas, tmp_path):
    from oddvision.transform.common import TransformError

    raw, manifest = prepare(tmp_path, fresh_schemas, {FINAL: events_with(period=7)})

    with pytest.raises(TransformError, match="period"):
        load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert nothing_written(fresh_schemas)


def test_the_ingestion_log_marks_the_events_file_that_was_loaded(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    t2 = datetime(2026, 2, 2, tzinfo=timezone.utc)
    load_matches(fresh_schemas, SELECTION, raw, manifest, now=lambda: t2)

    loaded = {r.file_path: r.loaded_at for r in rows(fresh_schemas, "SELECT file_path, loaded_at FROM core.ingestion_log")}
    assert loaded[f"events/{FINAL}.json"] == t2 and loaded[f"lineups/{FINAL}.json"] == t2
    assert loaded[f"events/{ARG_AUS}.json"] is None and loaded[f"events/{NO_REFEREE}.json"] is None


# --------------------------------------------------------------------------- colunas e CLI

def test_frame_columns_follow_the_table_column_order(schemas):
    in_database = [r.column_name for r in rows(
        schemas, "SELECT column_name FROM information_schema.columns "
                 "WHERE table_schema = 'core' AND table_name = 'events' ORDER BY ordinal_position")]
    assert list(EVENT_COLUMNS) == in_database


def test_load_command_reports_the_events(fresh_schemas, db_config, tmp_path, capsys):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "selection.toml").write_text(
        f'[source]\nrepo = "owner/repo"\ncommit = "{COMMIT}"\n\n[competition]\ncompetition_id = 43\n'
        "season_id = 106\n\n[load]\nmatch_ids = [3869685]\n", encoding="utf-8")
    (tmp_path / "config" / "database.toml").write_text(
        f"[connection]\nhost = {json.dumps(db_config.host)}\nport = {db_config.port}\n"
        f"user = {json.dumps(db_config.user)}\npassword = {json.dumps(db_config.password)}\n\n"
        f"[databases]\nmain = {json.dumps(db_config.test_db)}\ntest = {json.dumps(db_config.test_db)}\n", encoding="utf-8")
    _, _, served = stage(tmp_path / "unused")
    assert main(["ingest"], root=tmp_path, download=served.__getitem__) == 0
    capsys.readouterr()

    for _ in range(2):
        assert main(["load"], root=tmp_path) == 0
        out = capsys.readouterr().out
        assert "events: partida 3869685: 19 eventos" in out
        assert db_config.password not in out
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.events") == 19
