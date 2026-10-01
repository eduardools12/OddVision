"""M2 (finalizações e no alvo) e M3 (xG, npxG e npxG por finalização sem pênalti), docs/metrics.md.

Views: analytics.shot_events (uma linha por finalização, para a tabela e o mapa) e as colunas finalizacoes,
finalizacoes_no_alvo, xg, npxg, finalizacoes_sem_penalti e npxg_por_finalizacao_sem_penalti em team_match_stats e
player_match_stats. Os valores de xG do mundo sintético foram escolhidos para as somas serem fáceis de conferir à mão.
"""

import pytest
from sqlalchemy import text

APPROX = dict(abs=1e-9)


def rows(conn, sql, **params):
    return conn.execute(text(sql), params).all()


def team(conn, team_id, match_id=100):
    return rows(conn, "SELECT * FROM analytics.team_match_stats WHERE match_id = :m AND team_id = :t", m=match_id, t=team_id)[0]


def player(conn, player_id, match_id=100):
    return rows(conn, "SELECT * FROM analytics.player_match_stats WHERE match_id = :m AND player_id = :p", m=match_id, p=player_id)[0]


def build_shots(world):
    """Time 1: 9 finalizações válidas (uma delas pênalti) + 1 da disputa. Time 2: nenhuma."""
    world.seed()
    world.shot(1, 1, 11, outcome="Goal", xg=0.30)
    world.shot(2, 1, 11, outcome="Saved", xg=0.10)
    world.shot(3, 1, 12, outcome="Saved to Post", xg=0.05)
    world.shot(4, 1, 12, outcome="Post", xg=0.04)
    world.shot(5, 1, 12, outcome="Blocked", xg=0.02)
    world.shot(6, 1, 12, outcome="Off T", xg=0.03)
    world.shot(7, 1, 12, outcome="Wayward", xg=0.01)
    world.shot(8, 1, 12, outcome="Saved Off Target", xg=0.06)
    world.shot(9, 1, 11, outcome="Goal", xg=0.7835, shot_type="Penalty", period=2)    # pênalti DURANTE o jogo
    world.shot(10, 1, 12, outcome="Goal", xg=0.7835, shot_type="Penalty", period=5)   # disputa de pênaltis: fora de tudo


# --------------------------------------------------------------------------- colunas

def test_the_new_columns_are_added_at_the_end_of_the_stats_views(world, analytics):
    cols = lambda view: [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = :v ORDER BY ordinal_position", v=view)]
    added = ["finalizacoes", "finalizacoes_no_alvo", "xg", "npxg", "finalizacoes_sem_penalti", "npxg_por_finalizacao_sem_penalti"]
    assert cols("team_match_stats")[7:13] == added
    assert cols("player_match_stats")[7:13] == added


def test_shot_events_has_one_row_per_shot_with_everything_the_page_needs(world, analytics):
    build_shots(world)
    columns = [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = 'shot_events' ORDER BY ordinal_position")]
    assert columns == ["event_id", "match_id", "idx", "team_id", "team_name", "player_id", "player_name", "period", "minute", "second",
                       "ts_in_period", "x", "y", "end_x", "end_y", "end_z", "outcome", "shot_type", "body_part", "technique", "statsbomb_xg",
                       "key_pass_id", "is_goal", "is_no_alvo", "is_penalty", "is_shootout"]
    assert rows(analytics, "SELECT count(*) FROM analytics.shot_events")[0][0] == 10  # inclusive a da disputa, marcada


# --------------------------------------------------------------------------- M2: no alvo (convenção do OddVision)

@pytest.mark.parametrize("outcome, on_target", [
    ("Goal", True), ("Saved", True), ("Saved to Post", True),
    ("Post", False), ("Blocked", False), ("Off T", False), ("Wayward", False), ("Saved Off Target", False),
])
def test_m2_which_outcomes_count_as_on_target(world, analytics, outcome, on_target):
    world.seed()
    world.shot(1, 1, 11, outcome=outcome)
    r = rows(analytics, "SELECT * FROM analytics.shot_events")[0]
    assert r.is_no_alvo is on_target
    assert team(analytics, 1).finalizacoes_no_alvo == int(on_target)


def test_m2_the_goal_flag_and_the_penalty_and_shootout_flags(world, analytics):
    build_shots(world)
    flags = {r.idx: (r.is_goal, r.is_penalty, r.is_shootout) for r in rows(analytics, "SELECT * FROM analytics.shot_events")}
    assert flags[1] == (True, False, False)
    assert flags[2] == (False, False, False)
    assert flags[9] == (True, True, False)   # pênalti durante o jogo
    assert flags[10] == (True, True, True)   # pênalti da disputa


# --------------------------------------------------------------------------- M2 e M3 por time

def test_m2_team_shots_and_shots_on_target_exclude_the_shootout(world, analytics):
    build_shots(world)
    t = team(analytics, 1)
    assert t.finalizacoes == 9               # 8 de jogo aberto + o pênalti em jogo; o da disputa fica de fora
    assert t.finalizacoes_no_alvo == 4       # Goal, Saved, Saved to Post e o pênalti convertido
    assert t.finalizacoes_no_alvo <= t.finalizacoes


def test_m3_xg_includes_penalties_and_npxg_does_not(world, analytics):
    build_shots(world)
    t = team(analytics, 1)
    assert t.xg == pytest.approx(1.3935, **APPROX)       # 0.30+0.10+0.05+0.04+0.02+0.03+0.01+0.06+0.7835
    assert t.npxg == pytest.approx(0.61, **APPROX)       # o mesmo, sem os 0,7835 do pênalti
    assert t.npxg <= t.xg


def test_m3_the_rate_uses_the_same_events_in_numerator_and_denominator(world, analytics):
    build_shots(world)
    t = team(analytics, 1)
    assert t.finalizacoes_sem_penalti == 8   # as finalizações SEM o pênalti: o denominador exclui o mesmo que o npxG
    assert t.npxg_por_finalizacao_sem_penalti == pytest.approx(0.61 / 8, **APPROX)


def test_a_team_without_shots_has_zero_counts_and_a_null_rate(world, analytics):
    build_shots(world)
    t = team(analytics, 2)
    assert (t.finalizacoes, t.finalizacoes_no_alvo, t.finalizacoes_sem_penalti) == (0, 0, 0)
    assert (t.xg, t.npxg) == (0.0, 0.0)
    assert t.npxg_por_finalizacao_sem_penalti is None  # divisão por zero é NULL, nunca 0


def test_a_team_with_only_a_penalty_has_zero_npxg_and_a_null_rate(world, analytics):
    world.seed()
    world.shot(1, 1, 11, outcome="Goal", xg=0.7835, shot_type="Penalty")
    t = team(analytics, 1)
    assert (t.finalizacoes, t.finalizacoes_sem_penalti) == (1, 0)
    assert (t.xg, t.npxg) == (pytest.approx(0.7835), 0.0)
    assert t.npxg_por_finalizacao_sem_penalti is None


def test_the_shootout_never_enters_xg(world, analytics):
    world.seed()
    world.shot(1, 1, 11, outcome="Goal", xg=0.7835, shot_type="Penalty", period=5)
    t = team(analytics, 1)
    assert (t.finalizacoes, t.xg, t.npxg) == (0, 0.0, 0.0)


# --------------------------------------------------------------------------- por jogador e invariantes

def test_m2_m3_by_player(world, analytics):
    build_shots(world)
    p11, p12, p13 = player(analytics, 11), player(analytics, 12), player(analytics, 13)
    assert (p11.finalizacoes, p11.finalizacoes_no_alvo, p11.finalizacoes_sem_penalti) == (3, 3, 2)
    assert p11.xg == pytest.approx(1.1835, **APPROX) and p11.npxg == pytest.approx(0.40, **APPROX)
    assert p11.npxg_por_finalizacao_sem_penalti == pytest.approx(0.20, **APPROX)
    assert (p12.finalizacoes, p12.finalizacoes_no_alvo, p12.finalizacoes_sem_penalti) == (6, 1, 6)  # a da disputa não conta
    assert p12.xg == pytest.approx(0.21, **APPROX) and p12.npxg_por_finalizacao_sem_penalti == pytest.approx(0.035, **APPROX)
    assert (p13.finalizacoes, p13.xg, p13.npxg_por_finalizacao_sem_penalti) == (0, 0.0, None)


def test_the_players_add_up_to_the_team(world, analytics):
    """Invariante: Σ jogadores = time, em finalizações, no alvo, xG e npxG."""
    build_shots(world)
    for column in ("finalizacoes", "finalizacoes_no_alvo", "xg", "npxg", "finalizacoes_sem_penalti"):
        for team_id in (1, 2):
            by_players = analytics.execute(text(
                f"SELECT COALESCE(sum({column}), 0) FROM analytics.player_match_stats WHERE match_id = 100 AND team_id = :t"), {"t": team_id}).scalar_one()
            assert by_players == pytest.approx(getattr(team(analytics, team_id), column), **APPROX), (column, team_id)


def test_goals_agree_with_the_shot_flags(world, analytics):
    """Os gols de M1 (sem gol contra) são as finalizações marcadas como gol fora da disputa."""
    build_shots(world)
    flagged = rows(analytics, "SELECT count(*) FROM analytics.shot_events WHERE is_goal AND NOT is_shootout")[0][0]
    assert flagged == team(analytics, 1).gols - team(analytics, 1).gols_contra_a_favor == 2
