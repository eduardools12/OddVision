"""M7: passes para a área, CONVENÇÃO geométrica (docs/metrics.md).

Passe completo, de jogo corrido, período 1 a 4, que começa FORA da área e termina DENTRO dela. Área: x ≥ 102 e
18 ≤ y ≤ 62, limites inclusivos. A marcação `is_passe_para_area` fica em analytics.pass_events e a contagem
`passes_para_area` em team_match_stats e player_match_stats.
"""

import pytest
from sqlalchemy import text


def rows(conn, sql, **params):
    return conn.execute(text(sql), params).all()


def team(conn, team_id, match_id=100):
    return rows(conn, "SELECT * FROM analytics.team_match_stats WHERE match_id = :m AND team_id = :t", m=match_id, t=team_id)[0]


def player(conn, player_id, match_id=100):
    return rows(conn, "SELECT * FROM analytics.player_match_stats WHERE match_id = :m AND player_id = :p", m=match_id, p=player_id)[0]


def into_box(world, analytics, x, y, end_x, end_y, **kwargs):
    world.seed()
    world.pass_(1, 1, 11, x=x, y=y, end_x=end_x, end_y=end_y, **kwargs)
    return rows(analytics, "SELECT is_passe_para_area FROM analytics.pass_events")[0][0]


# --------------------------------------------------------------------------- colunas

def test_the_new_column_is_added_at_the_end_of_the_stats_views_and_of_pass_events(world, analytics):
    cols = lambda view: [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = :v ORDER BY ordinal_position", v=view)]
    assert cols("team_match_stats")[18] == "passes_para_area"
    assert cols("player_match_stats")[18] == "passes_para_area"
    assert cols("pass_events")[31] == "is_passe_para_area"


# --------------------------------------------------------------------------- geometria (fronteiras exatas)

@pytest.mark.parametrize("end_x, expected", [(102.0, True), (101.99, False), (102.01, True), (120.0, True)])
def test_the_box_depth_boundary_is_x_102(world, analytics, end_x, expected):
    assert into_box(world, analytics, 90, 40, end_x, 40) is expected


@pytest.mark.parametrize("end_y, expected", [(18.0, True), (17.99, False), (62.0, True), (62.01, False)])
def test_the_box_width_boundaries_are_y_18_and_62_inclusive(world, analytics, end_y, expected):
    assert into_box(world, analytics, 90, end_y, 110, end_y) is expected


@pytest.mark.parametrize("x, y, expected", [
    (101.99, 40, True),    # começa logo antes da linha da área: fora
    (102.0, 40, False),    # começa em x = 102: já dentro, não é entrada
    (110, 40, False),      # começa dentro
    (110, 18, False),      # começa na borda lateral (dentro, inclusivo)
    (110, 62, False),
    (110, 17.99, True),    # começa ao lado da área (y fora) e termina dentro: é entrada
    (110, 62.01, True),
])
def test_only_a_start_outside_the_box_makes_an_entry(world, analytics, x, y, expected):
    assert into_box(world, analytics, x, y, 112, 40) is expected


def test_a_pass_that_ends_outside_the_box_is_not_an_entry(world, analytics):
    assert into_box(world, analytics, 60, 40, 90, 40) is False


def test_an_entry_does_not_need_the_forward_distance_or_the_start_of_the_progressive_rule(world, analytics):
    """M7 não herda os limiares da M5: um passe de x = 30 até a área é para a área (longo, mas não progressivo)."""
    world.seed()
    world.pass_(1, 1, 11, x=30, y=40, end_x=105, end_y=40)
    r = rows(analytics, "SELECT is_passe_para_area, is_progressivo FROM analytics.pass_events")[0]
    assert (r.is_passe_para_area, r.is_progressivo) == (True, False)


# --------------------------------------------------------------------------- exclusões

@pytest.mark.parametrize("kwargs", [
    {"outcome": "Incomplete"},
    {"outcome": "Out"},
    {"outcome": "Pass Offside"},
    {"pass_type": "Corner"},
    {"pass_type": "Free Kick"},
    {"pass_type": "Goal Kick"},
    {"pass_type": "Kick Off"},
    {"pass_type": "Throw-in"},
    {"period": 5},
])
def test_incomplete_set_piece_and_shootout_passes_are_never_entries(world, analytics, kwargs):
    assert into_box(world, analytics, 90, 40, 110, 40, **kwargs) is False


@pytest.mark.parametrize("pass_type", [None, "Recovery", "Interception"])
def test_open_play_pass_types_can_be_entries(world, analytics, pass_type):
    assert into_box(world, analytics, 90, 40, 110, 40, pass_type=pass_type) is True


@pytest.mark.parametrize("period", [1, 2, 3, 4])
def test_every_valid_period_counts(world, analytics, period):
    assert into_box(world, analytics, 90, 40, 110, 40, period=period) is True


# --------------------------------------------------------------------------- contagens e invariantes

def build_entries(world):
    """Time 1: jogador 11 com 2 entradas de 4 passes; jogador 12 com 1 de 2. Time 2: nenhuma."""
    world.seed()
    p = lambda idx, player, x, end_x, **kw: world.pass_(idx, 1, player, x=x, y=40, end_x=end_x, end_y=40, **kw)
    p(1, 11, 90, 110)
    p(2, 11, 95, 105)
    p(3, 11, 105, 115)                         # já dentro: não
    p(4, 11, 90, 110, outcome="Incomplete")    # incompleto: não
    p(5, 12, 100, 103)
    p(6, 12, 90, 110, pass_type="Corner")      # escanteio: não


def test_m7_counts_by_team_and_by_player(world, analytics):
    build_entries(world)
    assert team(analytics, 1).passes_para_area == 3
    assert team(analytics, 2).passes_para_area == 0
    assert player(analytics, 11).passes_para_area == 2
    assert player(analytics, 12).passes_para_area == 1
    assert player(analytics, 13).passes_para_area == 0


def test_the_players_add_up_to_the_team(world, analytics):
    build_entries(world)
    by_players = analytics.execute(text(
        "SELECT sum(passes_para_area) FROM analytics.player_match_stats WHERE match_id = 100 AND team_id = 1")).scalar_one()
    assert by_players == team(analytics, 1).passes_para_area


def test_entries_are_a_subset_of_completed_open_play_passes(world, analytics):
    build_entries(world)
    broken = rows(analytics, "SELECT 1 FROM analytics.pass_events WHERE is_passe_para_area AND NOT (is_complete AND is_jogo_corrido AND is_tentado)")
    assert broken == []
    assert team(analytics, 1).passes_para_area <= team(analytics, 1).passes_completos
