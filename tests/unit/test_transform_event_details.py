"""Testes de transform/event_details.py: objetos específicos dos eventos -> shots, passes, carries, cards, substitutions.

Fixtures (eventos REAIS da final, copiados sem alteração):
- events_sample.json: 19 eventos; contém 2 finalizações (pênaltis), 3 passes, 1 condução e 3 cartões.
- shot_with_key_pass_sample.json: o passe #2985 do Thuram e o chute #2987 do Mbappé (gol), ligados por `key_pass_id`.
- substitutions_sample.json: as substituições #1378 e #1379 (a primeira troca de cada time, França).
"""

import copy
import json
import uuid
from collections import Counter
from pathlib import Path

import pytest

from oddvision.config import PROJECT_ROOT
from oddvision.transform.common import TransformError
from oddvision.transform.event_details import (
    CARD_COLUMNS,
    CARRY_COLUMNS,
    PASS_COLUMNS,
    SHOT_COLUMNS,
    SUBSTITUTION_COLUMNS,
    cards_frame,
    carries_frame,
    passes_frame,
    shots_frame,
    substitutions_frame,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MATCH = 3869685


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def events():
    return load("events_sample.json")


@pytest.fixture
def pair():
    return load("shot_with_key_pass_sample.json")


@pytest.fixture
def subs():
    return load("substitutions_sample.json")


def source(events, idx):
    return next(e for e in events if e["index"] == idx)


def find(frame, event_id):
    return frame.loc[frame.event_id == uuid.UUID(event_id)].iloc[0]


# --------------------------------------------------------------------------- colunas

def test_columns_follow_the_core_tables():
    assert list(SHOT_COLUMNS) == ["event_id", "statsbomb_xg", "end_x", "end_y", "end_z", "outcome", "shot_type",
                                  "body_part", "technique", "key_pass_id", "extra"]
    assert list(PASS_COLUMNS) == ["event_id", "recipient_id", "end_x", "end_y", "length", "angle", "height", "pass_type",
                                  "body_part", "outcome", "is_complete", "is_cross", "is_switch", "is_through_ball",
                                  "is_shot_assist", "is_goal_assist", "extra"]
    assert list(CARRY_COLUMNS) == ["event_id", "end_x", "end_y"]
    assert list(CARD_COLUMNS) == ["event_id", "card_type"]
    assert list(SUBSTITUTION_COLUMNS) == ["event_id", "player_on_id", "reason"]


def test_each_frame_has_one_row_per_event_of_its_type(events, pair, subs):
    assert len(shots_frame(MATCH, events)) == 2
    assert len(passes_frame(MATCH, events)) == 3
    assert len(carries_frame(MATCH, events)) == 1
    assert len(cards_frame(MATCH, events)) == 3
    assert len(substitutions_frame(MATCH, subs)) == 2
    assert [len(shots_frame(MATCH, pair)), len(passes_frame(MATCH, pair))] == [1, 1]


def test_a_sample_without_events_of_a_type_gives_an_empty_frame_with_its_columns(events):
    frame = substitutions_frame(MATCH, events)  # a amostra de 19 eventos não tem substituições
    assert len(frame) == 0 and list(frame.columns) == list(SUBSTITUTION_COLUMNS)


def test_event_ids_are_uuids_that_point_to_events_of_the_right_type(events):
    by_id = {e["id"]: e for e in events}
    for frame, types in ((shots_frame(MATCH, events), {"Shot"}), (passes_frame(MATCH, events), {"Pass"}),
                         (carries_frame(MATCH, events), {"Carry"}),
                         (cards_frame(MATCH, events), {"Foul Committed", "Bad Behaviour"})):
        assert all(isinstance(v, uuid.UUID) for v in frame.event_id)
        assert {by_id[str(v)]["type"]["name"] for v in frame.event_id} <= types


# --------------------------------------------------------------------------- shots

def test_a_shootout_penalty_is_mapped_as_in_the_source(events):
    s = source(events, 771)
    r = find(shots_frame(MATCH, events), s["id"])
    assert (r.statsbomb_xg, r.end_x, r.end_y, r.end_z) == (0.7835, 120.0, 41.8, 0.2)
    assert (r.outcome, r.shot_type, r.body_part, r.technique) == ("Goal", "Penalty", "Left Foot", "Normal")
    assert r.key_pass_id is None


def test_penalties_have_the_same_xg(events):
    assert set(shots_frame(MATCH, events).statsbomb_xg) == {0.7835}


def test_a_shot_with_a_key_pass_points_to_the_pass_event(pair):
    shot, key_pass = pair[1], pair[0]
    r = find(shots_frame(MATCH, pair), shot["id"])
    assert r.key_pass_id == uuid.UUID(key_pass["id"]) == uuid.UUID(shot["shot"]["key_pass_id"])
    assert (r.outcome, r.shot_type, r.body_part, r.technique) == ("Goal", "Open Play", "Right Foot", "Volley")
    assert (r.statsbomb_xg, r.end_x, r.end_y, r.end_z) == (0.1017027, 120.0, 41.5, 0.3)


def test_the_shot_extra_keeps_the_freeze_frame_flags_and_domain_ids_but_not_the_mapped_keys(pair):
    shot = pair[1]
    extra = find(shots_frame(MATCH, pair), shot["id"]).extra
    assert extra["freeze_frame"] == shot["shot"]["freeze_frame"] and len(extra["freeze_frame"]) > 0
    assert extra["first_time"] is True
    assert extra["type"] == {"id": 87} and extra["outcome"] == {"id": 97}
    assert extra["body_part"] == {"id": 40} and extra["technique"] == {"id": 95}
    assert not {"statsbomb_xg", "end_location", "key_pass_id"} & set(extra)


def test_a_shot_without_height_has_a_null_end_z(events):
    s = source(events, 771)
    s["shot"]["end_location"] = [120.0, 41.8]  # Blocked e Wayward só trazem x e y na fonte
    assert find(shots_frame(MATCH, events), s["id"]).end_z is None


def test_a_missing_optional_shot_attribute_is_null(events):
    s = source(events, 771)
    del s["shot"]["body_part"], s["shot"]["technique"]
    r = find(shots_frame(MATCH, events), s["id"])
    assert r.body_part is None and r.technique is None


@pytest.mark.parametrize("xg", [-0.001, 1.001])
def test_an_xg_outside_0_1_is_rejected_with_the_event(events, xg):
    s = source(events, 771)
    s["shot"]["statsbomb_xg"] = xg
    with pytest.raises(TransformError, match=rf"{s['id']}.*statsbomb_xg"):
        shots_frame(MATCH, events)


def test_a_shot_pointing_to_an_event_that_is_not_in_the_file_is_rejected(pair):
    pair[1]["shot"]["key_pass_id"] = str(uuid.uuid4())
    with pytest.raises(TransformError, match="key_pass_id"):
        shots_frame(MATCH, pair)


def test_an_invalid_key_pass_id_is_rejected(pair):
    pair[1]["shot"]["key_pass_id"] = "não-é-uuid"
    with pytest.raises(TransformError, match="key_pass_id"):
        shots_frame(MATCH, pair)


@pytest.mark.parametrize("end_location", [[120.0], [1.0, 2.0, 3.0, 4.0], ["a", "b"], "120,40"])
def test_an_invalid_shot_end_location_is_rejected(events, end_location):
    source(events, 771)["shot"]["end_location"] = end_location
    with pytest.raises(TransformError, match="end_location"):
        shots_frame(MATCH, events)


# --------------------------------------------------------------------------- passes

def test_a_completed_pass_is_mapped_as_in_the_source(events):
    s = source(events, 88)
    r = find(passes_frame(MATCH, events), s["id"])
    assert (r.recipient_id, r.end_x, r.end_y) == (2995, 116.2, 8.9)
    assert (r.length, r.angle) == (47.816315, -0.5949631)
    assert (r.height, r.pass_type, r.body_part, r.outcome) == ("High Pass", None, "Left Foot", None)
    assert r.is_complete is True
    assert (r.is_cross, r.is_switch, r.is_through_ball, r.is_shot_assist, r.is_goal_assist) == (False,) * 5


def test_a_pass_with_an_outcome_is_incomplete_and_may_have_no_recipient(events):
    s = source(events, 796)
    r = find(passes_frame(MATCH, events), s["id"])
    assert (r.outcome, r.is_complete, r.recipient_id) == ("Incomplete", False, None)


def test_is_complete_is_exactly_the_absence_of_an_outcome(events):
    for r in passes_frame(MATCH, events).itertuples():
        assert r.is_complete == (r.outcome is None)


def test_a_goal_assist_sets_its_flag_and_keeps_the_assisted_shot_in_extra(pair):
    key_pass = pair[0]
    r = find(passes_frame(MATCH, pair), key_pass["id"])
    assert (r.recipient_id, r.is_goal_assist, r.is_shot_assist) == (3009, True, False)
    assert r.extra["assisted_shot_id"] == key_pass["pass"]["assisted_shot_id"] == pair[1]["id"]


def test_the_pass_extra_keeps_domain_ids_but_not_the_recipient_name_nor_mapped_keys(events):
    extra = find(passes_frame(MATCH, events), source(events, 88)["id"]).extra
    assert extra == {"height": {"id": 3}, "body_part": {"id": 38}}  # recipient e demais chaves viraram colunas
    incomplete = find(passes_frame(MATCH, events), source(events, 796)["id"]).extra
    assert incomplete == {"height": {"id": 1}, "body_part": {"id": 38}, "outcome": {"id": 9}}


@pytest.mark.parametrize("flag, column", [("cross", "is_cross"), ("switch", "is_switch"), ("through_ball", "is_through_ball"),
                                          ("shot_assist", "is_shot_assist"), ("goal_assist", "is_goal_assist")])
def test_each_boolean_flag_that_is_present_becomes_true(events, flag, column):
    s = source(events, 88)
    s["pass"][flag] = True
    r = find(passes_frame(MATCH, events), s["id"])
    assert r[column] is True
    assert sum(bool(r[c]) for c in ("is_cross", "is_switch", "is_through_ball", "is_shot_assist", "is_goal_assist")) == 1
    assert flag not in r.extra


def test_the_pass_type_is_the_name_of_the_pass_type_object(events):
    s = source(events, 88)
    s["pass"]["type"] = {"id": 67, "name": "Throw-in"}
    r = find(passes_frame(MATCH, events), s["id"])
    assert r.pass_type == "Throw-in" and r.extra["type"] == {"id": 67}


def test_the_pass_technique_object_stays_whole_in_extra(events):
    s = source(events, 88)
    s["pass"]["technique"] = {"id": 104, "name": "Through Ball"}
    assert find(passes_frame(MATCH, events), s["id"]).extra["technique"] == {"id": 104, "name": "Through Ball"}


@pytest.mark.parametrize("end_location", [[116.2], [116.2, 8.9, 1.0], [120.1, 8.9], [116.2, -0.1], [116.2, 80.1], ["a", "b"]])
def test_an_invalid_or_out_of_pitch_pass_end_location_is_rejected(events, end_location):
    s = source(events, 88)
    s["pass"]["end_location"] = end_location
    with pytest.raises(TransformError, match=rf"{s['id']}.*end_location"):
        passes_frame(MATCH, events)


def test_a_pass_outcome_without_a_name_is_rejected(events):
    s = source(events, 796)
    s["pass"]["outcome"] = {"id": 9}
    with pytest.raises(TransformError, match="outcome"):
        passes_frame(MATCH, events)


def test_a_non_boolean_flag_is_rejected(events):
    source(events, 88)["pass"]["cross"] = "sim"
    with pytest.raises(TransformError, match="cross"):
        passes_frame(MATCH, events)


def test_a_non_numeric_length_is_rejected(events):
    source(events, 88)["pass"]["length"] = "longo"
    with pytest.raises(TransformError, match="length"):
        passes_frame(MATCH, events)


# --------------------------------------------------------------------------- carries

def test_a_carry_keeps_only_its_end_location(events):
    r = carries_frame(MATCH, events).iloc[0]
    assert (r.event_id, r.end_x, r.end_y) == (uuid.UUID(source(events, 86)["id"]), 76.6, 35.7)


def test_a_carry_with_a_key_that_the_model_does_not_have_is_rejected_instead_of_losing_it(events):
    source(events, 86)["carry"]["novidade"] = 1  # a tabela carries não tem extra
    with pytest.raises(TransformError, match="novidade"):
        carries_frame(MATCH, events)


@pytest.mark.parametrize("end_location", [[76.6], [120.1, 35.7], [76.6, 80.1], [-1.0, 0.0]])
def test_an_invalid_carry_end_location_is_rejected(events, end_location):
    source(events, 86)["carry"]["end_location"] = end_location
    with pytest.raises(TransformError, match="end_location"):
        carries_frame(MATCH, events)


# --------------------------------------------------------------------------- cards

def test_each_card_comes_from_foul_committed_or_bad_behaviour(events):
    frame = cards_frame(MATCH, events)
    assert Counter(frame.card_type) == {"Yellow Card": 3}
    expected = {source(events, i)["id"] for i in (3160, 3396, 4401)}  # duas faltas e um Bad Behaviour
    assert {str(v) for v in frame.event_id} == expected


def test_a_foul_without_a_card_gives_no_row(events):
    ids = {str(v) for v in cards_frame(MATCH, events).event_id}
    assert source(events, 250)["id"] not in ids  # Foul Committed sem o objeto foul_committed


def test_a_red_card_name_is_kept_as_is(events):
    source(events, 3396)["foul_committed"]["card"] = {"id": 5, "name": "Red Card"}
    assert find(cards_frame(MATCH, events), source(events, 3396)["id"]).card_type == "Red Card"


def test_a_card_with_a_key_that_the_model_does_not_have_is_rejected(events):
    source(events, 3396)["foul_committed"]["card"]["motivo"] = "x"
    with pytest.raises(TransformError, match="motivo"):
        cards_frame(MATCH, events)


def test_a_card_without_a_name_is_rejected(events):
    source(events, 3396)["foul_committed"]["card"] = {"id": 7}
    with pytest.raises(TransformError, match="name"):
        cards_frame(MATCH, events)


# --------------------------------------------------------------------------- substitutions

def test_substitutions_map_the_player_who_comes_on_and_the_reason(subs):
    frame = substitutions_frame(MATCH, subs)
    by_id = {str(r.event_id): (r.player_on_id, r.reason) for r in frame.itertuples()}
    assert by_id == {subs[0]["id"]: (22097, "Tactical"), subs[1]["id"]: (2972, "Tactical")}


def test_the_substitution_reason_is_optional(subs):
    del subs[0]["substitution"]["outcome"]
    r = find(substitutions_frame(MATCH, subs), subs[0]["id"])
    assert r.reason is None and r.player_on_id == 22097


def test_a_substitution_without_the_replacement_is_rejected(subs):
    del subs[0]["substitution"]["replacement"]
    with pytest.raises(TransformError, match="replacement"):
        substitutions_frame(MATCH, subs)


def test_a_substitution_with_a_key_that_the_model_does_not_have_is_rejected(subs):
    subs[0]["substitution"]["novidade"] = 1
    with pytest.raises(TransformError, match="novidade"):
        substitutions_frame(MATCH, subs)


# --------------------------------------------------------------------------- consistência entre tipo e objeto

@pytest.mark.parametrize("frame_function, key, donor_idx, victim_idx", [
    (shots_frame, "shot", 771, 211),   # um Ball Receipt* ganha o objeto de um chute
    (passes_frame, "pass", 88, 995),   # uma Pressure ganha o objeto de um passe
    (carries_frame, "carry", 86, 211),
])
def test_an_object_on_an_event_of_another_type_is_rejected_instead_of_being_lost(
        events, frame_function, key, donor_idx, victim_idx):
    # O objeto sairia do events.extra (D25) e não iria para nenhuma tabela: seria perdido em silêncio.
    source(events, victim_idx)[key] = copy.deepcopy(source(events, donor_idx)[key])
    with pytest.raises(TransformError, match=key):
        frame_function(MATCH, events)


@pytest.mark.parametrize("frame_function, missing", [(shots_frame, 771), (passes_frame, 88), (carries_frame, 86)])
def test_an_event_of_the_type_without_its_object_is_rejected(events, frame_function, missing):
    event = source(events, missing)
    del event[{771: "shot", 88: "pass", 86: "carry"}[missing]]
    with pytest.raises(TransformError, match=event["id"]):
        frame_function(MATCH, events)


def test_a_substitution_event_without_its_object_is_rejected(subs):
    del subs[0]["substitution"]
    with pytest.raises(TransformError, match=subs[0]["id"]):
        substitutions_frame(MATCH, subs)


def test_transforms_do_not_modify_the_input(events, pair, subs):
    before = copy.deepcopy((events, pair, subs))
    for frame_function in (shots_frame, passes_frame, carries_frame, cards_frame):
        frame_function(MATCH, events)
    shots_frame(MATCH, pair), passes_frame(MATCH, pair), substitutions_frame(MATCH, subs)
    assert (events, pair, subs) == before


# --------------------------------------------------------------------------- dados reais (se baixados)

RAW = PROJECT_ROOT / "data" / "raw" / "statsbomb"
SENTINELS = [3869685, 3857276, 3857271]
# Totais das 3 sentinelas, contados à parte (script independente) no JSON bruto
EXPECTED_TOTALS = {"shots": 71, "passes": 3311, "carries": 2572, "cards": 14, "substitutions": 34}


@pytest.mark.skipif(not (RAW / "events").is_dir(), reason="data/raw não existe (rode a ingestão)")
def test_the_real_events_of_the_sentinels_have_the_known_totals_and_domains():
    totals = Counter()
    outcomes, shot_types, pass_types, pass_outcomes = set(), set(), set(), set()
    for match_id in SENTINELS:
        raw = json.loads((RAW / "events" / f"{match_id}.json").read_text(encoding="utf-8"))
        shots, passes = shots_frame(match_id, raw), passes_frame(match_id, raw)
        totals.update(shots=len(shots), passes=len(passes), carries=len(carries_frame(match_id, raw)),
                      cards=len(cards_frame(match_id, raw)), substitutions=len(substitutions_frame(match_id, raw)))
        assert len(shots) == sum(e["type"]["name"] == "Shot" for e in raw)
        assert len(passes) == sum(e["type"]["name"] == "Pass" for e in raw)
        assert all(r.is_complete == (r.outcome is None) for r in passes.itertuples())
        assert all(r.statsbomb_xg == 0.7835 for r in shots.itertuples() if r.shot_type == "Penalty")
        outcomes |= set(shots.outcome); shot_types |= set(shots.shot_type)
        pass_types |= set(passes.pass_type); pass_outcomes |= set(passes.outcome)
    assert dict(totals) == EXPECTED_TOTALS
    assert outcomes <= {"Blocked", "Goal", "Off T", "Post", "Saved", "Saved Off Target", "Saved to Post", "Wayward"}
    assert shot_types <= {"Open Play", "Free Kick", "Penalty", "Corner"}
    assert pass_types <= {None, "Recovery", "Throw-in", "Free Kick", "Goal Kick", "Corner", "Interception", "Kick Off"}
    assert pass_outcomes <= {None, "Incomplete", "Out", "Unknown", "Pass Offside", "Injury Clearance"}


@pytest.mark.skipif(not (RAW / "events").is_dir(), reason="data/raw não existe (rode a ingestão)")
@pytest.mark.parametrize("match_id", SENTINELS)
def test_the_cards_in_the_events_match_the_cards_in_the_lineups(match_id):
    """Conciliação entre duas fontes do mesmo arquivo de dados (o aviso C09 do Passo 9)."""
    raw = json.loads((RAW / "events" / f"{match_id}.json").read_text(encoding="utf-8"))
    lineups = json.loads((RAW / "lineups" / f"{match_id}.json").read_text(encoding="utf-8"))
    player_of = {e["id"]: e["player"]["id"] for e in raw if "player" in e}
    from_events = Counter((player_of[str(r.event_id)], r.card_type) for r in cards_frame(match_id, raw).itertuples())
    from_lineups = Counter((p["player_id"], c["card_type"]) for t in lineups for p in t["lineup"] for c in p["cards"])
    assert from_events == from_lineups
