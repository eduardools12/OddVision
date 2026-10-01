"""As páginas do Streamlit rodam de ponta a ponta (AppTest) contra o banco principal, só LENDO `analytics`.

Pulados quando a final não está carregada no banco principal (mesmo critério do teste de referência).
"""

import pytest
from sqlalchemy import text
from streamlit.testing.v1 import AppTest

from oddvision.config import PROJECT_ROOT
from oddvision.db import make_engine

APP = PROJECT_ROOT / "app"
FINAL, ENGLAND_IRAN, CANADA_MOROCCO = 3869685, 3857271, 3857276


@pytest.fixture(scope="module")
def loaded(db_config):
    engine = make_engine(db_config, db_config.main_db)
    with engine.connect() as conn:
        views = conn.execute(text("SELECT count(*) FROM information_schema.views WHERE table_schema = 'analytics'")).scalar_one()
        events = conn.execute(text("SELECT count(*) FROM core.events WHERE match_id = :m"), {"m": FINAL}).scalar_one()
        without = conn.execute(text("SELECT match_id FROM analytics.match_summary WHERE NOT has_events ORDER BY match_id LIMIT 1")).scalar()
    engine.dispose()
    if views < 11 or events == 0:
        pytest.skip("o banco principal precisa das views de analytics e da final carregada: rode init-db e load")
    return {"without_events": without}


def page(name="pages/1_Partida.py"):
    return AppTest.from_file(str(APP / name), default_timeout=60)


def texts(elements):
    return [e.value for e in elements]


def test_the_home_page_runs_and_shows_the_credits(loaded):
    at = AppTest.from_file(str(APP / "Home.py"), default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "OddVision"
    assert any("StatsBomb" in c.value for c in at.caption)
    assert at.metric[0].value == "64"


def test_the_match_page_opens_the_final_with_the_official_score_and_the_shootout(loaded):
    at = page().run()
    assert not at.exception
    assert at.title[0].value == "Argentina 3 – 3 France"
    assert "Disputa de pênaltis: Argentina 4 – 2 France" in texts(at.subheader)
    assert "OddVision v1" in " ".join(texts(at.caption))


def test_the_final_page_has_the_stats_the_incidents_the_shots_and_the_lineups(loaded):
    at = page().run()
    labels = [t.label for t in at.tabs]
    assert labels == ["Estatísticas", "xG acumulado", "Linha do tempo", "Finalizações", "Passes", "Escalações"]
    tab = dict(zip(labels, at.tabs))
    stats = tab["Estatísticas"].dataframe[0].value
    incidents = tab["Linha do tempo"].dataframe[0].value
    shots = tab["Finalizações"].dataframe[0].value
    lineup_argentina, lineup_france = (d.value for d in tab["Escalações"].dataframe)
    assert incidents[incidents["Incidente"] == "Gol"]["Minuto"].tolist() == ["23'", "36'", "80'", "81'", "108'", "118'"]
    assert len(at.get("image")) == 4                           # xG, linha do tempo, mapa de finalizações e mapa de passes
    assert stats.loc["Gols"].tolist() == ["3", "3"]
    assert stats.loc["Passes progressivos (OddVision v1)"].tolist() == ["56", "39"]
    assert (lineup_argentina["Situação"] == "Titular").sum() == 11
    assert (lineup_france["Situação"] == "Titular").sum() == 11
    shootout = shots["Minuto"] == "Disputa"
    assert (~shootout).sum() == 30                            # 20 da Argentina + 10 da França em tempo válido (M2)
    assert shootout.sum() == 8                                # 4 cobranças de cada time na disputa
    assert shots["Minuto"].iloc[-1] == "Disputa"              # a disputa vem por último


@pytest.mark.parametrize("match_id", [ENGLAND_IRAN, CANADA_MOROCCO])
def test_the_other_sentinels_open_without_error(loaded, match_id):
    at = page().run()
    at.sidebar.selectbox[0].select(match_id).run()
    assert not at.exception
    assert len(at.dataframe) >= 4
    assert len(at.get("image")) == 4


@pytest.mark.parametrize("team_index", [0, 1])
@pytest.mark.parametrize("kind", ["tentados", "completos", "incompletos", "progressivos", "para_a_area"])
def test_every_pass_filter_combination_renders_for_both_teams(loaded, team_index, kind):
    at = page().run()
    at.radio[0].set_value(at.radio[0].options[team_index]).run()
    at.selectbox[1].select(kind).run()                       # [0] jogador, [1] tipo de passe; a partida (barra lateral) é a última
    assert not at.exception
    assert len(at.get("image")) == 4


def test_filtering_the_pass_map_by_player_renders(loaded):
    at = page().run()
    at.selectbox[0].select_index(1).run()                    # o primeiro jogador depois de "Todos os jogadores"
    assert not at.exception
    assert len(at.get("image")) == 4


def test_a_match_without_events_shows_a_notice_instead_of_failing(loaded):
    at = page().run()
    at.sidebar.selectbox[0].select(loaded["without_events"]).run()
    assert not at.exception
    assert any("ainda não foram carregados" in i.value for i in at.info)
    assert [t.label for t in at.tabs] == []
