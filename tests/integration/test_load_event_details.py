"""Testes da carga P5 (Passo 8): shots, passes, carries, cards e substitutions, na transação da partida.

Tudo é montado SEM rede. O cenário completo junta eventos REAIS da final, copiados sem alteração:
- events_sample.json (19 eventos: 2 chutes, 3 passes, 1 condução, 3 cartões);
- shot_with_key_pass_sample.json (o passe #2985 do Thuram e o chute #2987 do Mbappé, ligados por key_pass_id);
- uma substituição real (#1379) com o jogador que SAI trocado pelo Mbappé, porque quem sai na troca real
  (Giroud) não está na amostra de escalações. Quem ENTRA (Thuram) é o da fonte.
"""

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError as DatabaseIntegrityError

from oddvision.config import Selection
from oddvision.ingest import run_ingest
from oddvision.load import load_matches, load_p2
from oddvision.pipeline import main
from oddvision.transform.event_details import (
    CARD_COLUMNS, CARRY_COLUMNS, PASS_COLUMNS, SHOT_COLUMNS, SUBSTITUTION_COLUMNS,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COMMIT = "ab" * 20
SELECTION = Selection("owner/repo", COMMIT, 43, 106, (3869685,))
FINAL, ARG_AUS, NO_REFEREE = 3869685, 3869151, 3857291
T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
MBAPPE, THURAM = 3009, 2972
# O que o cenário completo deve gerar (contado à mão a partir dos fixtures)
EXPECTED = {"events": 22, "shots": 3, "passes": 4, "carries": 1, "cards": 3, "substitutions": 1}


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def full_scenario():
    events = fixture("events_sample.json") + fixture("shot_with_key_pass_sample.json")
    substitution = copy.deepcopy(next(e for e in fixture("substitutions_sample.json") if e["index"] == 1379))
    substitution["player"] = {"id": MBAPPE, "name": "Kylian Mbappé Lottin"}  # quem sai, trocado: veja a docstring
    return sorted(events + [substitution], key=lambda e: e["index"])


def stage(tmp_path, events=None):
    """Ingestão (sem rede). `events` substitui os eventos da partida da final (padrão: o cenário completo)."""
    matches = fixture("matches_sample.json")
    files = {"competitions.json": dump(fixture("competitions_sample.json")), "matches/43/106.json": dump(matches)}
    for match in matches:
        files[f"events/{match['match_id']}.json"] = dump(events if match["match_id"] == FINAL and events is not None
                                                         else full_scenario() if match["match_id"] == FINAL
                                                         else fixture("events_sample.json"))
        files[f"lineups/{match['match_id']}.json"] = dump(fixture("lineups_sample.json"))
    served = {SELECTION.base_url + rel: data for rel, data in files.items()}
    raw, manifest = tmp_path / "raw", tmp_path / "manifests" / "manifest.csv"
    run_ingest(SELECTION, raw, manifest, download=served.__getitem__)
    return raw, manifest, served


def prepare(tmp_path, engine, events=None):
    raw, manifest, _ = stage(tmp_path, events)
    load_p2(engine, SELECTION, raw, manifest, now=lambda: T1)
    return raw, manifest


def load(engine, raw, manifest):
    return load_matches(engine, SELECTION, raw, manifest, now=lambda: T1)


def scalar(engine, sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar_one()


def rows(engine, sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).all()


def count(engine, table):
    return scalar(engine, f"SELECT count(*) FROM core.{table}")


def nothing_written(engine):
    return [count(engine, t) for t in ("players", "lineups", "events", "shots", "passes", "carries", "cards", "substitutions")] == [0] * 8


# --------------------------------------------------------------------------- contagens

def test_each_table_has_one_row_per_event_of_its_type(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)

    result = load(fresh_schemas, raw, manifest)

    assert {t: count(fresh_schemas, t) for t in ("events", "shots", "passes", "carries", "cards", "substitutions")} == {
        "events": 22, "shots": 3, "passes": 4, "carries": 1, "cards": 3, "substitutions": 1}
    m = result.matches[0]
    assert (m.events, m.shots, m.passes, m.carries, m.cards, m.substitutions) == tuple(EXPECTED.values())
    for table, type_name in (("shots", "Shot"), ("passes", "Pass"), ("carries", "Carry"), ("substitutions", "Substitution")):
        assert count(fresh_schemas, table) == scalar(fresh_schemas, "SELECT count(*) FROM core.events WHERE type_name = :t", t=type_name)


def test_every_row_points_to_an_event_of_the_right_type(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)
    for table, types in (("shots", ("Shot",)), ("passes", ("Pass",)), ("carries", ("Carry",)),
                         ("cards", ("Foul Committed", "Bad Behaviour")), ("substitutions", ("Substitution",))):
        wrong = scalar(fresh_schemas, f"SELECT count(*) FROM core.{table} t JOIN core.events e USING (event_id) "
                                      "WHERE e.type_name <> ALL(:types)", types=list(types))
        assert wrong == 0, table


def test_events_extra_has_none_of_the_objects_that_have_their_own_table(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.events WHERE extra ?| array['shot','pass','carry','substitution']") == 0


# --------------------------------------------------------------------------- valores

def test_a_shot_is_stored_with_the_right_types(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)

    r = rows(fresh_schemas, "SELECT s.* FROM core.shots s JOIN core.events e USING (event_id) WHERE e.idx = 2987")[0]
    pass_id = scalar(fresh_schemas, "SELECT event_id FROM core.events WHERE idx = 2985")
    assert (r.statsbomb_xg, r.end_x, r.end_y, r.end_z) == (0.1017027, 120.0, 41.5, 0.3)
    assert (r.outcome, r.shot_type, r.body_part, r.technique) == ("Goal", "Open Play", "Right Foot", "Volley")
    assert r.key_pass_id == pass_id  # a chave estrangeira resolve para o passe da própria partida
    assert r.extra["first_time"] is True and len(r.extra["freeze_frame"]) > 0 and r.extra["outcome"] == {"id": 97}


def test_penalties_keep_the_same_xg_and_no_xg_is_outside_0_1(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)
    assert [r.statsbomb_xg for r in rows(fresh_schemas, "SELECT statsbomb_xg FROM core.shots WHERE shot_type = 'Penalty'")] == [0.7835, 0.7835]
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.shots WHERE statsbomb_xg < 0 OR statsbomb_xg > 1") == 0


def test_passes_keep_complete_incomplete_and_the_flags(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)

    by_idx = {r.idx: r for r in rows(fresh_schemas, "SELECT e.idx, p.* FROM core.passes p JOIN core.events e USING (event_id)")}
    assert sorted(by_idx) == [88, 466, 796, 2985]
    assert (by_idx[88].recipient_id, by_idx[88].end_x, by_idx[88].is_complete, by_idx[88].outcome) == (2995, 116.2, True, None)
    assert (by_idx[796].is_complete, by_idx[796].outcome, by_idx[796].recipient_id) == (False, "Incomplete", None)
    assert (by_idx[2985].is_goal_assist, by_idx[2985].is_shot_assist, by_idx[2985].recipient_id) == (True, False, MBAPPE)
    assert by_idx[2985].extra["assisted_shot_id"] == scalar(fresh_schemas, "SELECT event_id::text FROM core.events WHERE idx = 2987")
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.passes WHERE is_complete <> (outcome IS NULL)") == 0


def test_the_carry_and_the_substitution(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)

    carry = rows(fresh_schemas, "SELECT c.end_x, c.end_y FROM core.carries c JOIN core.events e USING (event_id) WHERE e.idx = 86")[0]
    assert (carry.end_x, carry.end_y) == (76.6, 35.7)
    sub = rows(fresh_schemas, "SELECT e.player_id AS off, e.team_id, s.player_on_id, s.reason FROM core.substitutions s JOIN core.events e USING (event_id)")[0]
    assert (sub.off, sub.team_id, sub.player_on_id, sub.reason) == (MBAPPE, 771, THURAM, "Tactical")


def test_the_cards_in_the_events_match_the_cards_in_the_lineups(fresh_schemas, tmp_path):
    """O aviso C09 do Passo 9, já valendo aqui: as duas fontes dos cartões precisam concordar."""
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)

    from_events = sorted((r.player_id, r.card_type) for r in rows(
        fresh_schemas, "SELECT e.player_id, c.card_type FROM core.cards c JOIN core.events e USING (event_id)"))
    from_lineups = sorted((r.player_id, r.card_type) for r in rows(
        fresh_schemas, "SELECT l.player_id, c->>'card_type' AS card_type FROM core.lineups l, "
                       "jsonb_array_elements(l.extra->'cards') c WHERE l.match_id = :m", m=FINAL))
    assert from_events == from_lineups == [(2972, "Yellow Card"), (6909, "Yellow Card"), (19597, "Yellow Card")]


# --------------------------------------------------------------------------- repetibilidade

def snapshot(engine):
    return {t: rows(engine, f"SELECT * FROM core.{t} ORDER BY 1") for t in ("shots", "passes", "carries", "cards", "substitutions")}


def test_loading_twice_changes_nothing_even_with_key_pass_references(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)
    first = snapshot(fresh_schemas)

    load(fresh_schemas, raw, manifest)  # apaga os eventos (e, em cascata, as tabelas filhas) e insere de novo

    assert snapshot(fresh_schemas) == first


def test_reloading_removes_stale_rows_of_the_match_and_leaves_other_matches_alone(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load(fresh_schemas, raw, manifest)
    event_sql = ("INSERT INTO core.events (event_id, match_id, idx, period, ts_in_period, minute, second, type_name, team_id, "
                 "possession, possession_team_id, play_pattern) VALUES (:e, :m, :i, 1, interval '1 second', 0, 1, :t, 779, 1, 779, 'Regular Play')")
    stale, other = uuid.uuid4(), uuid.uuid4()
    with fresh_schemas.begin() as c:
        for event_id, match_id, idx in ((stale, FINAL, 99999), (other, NO_REFEREE, 1)):
            c.execute(text(event_sql), {"e": event_id, "m": match_id, "i": idx, "t": "Shot"})
            c.execute(text("INSERT INTO core.shots (event_id, statsbomb_xg, end_x, end_y, outcome, shot_type) "
                           "VALUES (:e, 0.5, 120, 40, 'Goal', 'Open Play')"), {"e": event_id})
    assert count(fresh_schemas, "shots") == 5

    load(fresh_schemas, raw, manifest)

    assert scalar(fresh_schemas, "SELECT count(*) FROM core.shots WHERE event_id = :e", e=stale) == 0  # sumiu em cascata
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.shots WHERE event_id = :e", e=other) == 1  # outra partida intacta
    assert count(fresh_schemas, "shots") == 4


# --------------------------------------------------------------------------- atomicidade

def test_a_failure_in_a_specialized_table_rolls_the_whole_match_back(fresh_schemas, tmp_path):
    # O destinatário 424242 não existe: a FK recusa o INSERT de passes, depois de lineups, events e shots.
    events = full_scenario()
    next(e for e in events if e["index"] == 88)["pass"]["recipient"] = {"id": 424242, "name": "Fantasma"}
    raw, manifest = prepare(tmp_path, fresh_schemas, events)

    with pytest.raises(DatabaseIntegrityError):
        load(fresh_schemas, raw, manifest)

    assert nothing_written(fresh_schemas)  # nem escalações, nem eventos, nem chutes
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.ingestion_log WHERE loaded_at IS NOT NULL AND file_path <> ALL(:p)",
                  p=["competitions.json", "matches/43/106.json"]) == 0


def test_a_shot_pointing_to_a_pass_from_another_match_never_reaches_the_database(fresh_schemas, tmp_path):
    from oddvision.transform.common import TransformError

    events = full_scenario()
    next(e for e in events if e["index"] == 2987)["shot"]["key_pass_id"] = str(uuid.uuid4())
    raw, manifest = prepare(tmp_path, fresh_schemas, events)

    with pytest.raises(TransformError, match="key_pass_id"):
        load(fresh_schemas, raw, manifest)

    assert nothing_written(fresh_schemas)


def test_a_substitute_who_is_not_in_the_lineups_rolls_the_match_back(fresh_schemas, tmp_path):
    events = full_scenario()
    next(e for e in events if e["index"] == 1379)["substitution"]["replacement"] = {"id": 424242, "name": "Fantasma"}
    raw, manifest = prepare(tmp_path, fresh_schemas, events)

    with pytest.raises(DatabaseIntegrityError):
        load(fresh_schemas, raw, manifest)

    assert nothing_written(fresh_schemas)


# --------------------------------------------------------------------------- colunas e CLI

@pytest.mark.parametrize("table, columns", [
    ("shots", SHOT_COLUMNS), ("passes", PASS_COLUMNS), ("carries", CARRY_COLUMNS),
    ("cards", CARD_COLUMNS), ("substitutions", SUBSTITUTION_COLUMNS)])
def test_frame_columns_follow_the_table_column_order(schemas, table, columns):
    in_database = [r.column_name for r in rows(
        schemas, "SELECT column_name FROM information_schema.columns "
                 "WHERE table_schema = 'core' AND table_name = :t ORDER BY ordinal_position", t=table)]
    assert list(columns) == in_database


def test_load_command_reports_the_specialized_events(fresh_schemas, db_config, tmp_path, capsys):
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
        assert "events: partida 3869685: 22 eventos | shots 3, passes 4, carries 1, cards 3, substitutions 1" in out
        assert db_config.password not in out
    assert count(fresh_schemas, "passes") == 4
