"""Views da página da partida: analytics.match_lineups (escalações) e analytics.match_timeline (gols, cartões e
substituições), mais o relógio de eventos (analytics.event_clock) que as duas e o gráfico de xG compartilham.
"""

import pytest
from sqlalchemy import text


def rows(conn, sql, **params):
    return conn.execute(text(sql), params).all()


def card(world, idx, team, player, card_type, **kwargs):
    event_id = world.event(idx, "Foul Committed", team, player, **kwargs)
    world.run("INSERT INTO core.cards (event_id, card_type) VALUES (:e, :c)", e=event_id, c=card_type)
    return event_id


def substitution(world, idx, team, player_off, player_on, reason="Tactical", **kwargs):
    event_id = world.event(idx, "Substitution", team, player_off, **kwargs)
    world.run("INSERT INTO core.substitutions (event_id, player_on_id, reason) VALUES (:e, :on, :r)", e=event_id, on=player_on, r=reason)
    return event_id


def timeline(conn, match_id=100):
    return rows(conn, "SELECT * FROM analytics.match_timeline WHERE match_id = :m ORDER BY period, idx", m=match_id)


# --------------------------------------------------------------------------- match_lineups

def test_match_lineups_has_one_row_per_listed_player_with_the_names(world, analytics):
    world.seed()
    columns = [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = 'match_lineups' ORDER BY ordinal_position")]
    assert columns == ["match_id", "team_id", "team_name", "player_id", "player_name", "player_nickname", "jersey_number",
                       "is_starter", "played", "first_position"]
    lineup = rows(analytics, "SELECT * FROM analytics.match_lineups ORDER BY team_id, player_id")
    assert [(r.team_id, r.player_id, r.team_name, r.is_starter, r.played) for r in lineup] == [
        (1, 11, "Casa", True, True), (1, 12, "Casa", True, True), (1, 13, "Casa", False, False),
        (2, 21, "Fora", True, True), (2, 22, "Fora", True, True), (2, 23, "Fora", False, False)]
    assert lineup[0].player_name == "Jogador 11"


def test_match_lineups_carries_shirt_number_nickname_and_position(world, analytics):
    world.seed()
    world.run("UPDATE core.players SET player_nickname = 'Apelido' WHERE player_id = 11")
    world.run("UPDATE core.lineups SET jersey_number = 10, first_position = 'Center Forward' WHERE player_id = 11")
    r = rows(analytics, "SELECT * FROM analytics.match_lineups WHERE player_id = 11")[0]
    assert (r.player_nickname, r.jersey_number, r.first_position) == ("Apelido", 10, "Center Forward")


def test_match_lineups_covers_every_match_that_has_a_lineup_and_none_without(world, analytics):
    world.seed()
    world.match(101, 1, 2, lineups=False)
    assert {r.match_id for r in rows(analytics, "SELECT DISTINCT match_id FROM analytics.match_lineups")} == {100}


# --------------------------------------------------------------------------- event_clock

def test_event_clock_has_every_valid_time_event_and_nothing_from_the_shootout(world, analytics):
    world.seed()
    world.event(1, "Pass", 1, 11, period=1)
    world.event(2, "Pass", 1, 11, period=4)
    world.event(3, "Pass", 1, 11, period=5)
    assert [r.period for r in rows(analytics, "SELECT period FROM analytics.event_clock ORDER BY period")] == [1, 4]


# --------------------------------------------------------------------------- match_timeline: incidentes

def test_match_timeline_has_the_columns_the_page_needs(world, analytics):
    world.seed()
    columns = [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = 'match_timeline' ORDER BY ordinal_position")]
    assert columns == ["match_id", "event_id", "idx", "period", "minute", "second", "tempo_decorrido_s", "minuto_futebol", "rotulo",
                       "incident_type", "detail", "team_id", "team_name", "player_id", "player_name", "related_player_id",
                       "related_player_name"]


def test_only_the_incidents_appear_and_the_shots_that_are_not_goals_do_not(world, analytics):
    world.seed()
    world.event(1, "Pass", 1, 11)
    world.shot(2, 1, 11, outcome="Saved")
    world.shot(3, 1, 12, outcome="Goal", ts=1500)
    world.event(4, "Pressure", 2, 21)
    assert [(r.incident_type, r.player_id) for r in timeline(analytics)] == [("Goal", 12)]


def test_a_goal_has_the_scorer_the_team_and_the_football_label(world, analytics):
    world.seed()
    event_id = world.shot(1, 1, 12, outcome="Goal")
    world.run("UPDATE core.events SET minute = 22 WHERE event_id = :e", e=event_id)
    r = timeline(analytics)[0]
    assert (r.incident_type, r.detail, r.team_id, r.team_name, r.player_id, r.player_name, r.rotulo, r.minuto_futebol) == (
        "Goal", None, 1, "Casa", 12, "Jogador 12", "23'", 23)


def test_a_penalty_goal_is_flagged_in_the_detail(world, analytics):
    world.seed()
    world.shot(1, 1, 11, outcome="Goal", shot_type="Penalty")
    world.shot(2, 1, 11, outcome="Goal", shot_type="Open Play")
    assert [r.detail for r in timeline(analytics)] == ["Penalty", None]


def test_a_shootout_goal_is_not_an_incident(world, analytics):
    world.seed()
    world.shot(1, 1, 11, outcome="Goal", shot_type="Penalty", period=5)
    assert timeline(analytics) == []


def test_an_own_goal_belongs_to_the_beneficiary_team_and_has_no_player(world, analytics):
    world.seed()
    world.event(1, "Own Goal For", 2, None)
    r = timeline(analytics)[0]
    assert (r.incident_type, r.team_id, r.player_id, r.player_name) == ("Own Goal", 2, None, None)


@pytest.mark.parametrize("card_type", ["Yellow Card", "Second Yellow", "Red Card"])
def test_every_card_is_an_incident_with_its_type_in_the_detail(world, analytics, card_type):
    world.seed()
    card(world, 1, 2, 21, card_type)
    r = timeline(analytics)[0]
    assert (r.incident_type, r.detail, r.team_id, r.player_id) == ("Card", card_type, 2, 21)


def test_a_substitution_has_the_player_off_the_player_on_and_the_reason(world, analytics):
    world.seed()
    substitution(world, 1, 1, 11, 13, reason="Injury")
    r = timeline(analytics)[0]
    assert (r.incident_type, r.detail, r.player_id, r.player_name, r.related_player_id, r.related_player_name) == (
        "Substitution", "Injury", 11, "Jogador 11", 13, "Jogador 13")


def test_incidents_in_the_shootout_period_are_not_shown(world, analytics):
    world.seed()
    card(world, 1, 1, 11, "Yellow Card", period=5)
    assert timeline(analytics) == []


def test_the_incidents_are_chronological_by_period_and_idx_and_the_time_axis_agrees(world, analytics):
    world.seed()
    world.event(10, "Half End", 1, period=1, ts=3000)
    world.event(11, "Half End", 2, period=1, ts=3000)
    world.shot(20, 1, 11, outcome="Goal", ts=2900)                   # 1º tempo longo
    card(world, 5, 2, 21, "Yellow Card", period=2, ts=100)           # 2º tempo, idx menor que o do 1º
    substitution(world, 30, 1, 12, 13, period=2, ts=900)
    series = timeline(analytics)
    assert [r.incident_type for r in series] == ["Goal", "Card", "Substitution"]
    assert [r.tempo_decorrido_s for r in series] == pytest.approx([2900, 3100, 3900], abs=1e-9)


def test_the_goals_in_the_timeline_agree_with_the_goals_of_m1(world, analytics):
    """Invariante: gols + gols contra no relatório do jogo = `gols` de cada time."""
    world.seed()
    world.shot(1, 1, 11, outcome="Goal")
    world.shot(2, 1, 12, outcome="Goal", shot_type="Penalty")
    world.shot(3, 2, 21, outcome="Goal")
    world.shot(4, 2, 21, outcome="Goal", shot_type="Penalty", period=5)
    world.event(5, "Own Goal For", 2, None)
    world.shot(6, 1, 11, outcome="Saved")
    for team_id in (1, 2):
        in_timeline = rows(analytics, "SELECT count(*) FROM analytics.match_timeline WHERE team_id = :t AND incident_type IN ('Goal', 'Own Goal')", t=team_id)[0][0]
        official = rows(analytics, "SELECT gols FROM analytics.team_match_stats WHERE team_id = :t", t=team_id)[0][0]
        assert in_timeline == official, team_id
