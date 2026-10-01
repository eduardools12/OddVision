"""Testes de transform/lineups.py: escalações JSON -> DataFrames de lineups e players.

tests/fixtures/lineups_sample.json: 7 jogadores REAIS da final (3869685), copiados sem alteração:
- França: Mbappé (titular), Thuram (reserva que entrou, 1 cartão), Areola (não entrou).
- Argentina: Messi (titular, `positions` fora de ordem), Acuña (reserva que entrou, 1 cartão,
  `positions` fora de ordem), E. Martínez (goleiro titular, 1 cartão), Armani (não entrou).
"""

import copy
import json
from pathlib import Path

import pytest

from oddvision.config import PROJECT_ROOT
from oddvision.transform.common import TransformError
from oddvision.transform.lineups import (
    LINEUP_COLUMNS,
    PLAYER_COLUMNS,
    AttributeConflict,
    lineups_frame,
    resolve_players,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MATCH = 3869685
FRANCE, ARGENTINA = 771, 779
MBAPPE, THURAM, AREOLA = 3009, 2972, 3379
MESSI, ACUNA, MARTINEZ, ARMANI = 5503, 19597, 6909, 6312


@pytest.fixture
def teams():
    return json.loads((FIXTURES / "lineups_sample.json").read_text(encoding="utf-8"))


def row(frame, player_id):
    return frame.loc[frame.player_id == player_id].iloc[0]


def find(teams, player_id):
    return next(p for t in teams for p in t["lineup"] if p["player_id"] == player_id)


# --------------------------------------------------------------------------- lineups_frame

def test_columns_follow_the_core_table(teams):
    assert list(LINEUP_COLUMNS) == ["match_id", "team_id", "player_id", "jersey_number", "is_starter",
                                    "played", "first_position", "extra"]
    assert list(lineups_frame(MATCH, teams).columns) == list(LINEUP_COLUMNS)


def test_one_row_per_listed_player_sorted_by_team_and_player(teams):
    frame = lineups_frame(MATCH, teams)
    assert [(r.team_id, r.player_id) for r in frame.itertuples()] == [
        (FRANCE, THURAM), (FRANCE, MBAPPE), (FRANCE, AREOLA),
        (ARGENTINA, MESSI), (ARGENTINA, ARMANI), (ARGENTINA, MARTINEZ), (ARGENTINA, ACUNA),
    ]
    assert (frame.match_id == MATCH).all()  # o match_id vem do nome do arquivo, não do conteúdo


@pytest.mark.parametrize("player_id, jersey, starter, played, first_position", [
    (MBAPPE, 10, True, True, "Left Wing"),
    (THURAM, 26, False, True, "Center Forward"),
    (AREOLA, 23, False, False, None),
    (MESSI, 10, True, True, "Right Wing"),
    (ACUNA, 8, False, True, "Left Wing"),
    (MARTINEZ, 23, True, True, "Goalkeeper"),
    (ARMANI, 1, False, False, None),
])
def test_derived_columns_of_the_real_players(teams, player_id, jersey, starter, played, first_position):
    r = row(lineups_frame(MATCH, teams), player_id)
    assert (r.jersey_number, r.is_starter, r.played, r.first_position) == (jersey, starter, played, first_position)


def test_starters_and_players_who_entered_per_team(teams):
    frame = lineups_frame(MATCH, teams)
    by_team = frame.groupby("team_id")
    assert by_team.is_starter.sum().to_dict() == {FRANCE: 1, ARGENTINA: 2}
    assert by_team.played.sum().to_dict() == {FRANCE: 2, ARGENTINA: 3}


def test_a_player_who_did_not_play_is_never_a_starter(teams):
    frame = lineups_frame(MATCH, teams)
    assert not frame.loc[~frame.played.astype(bool), "is_starter"].astype(bool).any()


def test_first_position_is_the_earliest_not_the_first_listed(teams):
    # Acuña: a fonte lista primeiro uma posição da prorrogação (P3), mas ele entrou no 2º tempo (P2 63:51).
    acuna = find(teams, ACUNA)
    assert acuna["positions"][0]["from_period"] == 3 and acuna["positions"][-1]["from_period"] == 2
    acuna["positions"][0]["position"] = "Posição da prorrogação"
    assert row(lineups_frame(MATCH, teams), ACUNA).first_position == "Left Wing"


def test_a_starter_is_recognized_even_if_the_starting_xi_entry_is_not_listed_first(teams):
    find(teams, MBAPPE)["positions"].reverse()
    r = row(lineups_frame(MATCH, teams), MBAPPE)
    assert r.is_starter and r.first_position == "Left Wing"


def test_a_player_whose_first_entry_is_not_the_starting_xi_is_not_a_starter(teams):
    assert not row(lineups_frame(MATCH, teams), THURAM).is_starter  # entrou como 'Substitution - On (Tactical)'


# --------------------------------------------------------------------------- extra

def test_extra_keeps_positions_cards_and_country_id(teams):
    extra = row(lineups_frame(MATCH, teams), THURAM).extra
    assert set(extra) == {"country", "cards", "positions"}
    assert extra["country"] == {"id": 78}  # country.name foi para core.players
    assert extra["cards"][0]["card_type"] == "Yellow Card"
    assert extra["cards"][0]["reason"] == "Foul Committed"


def test_extra_keeps_positions_in_the_source_order(teams):
    positions = find(teams, MESSI)["positions"]
    assert [p["from_period"] for p in positions] == [1, 4, 1]  # fora de ordem na fonte
    assert row(lineups_frame(MATCH, teams), MESSI).extra["positions"] == positions


def test_extra_never_repeats_a_mapped_column(teams):
    for r in lineups_frame(MATCH, teams).itertuples():
        assert not {"player_id", "jersey_number", "player_name", "player_nickname"} & set(r.extra)
        assert "name" not in r.extra["country"]


def test_a_player_who_did_not_play_has_empty_positions_in_extra(teams):
    r = row(lineups_frame(MATCH, teams), AREOLA)
    assert r.extra["positions"] == [] and r.extra["cards"] == []


def test_transforms_do_not_modify_the_input(teams):
    before = copy.deepcopy(teams)
    lineups_frame(MATCH, teams)
    resolve_players({MATCH: teams})
    assert teams == before


# --------------------------------------------------------------------------- dados inválidos

def test_a_file_must_have_exactly_two_teams(teams):
    with pytest.raises(TransformError, match="2 times"):
        lineups_frame(MATCH, teams[:1])
    with pytest.raises(TransformError, match="2 times"):
        lineups_frame(MATCH, [])


def test_the_two_teams_must_be_different(teams):
    teams[1]["team_id"] = teams[0]["team_id"]
    with pytest.raises(TransformError, match="repetido"):
        lineups_frame(MATCH, teams)


def test_a_player_cannot_appear_twice_in_the_same_match(teams):
    teams[0]["lineup"].append(copy.deepcopy(find(teams, MESSI)))
    with pytest.raises(TransformError, match=str(MESSI)):
        lineups_frame(MATCH, teams)


def test_a_player_without_id_is_rejected(teams):
    del teams[0]["lineup"][0]["player_id"]
    with pytest.raises(TransformError, match="player_id"):
        lineups_frame(MATCH, teams)


def test_positions_must_be_a_list(teams):
    teams[0]["lineup"][0]["positions"] = None
    with pytest.raises(TransformError, match="positions"):
        lineups_frame(MATCH, teams)


def test_a_position_without_period_or_clock_is_rejected(teams):
    del find(teams, MBAPPE)["positions"][0]["from_period"]
    with pytest.raises(TransformError, match="from_period"):
        lineups_frame(MATCH, teams)


def test_an_unparseable_clock_is_rejected(teams):
    find(teams, MBAPPE)["positions"][0]["from"] = "meio-dia"
    with pytest.raises(TransformError, match="from"):
        lineups_frame(MATCH, teams)


def test_jersey_number_must_be_an_integer(teams):
    find(teams, MBAPPE)["jersey_number"] = "10"
    with pytest.raises(TransformError, match="jersey_number"):
        lineups_frame(MATCH, teams)


# --------------------------------------------------------------------------- resolve_players

def observed(player_id, name, nickname=None, country="Argentina"):
    return {"player_id": player_id, "player_name": name, "player_nickname": nickname, "jersey_number": 1,
            "country": {"id": 1, "name": country}, "cards": [], "positions": []}


def file_with(*players):
    return [{"team_id": 1, "team_name": "A", "lineup": list(players)}]


def test_resolve_players_has_one_row_per_player_sorted_by_id(teams):
    frame, conflicts = resolve_players({MATCH: teams})
    assert list(frame.columns) == list(PLAYER_COLUMNS)
    assert list(frame.player_id) == sorted([MBAPPE, THURAM, AREOLA, MESSI, ACUNA, MARTINEZ, ARMANI])
    messi = frame.loc[frame.player_id == MESSI].iloc[0]
    assert (messi.player_name, messi.player_nickname, messi.country_name) == (
        "Lionel Andrés Messi Cuccittini", "Lionel Messi", "Argentina")
    assert conflicts == []


def test_the_most_frequent_name_wins():
    files = {1: file_with(observed(7, "Phil Foden")), 2: file_with(observed(7, "Philip Foden")),
             3: file_with(observed(7, "Phil Foden")), 4: file_with(observed(7, "Philip Foden")),
             5: file_with(observed(7, "Phil Foden"))}
    frame, conflicts = resolve_players(files)
    assert frame.iloc[0].player_name == "Phil Foden"
    assert conflicts == [AttributeConflict(7, "player_name", {"Phil Foden": 3, "Philip Foden": 2}, "Phil Foden")]


def test_a_tie_is_broken_by_alphabetical_order():
    files = {1: file_with(observed(7, "Philip Foden")), 2: file_with(observed(7, "Phil Foden"))}
    frame, conflicts = resolve_players(files)
    assert frame.iloc[0].player_name == "Phil Foden"
    assert conflicts[0].chosen == "Phil Foden"


def test_the_result_does_not_depend_on_the_order_of_the_files():
    forward = {1: file_with(observed(7, "B")), 2: file_with(observed(7, "A")), 3: file_with(observed(7, "B"))}
    backward = dict(reversed(list(forward.items())))
    assert resolve_players(forward)[0].equals(resolve_players(backward)[0])
    assert resolve_players(forward)[1] == resolve_players(backward)[1]


def test_a_null_nickname_does_not_compete_with_a_real_one():
    files = {1: file_with(observed(7, "M", nickname=None)), 2: file_with(observed(7, "M", nickname="Matt")),
             3: file_with(observed(7, "M", nickname=None))}
    frame, conflicts = resolve_players(files)
    assert frame.iloc[0].player_nickname == "Matt"  # 2 nulos contra 1 valor: o valor vence
    assert conflicts == [AttributeConflict(7, "player_nickname", {None: 2, "Matt": 1}, "Matt")]


def test_a_nickname_that_is_always_null_stays_null_without_a_conflict():
    frame, conflicts = resolve_players({1: file_with(observed(7, "M")), 2: file_with(observed(7, "M"))})
    assert frame.iloc[0].player_nickname is None
    assert conflicts == []


def test_the_country_uses_the_same_rule():
    files = {i: file_with(observed(7, "Z", country=c)) for i, c in enumerate(["Morocco"] * 3 + ["Belgium"] * 4)}
    frame, conflicts = resolve_players(files)
    assert frame.iloc[0].country_name == "Belgium"
    assert conflicts == [AttributeConflict(7, "country_name", {"Morocco": 3, "Belgium": 4}, "Belgium")]


def test_conflicts_are_sorted_by_player_and_attribute():
    files = {1: file_with(observed(9, "B", country="X"), observed(3, "A")),
             2: file_with(observed(9, "A", country="Y"), observed(3, "B"))}
    _, conflicts = resolve_players(files)
    assert [(c.player_id, c.attribute) for c in conflicts] == [
        (3, "player_name"), (9, "country_name"), (9, "player_name")]


def test_resolve_players_names_the_match_of_a_malformed_player():
    bad = observed(7, "X")
    del bad["player_name"]
    with pytest.raises(TransformError, match="1234"):
        resolve_players({1234: file_with(bad)})


# --------------------------------------------------------------------------- dados reais (se baixados)

RAW_LINEUPS = PROJECT_ROOT / "data" / "raw" / "statsbomb" / "lineups"


@pytest.mark.skipif(not RAW_LINEUPS.is_dir(), reason="data/raw não existe (rode a ingestão)")
def test_the_real_lineups_have_11_starters_per_team_and_the_known_conflicts():
    files = {int(p.stem): json.loads(p.read_text(encoding="utf-8")) for p in RAW_LINEUPS.glob("*.json")}
    assert len(files) == 64

    for match_id, teams in files.items():
        frame = lineups_frame(match_id, teams)
        assert len(frame) == sum(len(t["lineup"]) for t in teams)  # nenhuma linha perdida
        assert frame.groupby("team_id").is_starter.sum().tolist() == [11, 11], match_id

    players, conflicts = resolve_players(files)
    assert len(players) == 829
    chosen = {(c.player_id, c.attribute): c.chosen for c in conflicts}
    assert chosen == {
        (4354, "player_name"): "Phil Foden", (50494, "player_name"): "Yeremy Jesús Pino Santos",
        (10603, "player_name"): "Mamadou Loum N'Diaye", (24475, "player_name"): "Awer Denis Bul Mabil",
        (12352, "player_nickname"): "Matt Turner", (11184, "player_nickname"): "Otavinho",
        (131037, "country_name"): "Belgium",
    }
