"""M5: passes progressivos, CONVENÇÃO OddVision v1 (docs/metrics.md).

É progressivo ⇔ completo E jogo corrido E período 1 a 4 E x ≥ 48 E (ganho de distância ao gol ≥ 10 jardas OU entrada na
área). Distância ao gol = distância até (120, 40). A coluna `is_progressivo` fica em analytics.pass_events e as contagens
`passes_progressivos` em team_match_stats e player_match_stats.
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


def is_progressive(world, analytics, x, y, end_x, end_y, **kwargs):
    world.seed()
    world.pass_(1, 1, 11, x=x, y=y, end_x=end_x, end_y=end_y, **kwargs)
    return rows(analytics, "SELECT is_progressivo FROM analytics.pass_events")[0][0]


# --------------------------------------------------------------------------- colunas

def test_the_new_column_is_added_at_the_end_of_the_stats_views_and_of_pass_events(world, analytics):
    cols = lambda view: [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = :v ORDER BY ordinal_position", v=view)]
    assert cols("team_match_stats")[16] == "passes_progressivos"
    assert cols("player_match_stats")[16] == "passes_progressivos"
    assert cols("pass_events")[30] == "is_progressivo"


# --------------------------------------------------------------------------- fronteiras (docs/metrics.md, critério de validação)

@pytest.mark.parametrize("end_x, expected", [(70.0, True), (69.99, False), (70.01, True)])
def test_the_distance_gain_boundary_is_10_yards(world, analytics, end_x, expected):
    """De (60, 40) a 60 jardas do gol: terminar em x = 70 é um ganho de exatamente 10,00."""
    assert is_progressive(world, analytics, 60, 40, end_x, 40) is expected


@pytest.mark.parametrize("x, expected", [(47.9, False), (48.0, True), (48.1, True)])
def test_the_start_boundary_is_x_48(world, analytics, x, expected):
    """O ganho de distância é grande nos três casos (mais de 10 jardas): só o x de partida decide."""
    assert is_progressive(world, analytics, x, 40, 70, 40) is expected


def test_a_short_pass_that_enters_the_box_is_progressive_even_without_the_distance_gain(world, analytics):
    assert is_progressive(world, analytics, 101, 40, 102, 40) is True      # ganho de 1 jarda, mas entra na área em x = 102 (inclusivo)


def test_a_pass_that_ends_just_outside_the_box_is_not_an_entry(world, analytics):
    assert is_progressive(world, analytics, 101, 40, 101.99, 40) is False


@pytest.mark.parametrize("end_y, expected", [(18.0, True), (17.99, False), (62.0, True), (62.01, False)])
def test_entering_through_the_box_sides_isolates_the_y_boundary(world, analytics, end_y, expected):
    """Início em (101, end_y), fora da área por x; fim em (102, end_y): só a lateral decide a entrada (ganho de 1 jarda)."""
    assert is_progressive(world, analytics, 101, end_y, 102, end_y) is expected


def test_a_short_pass_inside_the_box_is_not_an_entry_and_not_progressive(world, analytics):
    assert is_progressive(world, analytics, 105, 40, 110, 40) is False     # dentro → dentro, ganho de 5


def test_a_long_pass_inside_the_box_still_counts_by_the_distance_gain(world, analytics):
    """A fórmula é 'ganho ≥ 10 OU entrada': de dentro para dentro com ganho de 18 jardas passa pelo primeiro critério."""
    assert is_progressive(world, analytics, 102, 40, 120, 40) is True


@pytest.mark.parametrize("x, y, end_x, end_y", [(80, 40, 60, 40), (80, 20, 80, 60)], ids=["backward", "lateral"])
def test_backward_and_lateral_passes_are_not_progressive(world, analytics, x, y, end_x, end_y):
    assert is_progressive(world, analytics, x, y, end_x, end_y) is False


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
def test_incomplete_set_piece_and_shootout_passes_are_never_progressive(world, analytics, kwargs):
    assert is_progressive(world, analytics, 60, 40, 90, 40, **kwargs) is False


@pytest.mark.parametrize("pass_type", [None, "Recovery", "Interception"])
def test_open_play_pass_types_can_be_progressive(world, analytics, pass_type):
    assert is_progressive(world, analytics, 60, 40, 90, 40, pass_type=pass_type) is True


@pytest.mark.parametrize("period", [1, 2, 3, 4])
def test_every_valid_period_counts(world, analytics, period):
    assert is_progressive(world, analytics, 60, 40, 90, 40, period=period) is True


# --------------------------------------------------------------------------- contagens e invariantes

def build_progressive(world):
    """Time 1: jogador 11 com 2 progressivos de 4 passes; jogador 12 com 1 de 2. Time 2: nenhum."""
    world.seed()
    p = lambda idx, player, x, end_x, **kw: world.pass_(idx, 1, player, x=x, y=40, end_x=end_x, end_y=40, **kw)
    p(1, 11, 60, 75)                         # progressivo
    p(2, 11, 60, 95)                         # progressivo
    p(3, 11, 60, 65)                         # ganho de 5: não
    p(4, 11, 60, 90, outcome="Incomplete")   # incompleto: não
    p(5, 12, 50, 80)                         # progressivo
    p(6, 12, 60, 90, pass_type="Throw-in")   # lateral: não


def test_m5_counts_by_team_and_by_player(world, analytics):
    build_progressive(world)
    assert team(analytics, 1).passes_progressivos == 3
    assert team(analytics, 2).passes_progressivos == 0
    assert player(analytics, 11).passes_progressivos == 2
    assert player(analytics, 12).passes_progressivos == 1
    assert player(analytics, 13).passes_progressivos == 0


def test_the_players_add_up_to_the_team(world, analytics):
    build_progressive(world)
    by_players = analytics.execute(text(
        "SELECT sum(passes_progressivos) FROM analytics.player_match_stats WHERE match_id = 100 AND team_id = 1")).scalar_one()
    assert by_players == team(analytics, 1).passes_progressivos


def test_progressive_passes_are_a_subset_of_completed_open_play_passes(world, analytics):
    build_progressive(world)
    broken = rows(analytics, "SELECT 1 FROM analytics.pass_events WHERE is_progressivo AND NOT (is_complete AND is_jogo_corrido AND is_tentado)")
    assert broken == []
    assert team(analytics, 1).passes_progressivos <= team(analytics, 1).passes_completos
