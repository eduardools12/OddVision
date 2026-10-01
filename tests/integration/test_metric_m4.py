"""M4: passes tentados, passes completos e percentual de acerto (docs/metrics.md).

Views: analytics.pass_events (uma linha por passe, com as marcações que as métricas de passe usam) e as colunas
passes_tentados, passes_completos e pct_acerto_passes em team_match_stats e player_match_stats.
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


def build_passes(world):
    """Time 1 (jogadores 11 e 12): 15 passes, dos quais 10 são 'tentados' e 6 deles completos. Time 2: nenhum."""
    world.seed()
    p = lambda idx, player, **kw: world.pass_(idx, 1, player, x=50, y=40, end_x=60, end_y=40, **kw)
    p(1, 11)                                      # regular completo
    p(2, 11)                                      # regular completo
    p(3, 11, outcome="Incomplete")
    p(4, 12, pass_type="Recovery")                # completo
    p(5, 12, pass_type="Interception", outcome="Out")
    p(6, 12, pass_type="Corner")                  # bola parada com o pé: CONTA em M4
    p(7, 12, pass_type="Free Kick", outcome="Incomplete")
    p(8, 12, pass_type="Goal Kick")
    p(9, 12, pass_type="Kick Off")
    p(10, 12, pass_type="Throw-in")               # com a mão: fora, mesmo completo
    p(11, 12, pass_type="Throw-in", outcome="Out")
    p(12, 11, outcome="Unknown")                  # resultado não determinado pela fonte: fora
    p(13, 11, outcome="Injury Clearance")         # bola chutada para fora por lesão: fora
    p(14, 11, outcome="Pass Offside")             # impedimento é tentativa que falhou: CONTA
    p(15, 11, period=5)                           # disputa de pênaltis: fora


# --------------------------------------------------------------------------- colunas

def test_the_new_columns_are_added_at_the_end_of_the_stats_views(world, analytics):
    cols = lambda view: [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = :v ORDER BY ordinal_position", v=view)]
    added = ["passes_tentados", "passes_completos", "pct_acerto_passes"]
    assert cols("team_match_stats")[13:16] == added
    assert cols("player_match_stats")[13:16] == added


def test_pass_events_has_one_row_per_pass_with_everything_the_page_needs(world, analytics):
    build_passes(world)
    columns = [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = 'pass_events' ORDER BY ordinal_position")]
    expected = ["event_id", "match_id", "idx", "team_id", "team_name", "player_id", "player_name", "recipient_id", "recipient_name",
                "period", "minute", "second", "ts_in_period", "x", "y", "end_x", "end_y", "length", "height", "pass_type", "body_part",
                "outcome", "is_complete", "is_cross", "is_switch", "is_through_ball", "is_shot_assist", "is_goal_assist",
                "is_jogo_corrido", "is_tentado"]
    assert columns[:len(expected)] == expected
    assert rows(analytics, "SELECT count(*) FROM analytics.pass_events")[0][0] == 15  # todos os passes, marcados


# --------------------------------------------------------------------------- marcações

@pytest.mark.parametrize("pass_type, open_play", [
    (None, True), ("Recovery", True), ("Interception", True),
    ("Corner", False), ("Free Kick", False), ("Goal Kick", False), ("Kick Off", False), ("Throw-in", False),
])
def test_which_pass_types_are_open_play(world, analytics, pass_type, open_play):
    world.seed()
    world.pass_(1, 1, 11, x=50, y=40, end_x=60, end_y=40, pass_type=pass_type)
    assert rows(analytics, "SELECT is_jogo_corrido FROM analytics.pass_events")[0][0] is open_play


@pytest.mark.parametrize("pass_type, outcome, period, attempted", [
    (None, None, 1, True),
    (None, "Incomplete", 1, True),
    (None, "Out", 2, True),
    (None, "Pass Offside", 3, True),
    ("Corner", None, 1, True),                  # bola parada com o pé conta
    ("Goal Kick", "Incomplete", 4, True),
    ("Throw-in", None, 1, False),
    ("Throw-in", "Out", 1, False),
    (None, "Unknown", 1, False),
    (None, "Injury Clearance", 1, False),
    (None, None, 5, False),                     # período 5
])
def test_which_passes_count_as_attempted(world, analytics, pass_type, outcome, period, attempted):
    world.seed()
    world.pass_(1, 1, 11, x=50, y=40, end_x=60, end_y=40, pass_type=pass_type, outcome=outcome, period=period)
    assert rows(analytics, "SELECT is_tentado FROM analytics.pass_events")[0][0] is attempted
    assert team(analytics, 1).passes_tentados == int(attempted)


# --------------------------------------------------------------------------- M4 por time e por jogador

def test_m4_team_attempted_completed_and_percentage(world, analytics):
    build_passes(world)
    t = team(analytics, 1)
    assert (t.passes_tentados, t.passes_completos) == (10, 6)
    assert t.pct_acerto_passes == pytest.approx(60.0, **APPROX)


def test_m4_completed_only_counts_among_the_attempted(world, analytics):
    """O passe completo de lateral (Throw-in) não é tentado, então não pode ser completo em M4."""
    world.seed()
    world.pass_(1, 1, 11, x=50, y=40, end_x=60, end_y=40, pass_type="Throw-in")
    world.pass_(2, 1, 11, x=50, y=40, end_x=60, end_y=40)
    world.pass_(3, 1, 11, x=50, y=40, end_x=60, end_y=40, outcome="Incomplete")
    t = team(analytics, 1)
    assert (t.passes_tentados, t.passes_completos) == (2, 1)
    assert t.pct_acerto_passes == pytest.approx(50.0, **APPROX)


def test_a_team_without_attempted_passes_has_zero_counts_and_a_null_percentage(world, analytics):
    build_passes(world)
    t = team(analytics, 2)
    assert (t.passes_tentados, t.passes_completos) == (0, 0)
    assert t.pct_acerto_passes is None  # divisão por zero é NULL, nunca 0


def test_a_team_with_only_excluded_passes_has_a_null_percentage(world, analytics):
    world.seed()
    world.pass_(1, 1, 11, x=50, y=40, end_x=60, end_y=40, pass_type="Throw-in")
    world.pass_(2, 1, 11, x=50, y=40, end_x=60, end_y=40, outcome="Unknown")
    t = team(analytics, 1)
    assert (t.passes_tentados, t.passes_completos, t.pct_acerto_passes) == (0, 0, None)


def test_m4_by_player(world, analytics):
    build_passes(world)
    p11, p12, p13 = player(analytics, 11), player(analytics, 12), player(analytics, 13)
    assert (p11.passes_tentados, p11.passes_completos) == (4, 2)
    assert p11.pct_acerto_passes == pytest.approx(50.0, **APPROX)
    assert (p12.passes_tentados, p12.passes_completos) == (6, 4)
    assert p12.pct_acerto_passes == pytest.approx(100 * 4 / 6, **APPROX)
    assert (p13.passes_tentados, p13.passes_completos, p13.pct_acerto_passes) == (0, 0, None)


# --------------------------------------------------------------------------- invariantes

def test_the_players_add_up_to_the_team(world, analytics):
    build_passes(world)
    for column in ("passes_tentados", "passes_completos"):
        by_players = analytics.execute(text(
            f"SELECT COALESCE(sum({column}), 0) FROM analytics.player_match_stats WHERE match_id = 100 AND team_id = 1")).scalar_one()
        assert by_players == getattr(team(analytics, 1), column), column


def test_completed_never_exceeds_attempted_and_the_percentage_is_between_0_and_100(world, analytics):
    build_passes(world)
    for view in ("team_match_stats", "player_match_stats"):
        broken = rows(analytics, f"SELECT 1 FROM analytics.{view} WHERE passes_completos > passes_tentados "
                                 "OR pct_acerto_passes < 0 OR pct_acerto_passes > 100")
        assert broken == []
