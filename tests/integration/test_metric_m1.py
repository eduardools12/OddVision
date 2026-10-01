"""M1: placar e gols (docs/metrics.md, seção M1). Dados sintéticos com fronteiras controladas.

Views: analytics.team_match_stats (gols, gols_contra_a_favor, penaltis_disputa), analytics.player_match_stats (gols)
e analytics.match_summary (placar oficial x reconstruído, e a disputa de pênaltis como informação separada).
"""

from sqlalchemy import text


def rows(conn, sql, **params):
    return conn.execute(text(sql), params).all()


def team_stats(conn, match_id=100):
    return {r.team_id: r for r in rows(conn, "SELECT * FROM analytics.team_match_stats WHERE match_id = :m", m=match_id)}


def player_goals(conn, match_id=100):
    return {r.player_id: r.gols for r in rows(conn, "SELECT player_id, gols FROM analytics.player_match_stats WHERE match_id = :m", m=match_id)}


def build_match_with_everything(world):
    """Casa (1) x Fora (2): gols de jogo aberto, de pênalti, na prorrogação, um gol contra e uma disputa de pênaltis."""
    world.seed(home_score=2, away_score=2)
    world.shot(1, 1, 11, outcome="Goal")                                      # gol de jogo aberto (P1)
    world.shot(2, 1, 11, outcome="Goal", shot_type="Penalty", period=2)       # pênalti DURANTE o jogo conta
    world.shot(3, 2, 21, outcome="Goal", period=3)                            # prorrogação conta
    world.shot(4, 1, 12, outcome="Saved")                                     # defendida: não é gol
    world.event(5, "Own Goal For", team=2)                                    # gol contra: vale para o time 2, sem jogador
    world.event(6, "Own Goal Against", team=1, player=12)                     # o jogador do time 1 que fez o gol contra
    world.shot(7, 1, 11, outcome="Goal", shot_type="Penalty", period=5)       # disputa de pênaltis (P5): fora do placar
    world.shot(8, 1, 12, outcome="Goal", shot_type="Penalty", period=5)
    world.shot(9, 2, 21, outcome="Saved", shot_type="Penalty", period=5)


# --------------------------------------------------------------------------- colunas (o contrato das views)

def test_the_views_expose_exactly_the_documented_columns(world, analytics):
    cols = lambda view: [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = :v ORDER BY ordinal_position", v=view)]
    assert cols("team_match_stats")[:7] == ["match_id", "team_id", "team_name", "is_home", "gols", "gols_contra_a_favor", "penaltis_disputa"]
    assert cols("player_match_stats")[:7] == ["match_id", "team_id", "player_id", "player_name", "is_starter", "played", "gols"]
    assert cols("match_summary") == [
        "match_id", "match_date", "competition_stage", "home_team_id", "home_team_name", "away_team_id", "away_team_name",
        "home_score", "away_score", "has_events", "home_goals", "away_goals", "score_matches_events", "home_penalties", "away_penalties"]


# --------------------------------------------------------------------------- gols por time

def test_team_goals_count_open_play_penalties_in_play_and_extra_time(world, analytics):
    build_match_with_everything(world)
    stats = team_stats(analytics)
    assert stats[1].gols == 2          # jogo aberto + pênalti durante o jogo
    assert stats[2].gols == 2          # prorrogação + 1 gol contra a favor


def test_an_own_goal_is_credited_to_the_beneficiary_team(world, analytics):
    build_match_with_everything(world)
    stats = team_stats(analytics)
    assert (stats[2].gols_contra_a_favor, stats[1].gols_contra_a_favor) == (1, 0)


def test_the_shootout_is_reported_apart_and_never_counted_as_goals(world, analytics):
    build_match_with_everything(world)
    stats = team_stats(analytics)
    assert (stats[1].penaltis_disputa, stats[2].penaltis_disputa) == (2, 0)
    assert (stats[1].gols, stats[2].gols) == (2, 2)  # os 2 gols da disputa não entram no placar


def test_a_match_without_a_shootout_has_null_shootout_goals_not_zero(world, analytics):
    world.seed()
    world.event(1, "Pass", team=1, player=11)
    stats = team_stats(analytics)
    assert stats[1].penaltis_disputa is None and stats[2].penaltis_disputa is None
    assert (stats[1].gols, stats[2].gols) == (0, 0)  # sem gols é zero, e isso é diferente de "não houve disputa"


def test_a_team_that_missed_every_shootout_penalty_has_zero_not_null(world, analytics):
    world.seed()
    world.shot(1, 2, 21, outcome="Saved", shot_type="Penalty", period=5)
    assert team_stats(analytics)[1].penaltis_disputa == 0


def test_team_rows_exist_only_for_matches_with_events_and_have_one_row_per_team(world, analytics):
    world.seed()
    world.match(101, home=1, away=2)  # partida sem nenhum evento carregado
    world.event(1, "Pass", team=1, player=11)
    assert rows(analytics, "SELECT DISTINCT match_id FROM analytics.team_match_stats") == [(100,)]
    assert sorted(team_stats(analytics)) == [1, 2]
    assert {r.team_id: (r.team_name, r.is_home) for r in team_stats(analytics).values()} == {1: ("Casa", True), 2: ("Fora", False)}


# --------------------------------------------------------------------------- gols por jogador

def test_player_goals_exclude_own_goals_and_the_shootout(world, analytics):
    build_match_with_everything(world)
    goals = player_goals(analytics)
    assert goals[11] == 2   # os 2 gols de jogo (um deles de pênalti); os da disputa não contam
    assert goals[12] == 0   # fez um gol contra e dois na disputa: nenhum conta como gol dele
    assert goals[21] == 1
    assert goals[13] == goals[22] == goals[23] == 0


def test_player_rows_cover_every_listed_player_with_their_status(world, analytics):
    build_match_with_everything(world)
    found = {r.player_id: (r.team_id, r.is_starter, r.played, r.player_name)
             for r in rows(analytics, "SELECT * FROM analytics.player_match_stats WHERE match_id = 100")}
    assert found[11] == (1, True, True, "Jogador 11")
    assert found[13] == (1, False, False, "Jogador 13")  # não entrou: aparece, com zero gols
    assert sorted(found) == [11, 12, 13, 21, 22, 23]


def test_goals_by_players_plus_own_goals_equal_the_team_goals(world, analytics):
    """Invariante da M1: Σ gols dos jogadores + gols contra a favor = gols do time."""
    build_match_with_everything(world)
    for team_id, team in team_stats(analytics).items():
        by_players = analytics.execute(text(
            "SELECT COALESCE(sum(gols), 0) FROM analytics.player_match_stats WHERE match_id = 100 AND team_id = :t"), {"t": team_id}).scalar_one()
        assert by_players + team.gols_contra_a_favor == team.gols


# --------------------------------------------------------------------------- resumo da partida

def test_match_summary_compares_the_official_score_with_the_events(world, analytics):
    build_match_with_everything(world)
    r = rows(analytics, "SELECT * FROM analytics.match_summary WHERE match_id = 100")[0]
    assert (r.home_team_name, r.away_team_name, r.competition_stage) == ("Casa", "Fora", "Final")
    assert (r.home_score, r.away_score) == (2, 2)
    assert (r.has_events, r.home_goals, r.away_goals, r.score_matches_events) == (True, 2, 2, True)
    assert (r.home_penalties, r.away_penalties) == (2, 0)  # a disputa é informação complementar, não faz parte do placar


def test_match_summary_flags_a_score_that_the_events_do_not_support(world, analytics):
    build_match_with_everything(world)
    world.run("UPDATE core.matches SET away_score = 3 WHERE match_id = 100")
    r = rows(analytics, "SELECT * FROM analytics.match_summary WHERE match_id = 100")[0]
    assert (r.away_score, r.away_goals, r.score_matches_events) == (3, 2, False)


def test_match_summary_has_no_reconstruction_for_a_match_without_events(world, analytics):
    world.seed()
    world.match(102, home=1, away=2)
    r = rows(analytics, "SELECT * FROM analytics.match_summary WHERE match_id = 102")[0]
    assert (r.has_events, r.home_goals, r.away_goals, r.score_matches_events) == (False, None, None, None)
    assert (r.home_penalties, r.away_penalties) == (None, None)
    assert r.home_score == 0  # o placar oficial continua disponível
