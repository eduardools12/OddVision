"""Camada de visualização (`oddvision.viz.pitch`): transformações puras e figuras do matplotlib.

O espelhamento do visitante (120 − x, 80 − y) é uma decisão de APRESENTAÇÃO: `analytics` guarda as coordenadas como a fonte
as entrega (cada time ataca para x = 120) e só aqui o visitante é virado para os dois times dividirem um mesmo campo.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from oddvision import presentation as p
from oddvision.viz import pitch as v

HOME, AWAY = 1, 2


# --------------------------------------------------------------------------- espelhamento

def test_the_home_team_is_not_flipped():
    assert v.flip_for_display(100.0, 30.0, HOME, HOME) == (100.0, 30.0)


def test_the_away_team_is_mirrored_in_both_axes():
    assert v.flip_for_display(100.0, 30.0, AWAY, HOME) == (20.0, 50.0)


@pytest.mark.parametrize("x, y", [(0, 0), (120, 80), (60, 40), (101.99, 17.5)])
def test_flipping_twice_gives_back_the_original(x, y):
    fx, fy = v.flip_for_display(x, y, AWAY, HOME)
    assert v.flip_for_display(fx, fy, AWAY, HOME) == pytest.approx((x, y))
    assert (fx, fy) == pytest.approx((120 - x, 80 - y))


def test_the_flip_keeps_every_point_inside_the_pitch():
    for x in (0, 30, 60, 90, 120):
        for y in (0, 20, 40, 80):
            fx, fy = v.flip_for_display(x, y, AWAY, HOME)
            assert 0 <= fx <= 120 and 0 <= fy <= 80


def frame():
    return pd.DataFrame({"team_id": [HOME, AWAY, AWAY], "x": [100.0, 110.0, 90.0], "y": [30.0, 40.0, 10.0],
                         "end_x": [120.0, 120.0, 100.0], "end_y": [40.0, 40.0, 20.0]})


def test_flip_frame_mirrors_only_the_away_rows_and_both_coordinate_pairs_without_touching_the_input():
    source = frame()
    flipped = v.flip_frame(source, HOME)
    assert flipped["x"].tolist() == [100.0, 10.0, 30.0]
    assert flipped["y"].tolist() == [30.0, 40.0, 70.0]
    assert flipped["end_x"].tolist() == [120.0, 0.0, 20.0]
    assert flipped["end_y"].tolist() == [40.0, 40.0, 60.0]
    assert source.equals(frame())                     # a entrada continua intacta


def test_flip_frame_handles_missing_end_columns_and_empty_frames():
    only_start = frame()[["team_id", "x", "y"]]
    assert v.flip_frame(only_start, HOME)["x"].tolist() == [100.0, 10.0, 30.0]
    assert v.flip_frame(frame().iloc[0:0], HOME).empty


def test_after_the_flip_the_home_shots_are_in_the_right_half_and_the_away_shots_in_the_left_half():
    shots = pd.DataFrame({"team_id": [HOME, HOME, AWAY, AWAY], "x": [60.0, 118.0, 61.0, 100.0], "y": [40.0, 30.0, 55.0, 20.0]})
    flipped = v.flip_frame(shots, HOME)
    assert (flipped[flipped["team_id"] == HOME]["x"] >= 60).all()
    assert (flipped[flipped["team_id"] == AWAY]["x"] <= 60).all()


# --------------------------------------------------------------------------- tamanho dos marcadores

def test_marker_size_grows_with_xg_and_is_always_visible():
    sizes = v.shot_sizes(np.array([0.0, 0.05, 0.3, 0.78]))
    assert (sizes > 0).all()
    assert list(sizes) == sorted(sizes) and len(set(sizes)) == 4


# --------------------------------------------------------------------------- série do xG acumulado

def xg_frame():
    return pd.DataFrame({
        "team_id": [HOME, HOME, AWAY, HOME], "tempo_decorrido_s": [600.0, 1500.0, 1800.0, 3000.0],
        "statsbomb_xg": [0.1, 0.7835, 0.2, 0.05], "xg_acumulado": [0.1, 0.8835, 0.2, 0.9335],
        "is_goal": [False, True, False, False], "is_penalty": [False, True, False, False], "rotulo": ["11'", "26'", "31'", "51'"]})


def test_the_xg_series_starts_at_zero_steps_at_each_shot_and_ends_at_the_final_time():
    x, y = v.xg_series(xg_frame(), HOME, end_s=5400.0)
    assert x.tolist() == [0.0, 10.0, 25.0, 50.0, 90.0]            # em minutos decorridos
    assert y.tolist() == pytest.approx([0.0, 0.1, 0.8835, 0.9335, 0.9335])


def test_the_xg_series_never_decreases_and_ends_at_the_team_total():
    x, y = v.xg_series(xg_frame(), HOME, end_s=5400.0)
    assert list(y) == sorted(y) and list(x) == sorted(x)
    assert y[-1] == pytest.approx(0.1 + 0.7835 + 0.05)


def test_a_team_without_shots_is_a_flat_zero_line():
    x, y = v.xg_series(xg_frame(), 99, end_s=5400.0)
    assert x.tolist() == [0.0, 90.0] and y.tolist() == [0.0, 0.0]


def test_the_period_boundaries_are_the_start_of_each_period_after_the_first_in_minutes():
    bounds = pd.DataFrame({"period": [1, 2, 3], "start_s": [0.0, 3600.0, 6900.0], "end_s": [3590.0, 6500.0, 7800.0]})
    assert v.period_boundaries(bounds) == [60.0, 115.0]
    assert v.match_end_minutes(bounds) == pytest.approx(130.0)


# --------------------------------------------------------------------------- figuras

def shots_frame():
    return pd.DataFrame({
        "team_id": [HOME, AWAY, AWAY, HOME], "team_name": ["Casa", "Fora", "Fora", "Casa"], "player_name": ["A", "B", "C", "D"],
        "x": [105.0, 100.0, 90.0, 110.0], "y": [40.0, 30.0, 50.0, 40.0], "statsbomb_xg": [0.3, 0.1, 0.05, 0.78],
        "is_goal": [True, False, False, True], "is_penalty": [False, False, False, True], "is_shootout": [False, False, False, False],
        "outcome": ["Goal", "Saved", "Off T", "Goal"], "rotulo": ["10'", "20'", "30'", "40'"]})


def passes_frame():
    return pd.DataFrame({
        "team_id": [HOME] * 4, "player_id": [11, 11, 12, 12], "player_name": ["A", "A", "B", "B"],
        "x": [50.0, 60.0, 70.0, 90.0], "y": [40.0, 30.0, 20.0, 40.0], "end_x": [60.0, 62.0, 90.0, 110.0], "end_y": [40.0, 30.0, 20.0, 40.0],
        "is_complete": [True, False, True, True], "is_tentado": [True, True, True, True], "is_progressivo": [False, False, True, True],
        "is_passe_para_area": [False, False, False, True]})


def timeline_frame():
    return pd.DataFrame({
        "team_id": [HOME, AWAY, HOME, AWAY, HOME], "incident_type": ["Goal", "Card", "Substitution", "Own Goal", "Card"],
        "detail": [None, "Yellow Card", "Tactical", None, "Red Card"], "tempo_decorrido_s": [600.0, 1200.0, 3000.0, 3400.0, 4000.0],
        "rotulo": ["11'", "21'", "50'", "57'", "67'"], "player_name": ["A", "B", "C", None, "E"]})


def bounds_frame():
    return pd.DataFrame({"period": [1, 2], "start_s": [0.0, 3000.0], "end_s": [2900.0, 5900.0]})


@pytest.fixture
def no_leak():
    before = set(plt.get_fignums())
    yield
    assert set(plt.get_fignums()) == before, "a figura foi criada pelo pyplot e ficou aberta"


def test_the_shot_map_draws_one_marker_per_valid_shot_and_does_not_leak_figures(no_leak):
    figure = v.shot_map_figure(shots_frame(), HOME, "Casa", "Fora")
    assert len(figure.axes[0].collections) >= 1
    assert sum(len(c.get_offsets()) for c in figure.axes[0].collections if len(c.get_offsets())) >= 4


def test_the_shot_map_leaves_the_shootout_out(no_leak):
    shots = shots_frame()
    shots.loc[3, "is_shootout"] = True
    figure = v.shot_map_figure(shots, HOME, "Casa", "Fora")
    assert sum(len(c.get_offsets()) for c in figure.axes[0].collections if len(c.get_offsets())) == 3


def test_the_shot_map_of_a_match_without_shots_is_still_a_pitch(no_leak):
    assert v.shot_map_figure(shots_frame().iloc[0:0], HOME, "Casa", "Fora").axes


def test_the_pass_map_draws_every_pass_of_the_filtered_frame(no_leak):
    figure = v.pass_map_figure(passes_frame(), "Casa")
    drawn = sum(len(c.get_offsets()) for c in figure.axes[0].collections if hasattr(c, "get_offsets"))
    assert drawn >= 4


def test_the_pass_map_of_an_empty_filter_is_still_a_pitch(no_leak):
    assert v.pass_map_figure(passes_frame().iloc[0:0], "Casa").axes


def test_the_xg_chart_has_one_step_line_per_team_and_the_period_lines(no_leak):
    figure = v.xg_timeline_figure(xg_frame(), bounds_frame(), [(HOME, "Casa"), (AWAY, "Fora")])
    ax = figure.axes[0]
    assert len(ax.lines) >= 2 + 1                     # duas séries + a linha do intervalo
    assert ax.get_xlabel() and ax.get_ylabel()


def test_the_incident_timeline_draws_every_incident(no_leak):
    figure = v.incident_timeline_figure(timeline_frame(), HOME, "Casa", "Fora", bounds_frame())
    ax = figure.axes[0]
    assert sum(len(c.get_offsets()) for c in ax.collections) == 5


def test_the_incident_timeline_of_a_match_without_incidents_is_still_a_chart(no_leak):
    assert v.incident_timeline_figure(timeline_frame().iloc[0:0], HOME, "Casa", "Fora", bounds_frame()).axes


# --------------------------------------------------------------------------- filtros do mapa de passes

def test_pass_filters_by_team_player_and_kind():
    frame = passes_frame()
    assert len(p.filter_passes(frame, HOME)) == 4                                          # todos os tentados do time
    assert len(p.filter_passes(frame, HOME, player_id=11)) == 2
    assert len(p.filter_passes(frame, HOME, kind="completos")) == 3
    assert len(p.filter_passes(frame, HOME, kind="incompletos")) == 1
    assert p.filter_passes(frame, HOME, kind="progressivos")["player_id"].tolist() == [12, 12]
    assert len(p.filter_passes(frame, HOME, kind="para_a_area")) == 1


def test_pass_filter_never_returns_passes_that_were_not_attempted_and_other_teams():
    frame = passes_frame()
    frame.loc[0, "is_tentado"] = False
    other = frame.iloc[[1]].copy()
    other["team_id"] = AWAY
    both = pd.concat([frame, other], ignore_index=True)
    assert len(p.filter_passes(both, HOME)) == 3
    assert (p.filter_passes(both, HOME)["team_id"] == HOME).all()


def test_pass_filter_labels_name_every_kind_and_mark_the_convention():
    assert set(p.PASS_KINDS) == {"tentados", "completos", "incompletos", "progressivos", "para_a_area"}
    assert "OddVision v1" in p.PASS_KINDS["progressivos"]
    with pytest.raises(ValueError):
        p.filter_passes(passes_frame(), HOME, kind="inexistente")
