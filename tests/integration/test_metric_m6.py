"""M6: conduções progressivas, CONVENÇÃO OddVision v1 (docs/metrics.md).

A mesma regra geométrica da M5, aplicada a `Carry`: é progressiva ⇔ período 1 a 4 E x ≥ 48 E (ganho de distância ao gol
≥ 10 jardas OU entrada na área). Uma condução não tem resultado na fonte, então não há filtro de "completa".
A marcação `is_progressivo` fica em analytics.carry_events e a contagem `conducoes_progressivas` nas views de estatísticas.
"""

import pytest
from sqlalchemy import text


def rows(conn, sql, **params):
    return conn.execute(text(sql), params).all()


def team(conn, team_id, match_id=100):
    return rows(conn, "SELECT * FROM analytics.team_match_stats WHERE match_id = :m AND team_id = :t", m=match_id, t=team_id)[0]


def player(conn, player_id, match_id=100):
    return rows(conn, "SELECT * FROM analytics.player_match_stats WHERE match_id = :m AND player_id = :p", m=match_id, p=player_id)[0]


def is_progressive(world, analytics, x, y, end_x, end_y, **kwargs):
    world.seed()
    world.carry(1, 1, 11, x=x, y=y, end_x=end_x, end_y=end_y, **kwargs)
    return rows(analytics, "SELECT is_progressivo FROM analytics.carry_events")[0][0]


# --------------------------------------------------------------------------- colunas

def test_the_new_column_is_added_at_the_end_of_the_stats_views(world, analytics):
    cols = lambda view: [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = :v ORDER BY ordinal_position", v=view)]
    assert cols("team_match_stats")[17] == "conducoes_progressivas"
    assert cols("player_match_stats")[17] == "conducoes_progressivas"


def test_carry_events_has_one_row_per_carry_with_everything_the_page_needs(world, analytics):
    world.seed()
    world.carry(1, 1, 11, x=60, y=40, end_x=75, end_y=40)
    world.carry(2, 2, 21, x=60, y=40, end_x=61, end_y=40, period=5)
    columns = [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = 'carry_events' ORDER BY ordinal_position")]
    assert columns == ["event_id", "match_id", "idx", "team_id", "team_name", "player_id", "player_name", "period", "minute", "second",
                       "ts_in_period", "x", "y", "end_x", "end_y", "is_progressivo"]
    assert rows(analytics, "SELECT count(*) FROM analytics.carry_events")[0][0] == 2  # todas, marcadas


# --------------------------------------------------------------------------- fronteiras: as mesmas da M5, aplicadas a Carry

@pytest.mark.parametrize("end_x, expected", [(70.0, True), (69.99, False), (70.01, True)])
def test_the_distance_gain_boundary_is_10_yards(world, analytics, end_x, expected):
    assert is_progressive(world, analytics, 60, 40, end_x, 40) is expected


@pytest.mark.parametrize("x, expected", [(47.9, False), (48.0, True), (48.1, True)])
def test_the_start_boundary_is_x_48(world, analytics, x, expected):
    assert is_progressive(world, analytics, x, 40, 70, 40) is expected


def test_a_short_carry_that_enters_the_box_is_progressive_even_without_the_distance_gain(world, analytics):
    assert is_progressive(world, analytics, 101, 40, 102, 40) is True


def test_a_carry_that_ends_just_outside_the_box_is_not_an_entry(world, analytics):
    assert is_progressive(world, analytics, 101, 40, 101.99, 40) is False


@pytest.mark.parametrize("end_y, expected", [(18.0, True), (17.99, False), (62.0, True), (62.01, False)])
def test_entering_through_the_box_sides_isolates_the_y_boundary(world, analytics, end_y, expected):
    assert is_progressive(world, analytics, 101, end_y, 102, end_y) is expected


def test_a_short_carry_inside_the_box_is_not_an_entry_and_not_progressive(world, analytics):
    assert is_progressive(world, analytics, 105, 40, 110, 40) is False


def test_a_long_carry_inside_the_box_still_counts_by_the_distance_gain(world, analytics):
    assert is_progressive(world, analytics, 102, 40, 120, 40) is True


@pytest.mark.parametrize("x, y, end_x, end_y", [(80, 40, 60, 40), (80, 20, 80, 60)], ids=["backward", "lateral"])
def test_backward_and_lateral_carries_are_not_progressive(world, analytics, x, y, end_x, end_y):
    assert is_progressive(world, analytics, x, y, end_x, end_y) is False


@pytest.mark.parametrize("period, expected", [(1, True), (2, True), (3, True), (4, True), (5, False)])
def test_only_the_valid_periods_count(world, analytics, period, expected):
    assert is_progressive(world, analytics, 60, 40, 90, 40, period=period) is expected


# --------------------------------------------------------------------------- contagens e invariantes

def build_carries(world):
    """Time 1: jogador 11 com 2 progressivas de 3 conduções; jogador 12 com 1 de 2. Time 2: nenhuma."""
    world.seed()
    c = lambda idx, player, x, end_x, **kw: world.carry(idx, 1, player, x=x, y=40, end_x=end_x, end_y=40, **kw)
    c(1, 11, 60, 75)
    c(2, 11, 60, 95)
    c(3, 11, 60, 65)                   # ganho de 5: não
    c(4, 12, 50, 80)
    c(5, 12, 40, 80)                   # começa antes de x = 48: não
    c(6, 12, 60, 90, period=5)         # disputa: não


def test_m6_counts_by_team_and_by_player(world, analytics):
    build_carries(world)
    assert team(analytics, 1).conducoes_progressivas == 3
    assert team(analytics, 2).conducoes_progressivas == 0
    assert player(analytics, 11).conducoes_progressivas == 2
    assert player(analytics, 12).conducoes_progressivas == 1
    assert player(analytics, 13).conducoes_progressivas == 0


def test_the_players_add_up_to_the_team(world, analytics):
    build_carries(world)
    by_players = analytics.execute(text(
        "SELECT sum(conducoes_progressivas) FROM analytics.player_match_stats WHERE match_id = 100 AND team_id = 1")).scalar_one()
    assert by_players == team(analytics, 1).conducoes_progressivas


def test_carries_and_passes_do_not_mix(world, analytics):
    """A condução progressiva não conta como passe progressivo, e vice-versa."""
    build_carries(world)
    world.pass_(10, 1, 11, x=60, y=40, end_x=90, end_y=40)
    t = team(analytics, 1)
    assert (t.conducoes_progressivas, t.passes_progressivos) == (3, 1)


def test_m5_and_m6_share_the_same_convention_parameters(world, analytics):
    """Um passe e uma condução com a mesma geometria têm sempre a mesma marcação (fronteiras de ganho e de início)."""
    world.seed()
    cases = [(60, 69.99), (60, 70.0), (47.9, 70.0), (48.0, 70.0)]
    for idx, (x, end_x) in enumerate(cases, start=1):
        world.pass_(idx, 1, 11, x=x, y=40, end_x=end_x, end_y=40)
        world.carry(100 + idx, 1, 11, x=x, y=40, end_x=end_x, end_y=40)
    passes = [r.is_progressivo for r in rows(analytics, "SELECT is_progressivo FROM analytics.pass_events ORDER BY idx")]
    carries = [r.is_progressivo for r in rows(analytics, "SELECT is_progressivo FROM analytics.carry_events ORDER BY idx")]
    assert passes == carries == [False, True, False, True]
