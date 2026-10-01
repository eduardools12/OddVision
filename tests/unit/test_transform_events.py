"""Testes de transform/events.py: events/{match_id}.json -> DataFrame de core.events.

tests/fixtures/events_sample.json: 19 eventos REAIS da final (3869685), copiados sem alteração, escolhidos
para cobrir os casos difíceis: sem `location` (Starting XI, Half Start, Player On/Off, Tactical Shift, Bad
Behaviour), sem `player`, sem `duration` (Ball Receipt*), com `under_pressure`, período 5 (disputa de pênaltis),
posse de outro time, faltas com cartão, só com cartão e sem o objeto `foul_committed`, e eventos com objeto
próprio (shot, pass, carry, duel, goalkeeper, tactics). Só jogadores da amostra de escalações aparecem.
"""

import copy
import json
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from oddvision.config import PROJECT_ROOT
from oddvision.transform.common import TransformError
from oddvision.transform.events import EVENT_COLUMNS, events_frame

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MATCH = 3869685
ARGENTINA, FRANCE = 779, 771
MESSI, MBAPPE, THURAM, ACUNA, MARTINEZ = 5503, 3009, 2972, 19597, 6909

# idx dos eventos da amostra, por característica
PASS_OF_MESSI, CARRY, SHOT_P1, SHOT_SHOOTOUT, BAD_BEHAVIOUR = 88, 86, 771, 4391, 4401
STARTING_XI, HALF_START, TACTICAL_SHIFT, PLAYER_OFF, PLAYER_ON = 1, 3, 1385, 865, 867
RECEIPT, PRESSURE, DUEL, GOALKEEPER, OFF_CAMERA_PASS = 211, 995, 1521, 465, 466
FOUL_NO_OBJECT, FOUL_CARD_AND_MORE, FOUL_ONLY_CARD = 250, 3160, 3396
NO_LOCATION = {STARTING_XI, HALF_START, TACTICAL_SHIFT, PLAYER_OFF, PLAYER_ON, BAD_BEHAVIOUR}
NO_PLAYER = {STARTING_XI, HALF_START, TACTICAL_SHIFT}
UNDER_PRESSURE = {CARRY, PASS_OF_MESSI, DUEL}


@pytest.fixture
def events():
    return json.loads((FIXTURES / "events_sample.json").read_text(encoding="utf-8"))


def source(events, idx):
    return next(e for e in events if e["index"] == idx)


def row(frame, idx):
    return frame.loc[frame.idx == idx].iloc[0]


def leaf_paths(node, prefix=()):
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from leaf_paths(value, prefix + (key,))
    else:
        yield prefix


# --------------------------------------------------------------------------- estrutura

def test_columns_follow_the_core_table(events):
    assert list(EVENT_COLUMNS) == [
        "event_id", "match_id", "idx", "period", "ts_in_period", "minute", "second", "type_name", "team_id",
        "player_id", "position_name", "possession", "possession_team_id", "play_pattern", "x", "y", "duration",
        "under_pressure", "extra",
    ]
    assert list(events_frame(MATCH, events).columns) == list(EVENT_COLUMNS)


def test_one_row_per_event_sorted_by_idx(events):
    frame = events_frame(MATCH, events)
    assert len(frame) == len(events) == 19
    assert list(frame.idx) == sorted(e["index"] for e in events)
    assert (frame.match_id == MATCH).all()  # vem do nome do arquivo: o JSON de eventos não o contém


def test_the_rows_are_sorted_even_if_the_file_is_not(events):
    events.reverse()
    assert list(events_frame(MATCH, events).idx) == sorted(e["index"] for e in events)


# --------------------------------------------------------------------------- colunas tipadas

def test_a_pass_is_typed_and_mapped_as_in_the_source(events):
    r = row(events_frame(MATCH, events), PASS_OF_MESSI)
    assert r.event_id == uuid.UUID(source(events, PASS_OF_MESSI)["id"])
    assert (r.idx, r.period, r.minute, r.second) == (88, 1, 2, 16)
    assert r.ts_in_period == timedelta(seconds=136, microseconds=985000)
    assert (r.type_name, r.team_id, r.player_id, r.position_name) == ("Pass", ARGENTINA, MESSI, "Right Wing")
    assert (r.possession, r.possession_team_id, r.play_pattern) == (8, ARGENTINA, "From Throw In")
    assert (r.x, r.y, r.duration, r.under_pressure) == (76.6, 35.7, 4.15978, True)


def test_every_event_id_is_a_uuid_equal_to_the_source(events):
    frame = events_frame(MATCH, events)
    assert all(isinstance(value, uuid.UUID) for value in frame.event_id)
    assert {str(value) for value in frame.event_id} == {e["id"] for e in events}


@pytest.mark.parametrize("text, expected", [
    ("00:02:16.985", timedelta(seconds=136, microseconds=985000)),
    ("00:00:00.000", timedelta(0)),
    ("01:02:03.500", timedelta(hours=1, minutes=2, seconds=3, microseconds=500000)),
    ("00:00:39", timedelta(seconds=39)),
    ("00:00:39.2", timedelta(seconds=39, microseconds=200000)),
    ("00:00:00.001", timedelta(microseconds=1000)),  # sem arredondamento de ponto flutuante
    ("00:00:00.123456", timedelta(microseconds=123456)),
])
def test_timestamp_becomes_an_exact_interval(events, text, expected):
    events[0]["timestamp"] = text
    assert row(events_frame(MATCH, events), events[0]["index"]).ts_in_period == expected


@pytest.mark.parametrize("text", ["39.227", "aa:bb:cc", "", "00:00", "00:00:61.000", "00:60:00.000", None, 39.2])
def test_an_invalid_timestamp_is_rejected(events, text):
    events[0]["timestamp"] = text
    with pytest.raises(TransformError, match="timestamp"):
        events_frame(MATCH, events)


def test_events_without_location_have_null_x_and_y(events):
    frame = events_frame(MATCH, events)
    assert set(frame.loc[frame.x.isna() & frame.y.isna(), "idx"]) == NO_LOCATION
    assert frame.x.map(lambda v: v is None).sum() == len(NO_LOCATION)  # None de verdade, não NaN


def test_events_without_player_have_null_player_and_position(events):
    frame = events_frame(MATCH, events)
    assert {r.idx for r in frame.itertuples() if r.player_id is None} == NO_PLAYER
    assert {r.idx for r in frame.itertuples() if r.position_name is None} == NO_PLAYER


def test_a_missing_duration_is_null_but_a_zero_duration_is_kept(events):
    frame = events_frame(MATCH, events)
    assert row(frame, RECEIPT).duration is None  # Ball Receipt* nunca tem duration
    assert row(frame, STARTING_XI).duration == 0.0  # zero é um valor, não ausência


def test_under_pressure_is_false_when_the_key_is_absent(events):
    frame = events_frame(MATCH, events)
    assert {r.idx for r in frame.itertuples() if r.under_pressure} == UNDER_PRESSURE
    assert all(isinstance(v, bool) for v in frame.under_pressure)


def test_the_shootout_events_are_period_5(events):
    frame = events_frame(MATCH, events)
    assert set(frame.loc[frame.period == 5, "idx"]) == {SHOT_SHOOTOUT, BAD_BEHAVIOUR}
    assert row(frame, SHOT_SHOOTOUT).minute == 121  # o minuto continua contando depois da prorrogação


def test_the_possession_team_can_differ_from_the_team(events):
    r = row(events_frame(MATCH, events), HALF_START)
    assert (r.team_id, r.possession_team_id) == (FRANCE, ARGENTINA)


def test_coordinates_are_floats_even_if_the_source_has_integers(events):
    source(events, PASS_OF_MESSI)["location"] = [60, 40]
    r = row(events_frame(MATCH, events), PASS_OF_MESSI)
    assert (r.x, r.y) == (60.0, 40.0) and isinstance(r.x, float)


# --------------------------------------------------------------------------- extra

MAPPED_KEYS = {"id", "index", "period", "timestamp", "minute", "second", "location", "duration", "under_pressure", "possession"}


def test_extra_never_repeats_a_mapped_column_nor_an_object_with_its_own_table(events):
    for r in events_frame(MATCH, events).itertuples():
        assert not MAPPED_KEYS & set(r.extra), r.idx
        assert not {"shot", "pass", "carry", "substitution"} & set(r.extra), r.idx


def test_extra_keeps_the_domain_ids_but_not_the_names_that_the_dimensions_already_have(events):
    s = source(events, PASS_OF_MESSI)
    extra = row(events_frame(MATCH, events), PASS_OF_MESSI).extra
    assert extra["type"] == {"id": 30}
    assert extra["position"] == {"id": s["position"]["id"]}
    assert extra["play_pattern"] == {"id": s["play_pattern"]["id"]}
    assert extra["related_events"] == s["related_events"]
    assert not {"team", "player", "possession_team"} & set(extra)  # já estão em core.teams e core.players


def test_extra_keeps_flags_and_the_objects_of_types_without_a_table(events):
    frame = events_frame(MATCH, events)
    assert row(frame, OFF_CAMERA_PASS).extra["off_camera"] is source(events, OFF_CAMERA_PASS)["off_camera"]
    assert row(frame, FOUL_ONLY_CARD).extra["counterpress"] is True
    assert row(frame, DUEL).extra["duel"] == source(events, DUEL)["duel"]
    assert row(frame, GOALKEEPER).extra["goalkeeper"] == source(events, GOALKEEPER)["goalkeeper"]
    assert row(frame, STARTING_XI).extra["tactics"] == source(events, STARTING_XI)["tactics"]
    assert row(frame, TACTICAL_SHIFT).extra["tactics"] == source(events, TACTICAL_SHIFT)["tactics"]


def test_cards_leave_the_extra_but_the_other_foul_keys_stay(events):
    frame = events_frame(MATCH, events)
    original = source(events, FOUL_CARD_AND_MORE)["foul_committed"]
    assert "card" in original and len(original) > 1
    assert row(frame, FOUL_CARD_AND_MORE).extra["foul_committed"] == {k: v for k, v in original.items() if k != "card"}
    # só tinha o cartão: o objeto vazio é podado
    assert list(source(events, FOUL_ONLY_CARD)["foul_committed"]) == ["card"]
    assert "foul_committed" not in row(frame, FOUL_ONLY_CARD).extra
    assert "bad_behaviour" not in row(frame, BAD_BEHAVIOUR).extra
    # uma falta simples nem tem o objeto: nada a remover, nada a inventar
    assert "foul_committed" not in source(events, FOUL_NO_OBJECT)
    assert "foul_committed" not in row(frame, FOUL_NO_OBJECT).extra


def test_nothing_is_lost_except_what_is_documented(events):
    """Tudo que sai do extra é uma coluna, um objeto de tabela própria, um cartão ou um nome já presente nas dimensões."""
    removed_prefixes = [
        ("id",), ("index",), ("period",), ("timestamp",), ("minute",), ("second",), ("possession",), ("location",),
        ("duration",), ("under_pressure",), ("type", "name"), ("team",), ("player",), ("possession_team",),
        ("position", "name"), ("play_pattern", "name"), ("shot",), ("pass",), ("carry",), ("substitution",),
        ("foul_committed", "card"), ("bad_behaviour", "card"),
    ]
    for r in events_frame(MATCH, events).itertuples():
        s = source(events, r.idx)
        extra_leaves = set(leaf_paths(r.extra))
        source_leaves = set(leaf_paths(s))
        assert extra_leaves <= source_leaves, r.idx  # nada inventado
        for leaf in source_leaves - extra_leaves:  # tudo que sumiu foi removido de propósito
            assert any(leaf[: len(prefix)] == prefix for prefix in removed_prefixes), (r.idx, leaf)


def test_transforms_do_not_modify_the_input(events):
    before = copy.deepcopy(events)
    events_frame(MATCH, events)
    assert events == before


# --------------------------------------------------------------------------- dados inválidos

def test_an_empty_file_is_rejected():
    with pytest.raises(TransformError, match="nenhum evento"):
        events_frame(MATCH, [])
    with pytest.raises(TransformError, match="lista"):
        events_frame(MATCH, {"id": "x"})


def test_a_missing_id_names_the_match_and_the_position(events):
    del events[2]["id"]
    with pytest.raises(TransformError, match=rf"{MATCH}.*id"):
        events_frame(MATCH, events)


def test_an_id_that_is_not_a_uuid_is_rejected(events):
    events[0]["id"] = "não-é-uuid"
    with pytest.raises(TransformError, match="id"):
        events_frame(MATCH, events)


def test_a_repeated_id_is_rejected(events):
    events[1]["id"] = events[0]["id"]
    with pytest.raises(TransformError, match="id repetido"):
        events_frame(MATCH, events)


def test_a_repeated_index_is_rejected(events):
    events[1]["index"] = events[0]["index"]
    with pytest.raises(TransformError, match="index repetido"):
        events_frame(MATCH, events)


@pytest.mark.parametrize("field, value", [("period", 0), ("period", 6), ("second", 60), ("second", -1)])
def test_values_that_the_database_would_refuse_are_rejected_with_the_event(events, field, value):
    events[2][field] = value
    with pytest.raises(TransformError, match=rf"{events[2]['id']}.*{field}"):
        events_frame(MATCH, events)


@pytest.mark.parametrize("location", [[1.0], [1.0, 2.0, 3.0], ["a", "b"], [True, 1.0], "60,40", [120.1, 40.0], [60.0, -0.1], [-0.1, 40.0], [60.0, 80.1]])
def test_an_invalid_location_is_rejected_with_the_event(events, location):
    source(events, PASS_OF_MESSI)["location"] = location
    with pytest.raises(TransformError, match=r"1552304a|location"):
        events_frame(MATCH, events)


@pytest.mark.parametrize("path", [("team", "id"), ("type", "name"), ("possession",), ("possession_team", "id"), ("play_pattern", "name"), ("minute",), ("index",)])
def test_a_missing_required_field_is_rejected(events, path):
    node = events[2]
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    with pytest.raises(TransformError, match=path[-1]):
        events_frame(MATCH, events)


def test_a_wrong_type_is_rejected(events):
    events[2]["minute"] = 2.5
    with pytest.raises(TransformError, match="minute"):
        events_frame(MATCH, events)
    events[2]["minute"] = 2
    events[2]["under_pressure"] = "sim"
    with pytest.raises(TransformError, match="under_pressure"):
        events_frame(MATCH, events)
    events[2]["under_pressure"] = True
    events[2]["duration"] = "rápido"
    with pytest.raises(TransformError, match="duration"):
        events_frame(MATCH, events)


# --------------------------------------------------------------------------- dados reais (se baixados)

RAW_EVENTS = PROJECT_ROOT / "data" / "raw" / "statsbomb" / "events"
SENTINELS = [3869685, 3857276, 3857271]


@pytest.mark.skipif(not RAW_EVENTS.is_dir(), reason="data/raw não existe (rode a ingestão)")
@pytest.mark.parametrize("match_id", SENTINELS)
def test_the_real_events_of_the_sentinels_transform_without_losing_a_row(match_id):
    raw = json.loads((RAW_EVENTS / f"{match_id}.json").read_text(encoding="utf-8"))
    frame = events_frame(match_id, raw)

    assert len(frame) == len(raw)  # nenhum evento perdido
    assert frame.event_id.nunique() == len(raw) and frame.idx.nunique() == len(raw)
    assert Counter(frame.type_name) == Counter(e["type"]["name"] for e in raw)  # contagem por tipo, contada à parte
    assert Counter(frame.period) == Counter(e["period"] for e in raw)
    assert frame.x.isna().sum() == sum("location" not in e for e in raw)
    assert frame.player_id.isna().sum() == sum("player" not in e for e in raw)


@pytest.mark.skipif(not RAW_EVENTS.is_dir(), reason="data/raw não existe (rode a ingestão)")
def test_the_real_final_has_4407_events():
    raw = json.loads((RAW_EVENTS / "3869685.json").read_text(encoding="utf-8"))
    assert len(events_frame(3869685, raw)) == 4407
