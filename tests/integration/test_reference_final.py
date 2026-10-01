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


def test_m1_every_loaded_match_reproduces_its_official_score(final):
    wrong = final.execute(text("SELECT match_id FROM analytics.match_summary WHERE has_events AND NOT score_matches_events")).all()
    assert wrong == []
