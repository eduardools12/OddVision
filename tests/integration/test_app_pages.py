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
    engine.dispose()
    if views < 11 or events == 0:
        pytest.skip("o banco principal precisa das views de analytics e da final carregada: rode init-db e load")
    return True


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


def test_a_match_without_events_shows_a_notice_instead_of_failing(loaded, monkeypatch):
    """Com as 64 partidas carregadas nenhuma está sem eventos; a ausência é SIMULADA: o cabeçalho vem como 'sem eventos'
    e o resto (escalações) continua o da final. A página precisa avisar, sem abas de métricas e sem quebrar."""
    from oddvision import app_support

    real = app_support.run_query

    def without_events(name, match_id=None):
        result = real(name, match_id)
        if name == "match_header":
            return {**result, "has_events": False, "home_goals": None, "away_goals": None, "score_matches_events": None,
                    "home_penalties": None, "away_penalties": None}
        return result

    monkeypatch.setattr(app_support, "run_query", without_events)
    at = page().run()
    assert not at.exception
    assert any("ainda não foram carregados" in i.value for i in at.info)
    assert [t.label for t in at.tabs] == []
    assert not any("Disputa de pênaltis" in s.value for s in at.subheader)    # sem eventos não há disputa para mostrar
    assert len(at.dataframe) == 2                                             # só as duas escalações
    assert len(at.get("image")) == 0


# --------------------------------------------------------------------------- publicação: a URL do banco vem dos secrets

def cloud_url(db_config):
    from urllib.parse import quote

    return (f"postgresql://{quote(db_config.user, safe='')}:{quote(db_config.password, safe='')}"
            f"@{db_config.host}:{db_config.port}/{db_config.main_db}")


def test_the_app_reads_the_database_url_from_the_streamlit_secrets(loaded, db_config):
    import streamlit as st

    from oddvision.db import DATABASE_URL_ENV

    st.cache_resource.clear()
    st.cache_data.clear()
    try:
        at = AppTest.from_file(str(APP / "Home.py"), default_timeout=60)
        at.secrets[DATABASE_URL_ENV] = cloud_url(db_config)
        at.run()
        assert not at.exception
        assert at.metric[0].value == "64"
    finally:
        st.cache_resource.clear()
        st.cache_data.clear()


def test_a_connection_failure_shows_a_friendly_message_without_leaking_the_password(loaded):
    import streamlit as st

    from oddvision.db import DATABASE_URL_ENV

    st.cache_resource.clear()
    st.cache_data.clear()
    try:
        at = AppTest.from_file(str(APP / "Home.py"), default_timeout=60)
        at.secrets[DATABASE_URL_ENV] = "postgresql://leitor:SEGREDO-unico@127.0.0.1:1/banco?connect_timeout=2"   # nada escuta na porta 1
        at.run()
        assert not at.exception
        assert any("Não foi possível conectar" in e.value for e in at.error)
        everything = " ".join(str(getattr(el, "value", "")) for el in at.main)
        assert "SEGREDO" not in everything
    finally:
        st.cache_resource.clear()
        st.cache_data.clear()
