"""Consultas da aplicação (`oddvision.app_queries`): leem só `analytics` e devolvem o que a página da partida exibe."""

import pytest

from oddvision import app_queries as q


def build(world):
    """Partida 100 com eventos (gol e finalização de A, gol contra a favor de B) e a partida 101 sem eventos."""
    world.seed()
    world.shot(1, 1, 11, outcome="Goal", xg=0.4, ts=600)
    world.shot(2, 1, 12, outcome="Saved", xg=0.1, ts=700)
    world.shot(3, 1, 11, outcome="Goal", shot_type="Penalty", xg=0.7835, period=5)
    world.event(4, "Own Goal For", 2, None, ts=900)
    world.match(101, 1, 2, home_score=2, away_score=1, lineups=False)


# --------------------------------------------------------------------------- partidas

def test_list_matches_has_every_match_with_the_has_events_flag(world, analytics):
    build(world)
    matches = q.list_matches(analytics)
    assert matches["match_id"].tolist() == [100, 101]      # por data e, no empate, por match_id
    assert dict(zip(matches["match_id"], matches["has_events"])) == {100: True, 101: False}


def test_match_header_returns_the_official_score_the_shootout_and_the_reconstruction(world, analytics):
    build(world)
    header = q.match_header(analytics, 100)
    assert (header["home_team_name"], header["away_team_name"]) == ("Casa", "Fora")
    assert (header["home_goals"], header["away_goals"]) == (1, 1)         # 1 gol de A; 1 gol contra a favor de B
    assert (header["home_penalties"], header["away_penalties"]) == (1, 0)


def test_match_header_of_an_unknown_match_is_none(world, analytics):
    build(world)
    assert q.match_header(analytics, 999) is None


def test_match_header_of_a_match_without_events_has_no_reconstruction(world, analytics):
    build(world)
    header = q.match_header(analytics, 101)
    assert header["has_events"] is False
    assert (header["home_score"], header["away_score"]) == (2, 1)
    assert header["home_goals"] is None and header["score_matches_events"] is None      # NULL vira None, nunca NaN


# --------------------------------------------------------------------------- estatísticas, escalações, finalizações

def test_team_stats_has_the_two_teams_with_the_metric_columns(world, analytics):
    build(world)
    stats = q.team_stats(analytics, 100)
    assert sorted(stats["team_name"]) == ["Casa", "Fora"]
    assert {"gols", "xg", "passes_progressivos", "passes_para_area", "is_home"} <= set(stats.columns)
    assert stats.set_index("team_name").loc["Casa", "finalizacoes"] == 2        # a da disputa fica de fora


def test_team_stats_of_a_match_without_events_is_empty(world, analytics):
    build(world)
    assert q.team_stats(analytics, 101).empty


def test_lineups_has_everyone_listed_for_the_match(world, analytics):
    build(world)
    assert len(q.lineups(analytics, 100)) == 6
    assert q.lineups(analytics, 101).empty


def test_shots_include_the_shootout_marked_and_the_football_label_for_the_rest(world, analytics):
    build(world)
    shots = q.shots(analytics, 100).sort_values(["period", "idx"])
    assert shots["is_shootout"].tolist() == [False, False, True]
    assert shots["rotulo"].tolist()[:2] == ["11'", "12'"]                        # ts 600 s e 700 s: minutos decorridos 10 e 11
    assert shots["rotulo"].isna().tolist()[2]                                    # a disputa não tem relógio


# --------------------------------------------------------------------------- só analytics

def test_every_query_text_reads_only_the_analytics_schema():
    for name, sql in q.QUERIES.items():
        lowered = sql.lower()
        assert "core." not in lowered and "extra" not in lowered, name
        assert "analytics." in lowered, name
