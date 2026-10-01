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


def test_m1_every_loaded_match_reproduces_its_official_score(final):
    wrong = final.execute(text("SELECT match_id FROM analytics.match_summary WHERE has_events AND NOT score_matches_events")).all()
    assert wrong == []
