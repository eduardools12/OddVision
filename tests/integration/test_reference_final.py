"""Teste de REFERÊNCIA: as views de analytics reproduzem, nos dados reais, os valores da final da Copa 2022.

Os valores esperados estão em tests/fixtures/reference_final_3869685.json. Foram calculados no Passo 2 por um
notebook em Python puro, independente do pipeline (docs/data_notes.md). Aqui as views SQL precisam chegar aos mesmos
números a partir dos dados carregados no banco principal.

Os testes só LEEM o banco principal (`databases.main`): as views são aplicadas dentro de uma transação que é desfeita
no fim, então nada muda no seu banco. Sem a final carregada (4.407 eventos), os testes são pulados com o motivo.
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from oddvision.config import PROJECT_ROOT, analytics_dir
from oddvision.db import apply_analytics, make_engine

REFERENCE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "reference_final_3869685.json").read_text(encoding="utf-8"))
FINAL = REFERENCE["match_id"]
TEAMS = REFERENCE["times"]


@pytest.fixture(scope="module")
def final(db_config):
    """Conexão ao banco principal com as views aplicadas numa transação desfeita no fim."""
    engine = make_engine(db_config, db_config.main_db)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        loaded = connection.execute(text("SELECT count(*) FROM core.events WHERE match_id = :m"), {"m": FINAL}).scalar_one()
        if loaded != REFERENCE["eventos_na_partida"]:
            pytest.skip(f"a final não está carregada no banco '{db_config.main_db}' ({loaded} de {REFERENCE['eventos_na_partida']} "
                        "eventos): rode `python -m oddvision.pipeline load`")
        apply_analytics(connection, analytics_dir(PROJECT_ROOT))
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def team_row(final, name):
    return final.execute(text("SELECT * FROM analytics.team_match_stats WHERE match_id = :m AND team_id = :t"),
                         {"m": FINAL, "t": TEAMS[name]["team_id"]}).one()


@pytest.mark.parametrize("name", list(TEAMS))
def test_m1_goals_own_goals_and_shootout_of_the_final(final, name):
    r, expected = team_row(final, name), TEAMS[name]
    assert (r.gols, r.gols_contra_a_favor, r.penaltis_disputa) == (
        expected["gols"], expected["gols_contra_a_favor"], expected["penaltis_disputa"])


def test_m1_the_final_summary_is_3_3_with_a_4_2_shootout(final):
    r = final.execute(text("SELECT * FROM analytics.match_summary WHERE match_id = :m"), {"m": FINAL}).one()
    assert (r.home_team_name, r.away_team_name) == ("Argentina", "France")
    assert (r.home_score, r.away_score) == (3, 3) == (r.home_goals, r.away_goals)
    assert (r.home_penalties, r.away_penalties) == (4, 2)
    assert r.score_matches_events is True


def test_m1_the_goal_scorers_of_the_final(final):
    scorers = {r.player_name: r.gols for r in final.execute(text(
        "SELECT player_name, gols FROM analytics.player_match_stats WHERE match_id = :m AND gols > 0"), {"m": FINAL})}
    assert scorers == REFERENCE["gols_por_jogador"]


@pytest.mark.parametrize("name", list(TEAMS))
def test_m2_shots_and_shots_on_target_of_the_final(final, name):
    r, expected = team_row(final, name), TEAMS[name]
    assert (r.finalizacoes, r.finalizacoes_no_alvo) == (expected["finalizacoes"], expected["finalizacoes_no_alvo"])


@pytest.mark.parametrize("name", list(TEAMS))
def test_m3_xg_npxg_and_the_rate_of_the_final(final, name):
    r, expected = team_row(final, name), TEAMS[name]
    assert r.finalizacoes_sem_penalti == expected["finalizacoes_sem_penalti"]
    assert r.xg == pytest.approx(expected["xg"], abs=1e-4)
    assert r.npxg == pytest.approx(expected["npxg"], abs=1e-4)
    assert r.npxg_por_finalizacao_sem_penalti == pytest.approx(expected["npxg_por_finalizacao_sem_penalti"], abs=1e-4)


def test_m2_m3_the_players_of_the_final_add_up_to_each_team(final):
    for name in TEAMS:
        team = team_row(final, name)
        total = final.execute(text(
            "SELECT sum(finalizacoes) f, sum(finalizacoes_no_alvo) a, sum(xg) xg, sum(npxg) npxg "
            "FROM analytics.player_match_stats WHERE match_id = :m AND team_id = :t"), {"m": FINAL, "t": team.team_id}).one()
        assert (total.f, total.a) == (team.finalizacoes, team.finalizacoes_no_alvo)
        assert total.xg == pytest.approx(team.xg, abs=1e-9) and total.npxg == pytest.approx(team.npxg, abs=1e-9)


def test_m2_m3_every_loaded_match_respects_the_invariants(final):
    broken = final.execute(text(
        "SELECT match_id, team_id FROM analytics.team_match_stats "
        "WHERE finalizacoes_no_alvo > finalizacoes OR npxg > xg + 1e-9 OR finalizacoes_sem_penalti > finalizacoes "
        "OR gols > finalizacoes + gols_contra_a_favor")).all()
    assert broken == []


@pytest.mark.parametrize("name", list(TEAMS))
def test_m4_passes_and_accuracy_of_the_final(final, name):
    r, expected = team_row(final, name), TEAMS[name]
    assert (r.passes_tentados, r.passes_completos) == (expected["passes_tentados"], expected["passes_completos"])
    assert r.pct_acerto_passes == pytest.approx(expected["pct_acerto_passes"], abs=0.1)
    assert r.pct_acerto_passes == pytest.approx(100 * r.passes_completos / r.passes_tentados, abs=1e-9)


def test_m4_the_players_of_the_final_add_up_to_each_team(final):
    for name in TEAMS:
        team = team_row(final, name)
        total = final.execute(text(
            "SELECT sum(passes_tentados) AS tentados, sum(passes_completos) AS completos FROM analytics.player_match_stats "
            "WHERE match_id = :m AND team_id = :t"), {"m": FINAL, "t": team.team_id}).one()
        assert (total.tentados, total.completos) == (team.passes_tentados, team.passes_completos)


def test_m4_every_loaded_match_respects_the_invariants(final):
    broken = final.execute(text(
        "SELECT match_id, team_id FROM analytics.team_match_stats "
        "WHERE passes_completos > passes_tentados OR pct_acerto_passes NOT BETWEEN 0 AND 100")).all()
    assert broken == []


@pytest.mark.parametrize("name", list(TEAMS))
def test_m5_progressive_passes_of_the_final(final, name):
    assert team_row(final, name).passes_progressivos == TEAMS[name]["passes_progressivos"]


def test_m5_the_players_of_the_final_add_up_to_each_team_and_are_a_subset_of_completed_passes(final):
    for name in TEAMS:
        team = team_row(final, name)
        total = final.execute(text(
            "SELECT sum(passes_progressivos) FROM analytics.player_match_stats WHERE match_id = :m AND team_id = :t"),
            {"m": FINAL, "t": team.team_id}).scalar_one()
        assert total == team.passes_progressivos <= team.passes_completos


def test_m5_every_loaded_match_respects_the_subset_invariant(final):
    broken = final.execute(text("SELECT match_id, team_id FROM analytics.team_match_stats WHERE passes_progressivos > passes_completos")).all()
    assert broken == []


@pytest.mark.parametrize("name", list(TEAMS))
def test_m6_progressive_carries_of_the_final(final, name):
    assert team_row(final, name).conducoes_progressivas == TEAMS[name]["conducoes_progressivas"]


def test_m6_the_players_of_the_final_add_up_to_each_team(final):
    for name in TEAMS:
        team = team_row(final, name)
        total = final.execute(text(
            "SELECT sum(conducoes_progressivas) FROM analytics.player_match_stats WHERE match_id = :m AND team_id = :t"),
            {"m": FINAL, "t": team.team_id}).scalar_one()
        assert total == team.conducoes_progressivas


def test_m6_progressive_carries_are_a_subset_of_the_carries(final):
    broken = final.execute(text(
        "SELECT 1 FROM analytics.carry_events WHERE is_progressivo AND (period > 4 OR x < 48)")).all()
    assert broken == []


@pytest.mark.parametrize("name", list(TEAMS))
def test_m7_passes_into_the_box_of_the_final(final, name):
    assert team_row(final, name).passes_para_area == TEAMS[name]["passes_para_area"]


def test_m7_the_players_of_the_final_add_up_to_each_team_and_are_a_subset_of_completed_passes(final):
    for name in TEAMS:
        team = team_row(final, name)
        total = final.execute(text(
            "SELECT sum(passes_para_area) FROM analytics.player_match_stats WHERE match_id = :m AND team_id = :t"),
            {"m": FINAL, "t": team.team_id}).scalar_one()
        assert total == team.passes_para_area <= team.passes_completos


def test_m7_every_loaded_match_respects_the_subset_invariant(final):
    broken = final.execute(text("SELECT match_id, team_id FROM analytics.team_match_stats WHERE passes_para_area > passes_completos")).all()
    assert broken == []


@pytest.mark.parametrize("name", list(TEAMS))
def test_m8_the_cumulative_xg_of_the_final_ends_at_the_team_xg_with_the_penalty_steps(final, name):
    expected = TEAMS[name]
    series = final.execute(text(
        "SELECT xg_acumulado, is_penalty, minute, rotulo FROM analytics.xg_timeline WHERE match_id = :m AND team_id = :t "
        "ORDER BY period, idx"), {"m": FINAL, "t": expected["team_id"]}).all()
    assert series[-1].xg_acumulado == pytest.approx(expected["xg_acumulado_final"], abs=1e-4)
    assert series[-1].xg_acumulado == pytest.approx(team_row(final, name).xg, abs=1e-9)
    assert [r.minute for r in series if r.is_penalty] == expected["degraus_de_penalti_minute"]
    assert [r.rotulo for r in series if r.is_penalty] == [f"{m + 1}'" for m in expected["degraus_de_penalti_minute"]]
    assert all(b.xg_acumulado >= a.xg_acumulado for a, b in zip(series, series[1:]))


def test_m8_the_penalty_steps_are_the_penalty_xg(final):
    steps = final.execute(text(
        "SELECT t.statsbomb_xg, t.xg_acumulado - lag(t.xg_acumulado, 1, 0) OVER (PARTITION BY t.team_id ORDER BY t.period, t.idx) AS step, t.is_penalty "
        "FROM analytics.xg_timeline t WHERE t.match_id = :m"), {"m": FINAL}).all()
    penalties = [r for r in steps if r.is_penalty]
    assert len(penalties) == 3
    assert all(r.step == pytest.approx(0.7835, abs=1e-4) for r in penalties)


def test_m8_every_loaded_match_has_consistent_series_and_a_time_axis_without_overlap(final):
    """Em todas as partidas carregadas: o último ponto é o xG do time, e o tempo cresce com (period, idx)."""
    last_vs_xg = final.execute(text(
        "SELECT t.match_id, t.team_id FROM (SELECT DISTINCT ON (match_id, team_id) match_id, team_id, xg_acumulado "
        "FROM analytics.xg_timeline ORDER BY match_id, team_id, period DESC, idx DESC) t "
        "JOIN analytics.team_match_stats s ON s.match_id = t.match_id AND s.team_id = t.team_id "
        "WHERE abs(t.xg_acumulado - s.xg) > 1e-9")).all()
    assert last_vs_xg == []
    disordered = final.execute(text(
        "SELECT match_id FROM (SELECT match_id, tempo_decorrido_s, "
        "lag(tempo_decorrido_s) OVER (PARTITION BY match_id ORDER BY period, idx) AS previous FROM analytics.xg_timeline) x "
        "WHERE tempo_decorrido_s < previous")).all()
    assert disordered == []


def test_m8_the_long_first_half_of_england_iran_does_not_overlap_the_second(final):
    """Sentinela 3857271 (1º tempo com cerca de 14 minutos de acréscimo): o eixo real separa os dois tempos."""
    loaded = final.execute(text("SELECT count(*) FROM core.events WHERE match_id = 3857271")).scalar_one()
    if not loaded:
        pytest.skip("a partida Inglaterra x Irã (3857271) não está carregada")
    first_half_s = final.execute(text(
        "SELECT max(extract(epoch FROM ts_in_period)) FROM core.events WHERE match_id = 3857271 AND period = 1")).scalar_one()
    assert first_half_s > 50 * 60                       # passou muito dos 45 minutos
    period_2 = final.execute(text(
        "SELECT min(tempo_decorrido_s) FROM analytics.xg_timeline WHERE match_id = 3857271 AND period = 2")).scalar_one()
    period_1 = final.execute(text(
        "SELECT max(tempo_decorrido_s) FROM analytics.xg_timeline WHERE match_id = 3857271 AND period = 1")).scalar_one()
    assert period_1 < period_2 and period_2 >= first_half_s


def test_the_goal_timeline_of_the_final_has_the_six_goals_at_the_known_minutes(final):
    """Fatos públicos da final: Argentina 23' (pênalti), 36' e 108'; França 80' (pênalti), 81' e 118' (pênalti)."""
    goals = final.execute(text(
        "SELECT team_name, player_name, rotulo, detail FROM analytics.match_timeline "
        "WHERE match_id = :m AND incident_type = 'Goal' ORDER BY period, idx"), {"m": FINAL}).all()
    assert [(g.team_name, g.rotulo, g.detail) for g in goals] == [
        ("Argentina", "23'", "Penalty"), ("Argentina", "36'", None), ("France", "80'", "Penalty"),
        ("France", "81'", None), ("Argentina", "108'", None), ("France", "118'", "Penalty")]
    assert [g.player_name for g in goals if g.team_name == "France"] == ["Kylian Mbappé Lottin"] * 3


def test_the_timeline_cards_and_substitutions_of_the_final_match_the_core_counts(final):
    for incident, source in (("Card", "core.cards"), ("Substitution", "core.substitutions")):
        shown = final.execute(text("SELECT count(*) FROM analytics.match_timeline WHERE match_id = :m AND incident_type = :i"),
                              {"m": FINAL, "i": incident}).scalar_one()
        in_core = final.execute(text(
            f"SELECT count(*) FROM {source} x JOIN core.events e USING (event_id) WHERE e.match_id = :m AND e.period <= 4"), {"m": FINAL}).scalar_one()
        assert shown == in_core > 0, incident


def test_the_lineups_of_the_final_have_11_starters_per_team(final):
    starters = dict(final.execute(text(
        "SELECT team_name, count(*) FILTER (WHERE is_starter) FROM analytics.match_lineups WHERE match_id = :m GROUP BY team_name"),
        {"m": FINAL}).all())
    assert starters == {"Argentina": 11, "France": 11}


def test_every_loaded_match_has_goals_in_the_timeline_equal_to_m1_and_11_starters(final):
    wrong_goals = final.execute(text(
        "SELECT s.match_id, s.team_id FROM analytics.team_match_stats s WHERE s.gols <> ("
        "SELECT count(*) FROM analytics.match_timeline t WHERE t.match_id = s.match_id AND t.team_id = s.team_id "
        "AND t.incident_type IN ('Goal', 'Own Goal'))")).all()
    assert wrong_goals == []
    wrong_lineups = final.execute(text(
        "SELECT match_id, team_id FROM analytics.match_lineups WHERE match_id IN (SELECT DISTINCT match_id FROM core.events) "
        "GROUP BY match_id, team_id HAVING count(*) FILTER (WHERE is_starter) <> 11")).all()
    assert wrong_lineups == []


def test_the_shot_map_of_the_final_puts_each_team_on_its_own_side_after_the_mirroring(final):
    """Passo 12: mandante em x >= 60 e visitante em x <= 60 depois do espelhamento (nos dados reais, em jogo)."""
    from oddvision import app_queries
    from oddvision.viz.pitch import flip_frame

    shots = app_queries.shots(final, FINAL)
    shots = shots[~shots["is_shootout"]]
    flipped = flip_frame(shots, TEAMS["Argentina"]["team_id"], pairs=(("x", "y"),))
    home, away = flipped[flipped["team_id"] == TEAMS["Argentina"]["team_id"]], flipped[flipped["team_id"] == TEAMS["France"]["team_id"]]
    assert len(home) == 20 and len(away) == 10
    assert (home["x"] >= 60).all() and (away["x"] <= 60).all()
    assert (flipped["x"].between(0, 120) & flipped["y"].between(0, 80)).all()


def test_the_xg_chart_series_of_the_final_end_at_the_team_xg_and_the_penalty_steps_are_at_the_known_minutes(final):
    from oddvision import app_queries
    from oddvision.viz.pitch import match_end_minutes, xg_series

    xg = app_queries.xg_timeline(final, FINAL)
    bounds = app_queries.period_bounds(final, FINAL)
    end_s = match_end_minutes(bounds) * 60
    assert bounds["period"].tolist() == [1, 2, 3, 4]
    for name, expected in TEAMS.items():
        x, y = xg_series(xg, expected["team_id"], end_s)
        assert y[-1] == pytest.approx(expected["xg_acumulado_final"], abs=1e-4)
        assert list(y) == sorted(y) and list(x) == sorted(x)
        steps = xg[(xg["team_id"] == expected["team_id"]) & xg["is_penalty"]]
        assert steps["rotulo"].tolist() == [f"{m + 1}'" for m in expected["degraus_de_penalti_minute"]]


def test_the_period_axis_of_the_final_has_no_overlap(final):
    from oddvision import app_queries

    bounds = app_queries.period_bounds(final, FINAL)
    assert (bounds["start_s"] < bounds["end_s"]).all()
    # o eixo é contíguo: cada período termina exatamente onde o próximo começa (nunca depois dele)
    assert all(a == pytest.approx(b, abs=1e-9) for a, b in zip(bounds["end_s"].tolist(), bounds["start_s"].tolist()[1:]))


def test_m1_every_loaded_match_reproduces_its_official_score(final):
    wrong = final.execute(text("SELECT match_id FROM analytics.match_summary WHERE has_events AND NOT score_matches_events")).all()
    assert wrong == []
