"""Testes de transform/matches.py: JSON da fonte -> DataFrames de competitions, teams e matches.

As amostras em tests/fixtures/ são objetos COPIADOS SEM ALTERAÇÃO da fonte (commit 4b73468f):
- matches_sample.json: a final (3869685), Argentina x Austrália (3869151, repete o time Argentina)
  e Espanha x Costa Rica (3857291, a única partida sem a chave `referee`).
- competitions_sample.json: Copa do Mundo 2022 (43/106) e La Liga 2020/21 (11/90).
"""

import copy
import json
from datetime import date, datetime, time
from pathlib import Path

import pytest

from oddvision.config import PROJECT_ROOT
from oddvision.transform.common import TransformError
from oddvision.transform.matches import (
    COMPETITION_COLUMNS,
    MATCH_COLUMNS,
    TEAM_COLUMNS,
    competitions_frame,
    matches_frame,
    teams_frame,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FINAL, ARG_AUS, NO_REFEREE = 3869685, 3869151, 3857291


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def matches_json():
    return load_fixture("matches_sample.json")


@pytest.fixture
def competitions_json():
    return load_fixture("competitions_sample.json")


def row(frame, match_id):
    return frame.loc[frame.match_id == match_id].iloc[0]


# --------------------------------------------------------------------------- competitions

def test_competitions_frame_selects_only_the_requested_pair(competitions_json):
    frame = competitions_frame(competitions_json, 43, 106)
    assert list(frame.columns) == list(COMPETITION_COLUMNS)
    assert len(frame) == 1
    r = frame.iloc[0]
    assert (r.competition_id, r.season_id) == (43, 106)
    assert (r.competition_name, r.season_name, r.country_name) == ("FIFA World Cup", "2022", "International")
    assert (r.competition_gender, r.competition_youth, r.competition_international) == ("male", False, True)


def test_competitions_extra_keeps_only_what_is_not_mapped(competitions_json):
    r = competitions_frame(competitions_json, 43, 106).iloc[0]
    assert set(r.extra) == {"match_updated", "match_updated_360", "match_available", "match_available_360"}


def test_competitions_frame_fails_when_the_pair_does_not_exist(competitions_json):
    with pytest.raises(TransformError, match=r"99.*1"):
        competitions_frame(competitions_json, 99, 1)


def test_competitions_frame_fails_when_the_pair_is_duplicated(competitions_json):
    with pytest.raises(TransformError, match="mais de uma"):
        competitions_frame(competitions_json + [competitions_json[0]], 43, 106)


# --------------------------------------------------------------------------- teams

def test_teams_frame_has_one_row_per_team_sorted_by_id(matches_json):
    frame = teams_frame(matches_json)
    assert list(frame.columns) == list(TEAM_COLUMNS)
    # Argentina aparece em duas partidas e conta uma vez
    assert list(frame.team_id) == [771, 772, 779, 792, 795]
    argentina = frame.loc[frame.team_id == 779].iloc[0]
    assert (argentina.team_name, argentina.team_gender, argentina.country_name) == ("Argentina", "male", "Argentina")


def test_teams_frame_rejects_the_same_team_with_different_attributes(matches_json):
    matches_json[1]["home_team"]["home_team_name"] = "Argentine"  # 779 passa a ter dois nomes
    with pytest.raises(TransformError, match="779"):
        teams_frame(matches_json)


# --------------------------------------------------------------------------- matches

def test_matches_frame_columns_follow_the_core_table(matches_json):
    assert list(MATCH_COLUMNS) == [
        "match_id", "competition_id", "season_id", "match_date", "kick_off", "home_team_id", "away_team_id",
        "home_score", "away_score", "match_week", "competition_stage", "stadium_name", "referee_name",
        "match_status", "data_version", "shot_fidelity_version", "xy_fidelity_version", "last_updated", "extra",
    ]
    assert list(matches_frame(matches_json, 43, 106).columns) == list(MATCH_COLUMNS)


def test_matches_frame_is_sorted_by_match_id(matches_json):
    assert list(matches_frame(matches_json, 43, 106).match_id) == [NO_REFEREE, ARG_AUS, FINAL]


def test_the_final_is_typed_and_mapped_as_in_the_source(matches_json):
    r = row(matches_frame(matches_json, 43, 106), FINAL)
    assert (r.competition_id, r.season_id) == (43, 106)
    assert r.match_date == date(2022, 12, 18)
    assert r.kick_off == time(17, 0)
    assert (r.home_team_id, r.away_team_id) == (779, 771)
    assert (r.home_score, r.away_score) == (3, 3)
    assert r.match_week == 7
    assert r.competition_stage == "Final"
    assert r.stadium_name == "Lusail Stadium"
    assert r.referee_name == "Szymon Marciniak"
    assert r.match_status == "available"
    assert (r.data_version, r.shot_fidelity_version, r.xy_fidelity_version) == ("1.1.0", "2", "2")
    assert r.last_updated == datetime(2024, 12, 16, 10, 15, 11, 55845)
    assert r.last_updated.tzinfo is None  # a coluna é TIMESTAMP, sem fuso


def test_a_match_without_the_referee_key_gets_a_null_referee(matches_json):
    r = row(matches_frame(matches_json, 43, 106), NO_REFEREE)
    assert r.referee_name is None
    assert "referee" not in r.extra


def test_extra_keeps_what_the_source_has_and_the_model_does_not_use(matches_json):
    extra = row(matches_frame(matches_json, 43, 106), FINAL).extra
    assert set(extra) == {"home_team", "away_team", "stadium", "referee", "competition_stage",
                          "match_status_360", "last_updated_360"}
    assert extra["home_team"]["managers"][0]["id"] == 5677
    assert extra["home_team"]["country"] == {"id": 11}  # country.name foi mapeado para core.teams
    assert extra["home_team"]["home_team_group"] is None
    assert extra["away_team"]["managers"][0]["id"] == 545
    assert extra["stadium"] == {"id": 1001114, "country": {"id": 185, "name": "Qatar"}}
    assert extra["referee"] == {"id": 367, "country": {"id": 182, "name": "Poland"}}
    assert extra["competition_stage"] == {"id": 26}
    assert extra["match_status_360"] == "available"
    assert extra["last_updated_360"] == "2024-12-16T10:21:13.710934"


def test_extra_never_repeats_a_mapped_column(matches_json):
    for _, r in matches_frame(matches_json, 43, 106).iterrows():
        assert not {"match_id", "match_date", "kick_off", "home_score", "away_score", "match_week",
                    "match_status", "last_updated", "metadata", "competition", "season"} & set(r.extra)
        assert "home_team_id" not in r.extra["home_team"] and "home_team_name" not in r.extra["home_team"]
        assert "name" not in r.extra["competition_stage"] and "name" not in r.extra["stadium"]


def test_group_is_preserved_for_group_stage_matches(matches_json):
    assert row(matches_frame(matches_json, 43, 106), NO_REFEREE).extra["home_team"]["home_team_group"] == "E"


def test_transforms_do_not_modify_the_input(matches_json, competitions_json):
    before_matches, before_competitions = copy.deepcopy(matches_json), copy.deepcopy(competitions_json)
    matches_frame(matches_json, 43, 106)
    teams_frame(matches_json)
    competitions_frame(competitions_json, 43, 106)
    assert matches_json == before_matches and competitions_json == before_competitions


# --------------------------------------------------------------------------- dados inválidos

def test_missing_required_field_names_the_match_and_the_field(matches_json):
    del matches_json[0]["home_score"]
    with pytest.raises(TransformError, match=rf"{FINAL}.*home_score"):
        matches_frame(matches_json, 43, 106)


def test_null_required_field_is_rejected(matches_json):
    matches_json[0]["match_date"] = None
    with pytest.raises(TransformError, match="match_date"):
        matches_frame(matches_json, 43, 106)


def test_missing_optional_fields_become_null(matches_json):
    for key in ("kick_off", "match_week", "stadium", "last_updated", "metadata"):
        matches_json[0].pop(key)
    r = row(matches_frame(matches_json, 43, 106), FINAL)
    for column in ("kick_off", "match_week", "stadium_name", "last_updated", "data_version"):
        assert r[column] is None


def test_scores_must_be_integers(matches_json):
    matches_json[0]["home_score"] = "3"
    with pytest.raises(TransformError, match="home_score"):
        matches_frame(matches_json, 43, 106)


def test_unparseable_date_is_rejected(matches_json):
    matches_json[0]["match_date"] = "18/12/2022"
    with pytest.raises(TransformError, match="match_date"):
        matches_frame(matches_json, 43, 106)


def test_timestamp_with_a_timezone_is_rejected(matches_json):
    matches_json[0]["last_updated"] = "2024-12-16T10:15:11Z"
    with pytest.raises(TransformError, match="fuso"):
        matches_frame(matches_json, 43, 106)


def test_match_from_another_competition_is_rejected(matches_json):
    matches_json[0]["competition"]["competition_id"] = 11
    with pytest.raises(TransformError, match="competição"):
        matches_frame(matches_json, 43, 106)


def test_duplicate_match_ids_are_rejected(matches_json):
    with pytest.raises(TransformError, match=str(FINAL)):
        matches_frame(matches_json + [matches_json[0]], 43, 106)


def test_an_empty_matches_file_is_rejected():
    with pytest.raises(TransformError, match="nenhuma partida"):
        matches_frame([], 43, 106)


# --------------------------------------------------------------------------- dados reais (se baixados)

RAW_MATCHES = PROJECT_ROOT / "data" / "raw" / "statsbomb" / "matches" / "43" / "106.json"


@pytest.mark.skipif(not RAW_MATCHES.exists(), reason="data/raw não existe (rode a ingestão)")
def test_the_real_matches_file_transforms_cleanly():
    matches = json.loads(RAW_MATCHES.read_text(encoding="utf-8"))
    frame = matches_frame(matches, 43, 106)
    assert len(frame) == 64
    assert len(teams_frame(matches)) == 32
    assert frame.referee_name.isna().sum() == 1  # só a 3857291 não tem árbitro
    assert (frame.home_team_id != frame.away_team_id).all()
