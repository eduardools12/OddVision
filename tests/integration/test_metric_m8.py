"""M8: xG acumulado ao longo da partida (docs/metrics.md).

View analytics.xg_timeline: uma linha por finalização em tempo válido (períodos 1 a 4, pênaltis incluídos), com o xG
acumulado do time até ela, ordenado por (period, idx), o tempo decorrido em segundos (soma da duração REAL dos períodos
anteriores, vinda do Half End de cada um) e o rótulo em estilo futebol (minute + 1; "45+14'" nos acréscimos).
"""

import pytest
from sqlalchemy import text

APPROX = dict(abs=1e-9)


def rows(conn, sql, **params):
    return conn.execute(text(sql), params).all()


def timeline(conn, team_id=None, match_id=100):
    sql = "SELECT * FROM analytics.xg_timeline WHERE match_id = :m"
    params = {"m": match_id}
    if team_id is not None:
        sql += " AND team_id = :t"
        params["t"] = team_id
    return rows(conn, sql + " ORDER BY team_id, period, idx", **params)


def set_minute(world, event_id, minute):
    """O construtor deriva `minute` do tempo no período; a fonte real tem o minuto decorrido da partida (2º tempo a partir do 45)."""
    world.run("UPDATE core.events SET minute = :m WHERE event_id = :e", m=minute, e=event_id)


def half_end(world, idx, period, ts):
    """Os dois Half End do período (um por time), com o mesmo horário, como na fonte (A6 de docs/data_notes.md)."""
    world.event(idx, "Half End", 1, period=period, ts=ts)
    world.event(idx + 1, "Half End", 2, period=period, ts=ts)


# --------------------------------------------------------------------------- forma da view

def test_xg_timeline_has_the_columns_the_chart_needs(world, analytics):
    world.seed()
    world.shot(1, 1, 11, xg=0.1)
    columns = [r.column_name for r in rows(
        analytics, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = 'xg_timeline' ORDER BY ordinal_position")]
    assert columns == ["event_id", "match_id", "idx", "team_id", "team_name", "player_id", "player_name", "period", "minute", "second",
                       "tempo_decorrido_s", "minuto_futebol", "rotulo", "statsbomb_xg", "is_goal", "is_penalty", "xg_acumulado"]


# --------------------------------------------------------------------------- acumulado

def test_the_cumulative_xg_is_the_running_sum_per_team(world, analytics):
    world.seed()
    world.shot(1, 1, 11, xg=0.10)
    world.shot(2, 2, 21, xg=0.40)
    world.shot(3, 1, 12, xg=0.20)
    world.shot(4, 1, 11, xg=0.30)
    world.shot(5, 2, 22, xg=0.05)
    assert [r.xg_acumulado for r in timeline(analytics, 1)] == pytest.approx([0.10, 0.30, 0.60], **APPROX)
    assert [r.xg_acumulado for r in timeline(analytics, 2)] == pytest.approx([0.40, 0.45], **APPROX)


def test_penalties_are_included_as_a_step_and_the_shootout_is_not(world, analytics):
    world.seed()
    world.shot(1, 1, 11, xg=0.10)
    world.shot(2, 1, 11, xg=0.7835, shot_type="Penalty", outcome="Goal")
    world.shot(3, 1, 11, xg=0.7835, shot_type="Penalty", outcome="Goal", period=5)
    series = timeline(analytics, 1)
    assert [r.xg_acumulado for r in series] == pytest.approx([0.10, 0.8835], **APPROX)
    assert [r.is_penalty for r in series] == [False, True]
    assert [r.period for r in series] == [1, 1]


def test_the_order_is_period_then_idx_never_the_minute(world, analytics):
    """1º tempo longo (minuto 59) e um chute do 2º tempo com minuto MENOR no campo: a soma segue (period, idx)."""
    world.seed()
    half_end(world, 50, 1, 3600)
    first = world.shot(10, 1, 11, xg=0.10, ts=3540)             # 1º tempo, aos 59 min
    second = world.shot(60, 1, 11, xg=0.20, period=2, ts=100)   # 2º tempo
    set_minute(world, first, 58)
    set_minute(world, second, 46)                                # minuto da fonte do 2º tempo < minuto do 1º
    series = timeline(analytics, 1)
    assert [r.idx for r in series] == [10, 60]
    assert [r.xg_acumulado for r in series] == pytest.approx([0.10, 0.30], **APPROX)


def test_the_period_comes_before_the_idx_in_the_order(world, analytics):
    """Na fonte o idx já cresce entre períodos; a regra, porém, é (period, idx), e é ela que o teste fixa:
    um chute do 2º tempo com idx MENOR que o do 1º tempo continua depois dele."""
    world.seed()
    world.shot(90, 1, 11, xg=0.10)                   # 1º tempo, idx alto
    world.shot(20, 1, 11, xg=0.20, period=2)         # 2º tempo, idx baixo
    series = timeline(analytics, 1)
    assert [r.idx for r in series] == [90, 20]
    assert [r.xg_acumulado for r in series] == pytest.approx([0.10, 0.30], **APPROX)


def test_the_last_point_of_each_team_is_its_xg_and_the_series_never_decreases(world, analytics):
    world.seed()
    for idx, (team, player, xg) in enumerate([(1, 11, 0.1), (2, 21, 0.3), (1, 12, 0.0), (1, 11, 0.5), (2, 22, 0.2)], start=1):
        world.shot(idx, team, player, xg=xg)
    world.shot(10, 1, 11, xg=0.7835, shot_type="Penalty", outcome="Goal", period=2)
    for team_id in (1, 2):
        series = [r.xg_acumulado for r in timeline(analytics, team_id)]
        assert series == sorted(series)
        stats = rows(analytics, "SELECT xg FROM analytics.team_match_stats WHERE match_id = 100 AND team_id = :t", t=team_id)[0]
        assert series[-1] == pytest.approx(stats.xg, **APPROX)


def test_a_team_without_shots_has_no_rows_and_the_chart_treats_it_as_constant_zero(world, analytics):
    world.seed()
    world.shot(1, 1, 11, xg=0.1)
    assert timeline(analytics, 2) == []


# --------------------------------------------------------------------------- eixo de tempo real

def test_the_elapsed_time_adds_the_real_duration_of_the_previous_periods(world, analytics):
    """1º tempo com 60 min de duração real: o 2º tempo começa em 3600 s, e não em 2700 s (45 min)."""
    world.seed()
    half_end(world, 50, 1, 3600)
    half_end(world, 90, 2, 2900)
    world.shot(10, 1, 11, xg=0.1, ts=3540)
    world.shot(60, 1, 11, xg=0.1, period=2, ts=100)
    world.shot(95, 1, 11, xg=0.1, period=3, ts=30)
    world.shot(96, 1, 11, xg=0.1, period=3, ts=40)
    assert [r.tempo_decorrido_s for r in timeline(analytics, 1)] == pytest.approx([3540, 3700, 6500 + 30, 6500 + 40], **APPROX)


def test_no_period_overlaps_the_next_on_the_time_axis(world, analytics):
    world.seed()
    half_end(world, 50, 1, 3600)
    half_end(world, 90, 2, 3000)
    world.shot(10, 1, 11, xg=0.1, ts=3599)                      # último instante do 1º tempo
    world.shot(60, 1, 11, xg=0.1, period=2, ts=0)               # primeiro instante do 2º tempo
    world.shot(95, 2, 21, xg=0.1, period=3, ts=0)
    times = [r.tempo_decorrido_s for r in sorted(timeline(analytics), key=lambda r: (r.period, r.idx))]
    assert times == sorted(times) and len(set(times)) == len(times)
    assert times[1] == pytest.approx(3600, **APPROX)


def test_the_two_half_end_events_of_a_period_count_once(world, analytics):
    """Há dois Half End por período, um por time: a duração não pode ser somada duas vezes."""
    world.seed()
    half_end(world, 50, 1, 2800)
    world.shot(60, 1, 11, xg=0.1, period=2, ts=10)
    assert timeline(analytics, 1)[0].tempo_decorrido_s == pytest.approx(2810, **APPROX)


def test_without_a_half_end_the_period_lasts_until_its_last_event(world, analytics):
    world.seed()
    world.event(10, "Pass", 1, 11, ts=2750)
    world.shot(60, 1, 11, xg=0.1, period=2, ts=10)
    assert timeline(analytics, 1)[0].tempo_decorrido_s == pytest.approx(2760, **APPROX)


# --------------------------------------------------------------------------- rótulo

@pytest.mark.parametrize("period, minute, label, football_minute", [
    (1, 0, "1'", 1),
    (1, 22, "23'", 23),            # o exemplo da especificação: minute = 22 é o 23º minuto
    (1, 44, "45'", 45),
    (1, 45, "45+1'", 46),
    (1, 58, "45+14'", 59),         # o 1º tempo chegou ao minuto 59 na Copa
    (2, 45, "46'", 46),
    (2, 89, "90'", 90),
    (2, 90, "90+1'", 91),
    (3, 90, "91'", 91),
    (3, 104, "105'", 105),
    (3, 105, "105+1'", 106),
    (4, 105, "106'", 106),
    (4, 119, "120'", 120),
    (4, 120, "120+1'", 121),
])
def test_the_label_is_football_style(world, analytics, period, minute, label, football_minute):
    world.seed()
    event_id = world.shot(1, 1, 11, xg=0.1, period=period)
    set_minute(world, event_id, minute)
    r = timeline(analytics, 1)[0]
    assert (r.rotulo, r.minuto_futebol) == (label, football_minute)
