"""Carga completa (Passo 13): as 64 partidas da Copa 2022 no banco principal, só LENDO.

Pulados quando o banco principal não tem as 64 partidas com eventos (rode `pipeline load` com a seleção completa).
A final e as outras sentinelas continuam sendo a referência dos números; aqui vale a consistência em todas as partidas
e o critério "o app funciona em qualquer partida".
"""

import pytest
from sqlalchemy import text
from streamlit.testing.v1 import AppTest

from oddvision import presentation as p
from oddvision.config import PROJECT_ROOT, manifest_path
from oddvision.db import make_engine
from oddvision.ingest import read_manifest
from oddvision.viz import pitch as viz

MATCHES = 64


@pytest.fixture(scope="module")
def conn(db_config):
    engine = make_engine(db_config, db_config.main_db)
    connection = engine.connect()
    try:
        with_events = connection.execute(text("SELECT count(DISTINCT match_id) FROM core.events")).scalar_one()
        views = connection.execute(text("SELECT count(*) FROM information_schema.views WHERE table_schema = 'analytics'")).scalar_one()
        if with_events != MATCHES or views < 11:
            pytest.skip(f"o banco principal tem {with_events} partidas com eventos e {views} views de analytics: "
                        "rode init-db e load com as 64 partidas")
        yield connection
    finally:
        connection.close()
        engine.dispose()


def scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


# --------------------------------------------------------------------------- dados

def test_all_64_matches_have_events_lineups_and_stats_for_both_teams(conn):
    assert scalar(conn, "SELECT count(*) FROM core.matches") == MATCHES
    assert scalar(conn, "SELECT count(*) FROM analytics.match_summary WHERE has_events") == MATCHES
    assert scalar(conn, "SELECT count(*) FROM analytics.team_match_stats") == 2 * MATCHES
    assert scalar(conn, "SELECT count(DISTINCT match_id) FROM core.lineups") == MATCHES
    assert scalar(conn, "SELECT count(*) FROM analytics.match_lineups WHERE is_starter") == 22 * MATCHES


def test_the_loaded_events_match_the_manifest_of_the_pinned_commit(conn):
    entries = read_manifest(manifest_path(PROJECT_ROOT))
    expected = sum(entry.record_count for path, entry in entries.items() if path.startswith("events/"))
    assert len([path for path in entries if path.startswith("events/")]) == MATCHES
    assert scalar(conn, "SELECT count(*) FROM core.events") == expected


def test_every_official_score_is_reproduced_by_the_events_and_the_totals_agree(conn):
    assert scalar(conn, "SELECT count(*) FROM analytics.match_summary WHERE NOT score_matches_events") == 0
    goals = scalar(conn, "SELECT sum(gols) FROM analytics.team_match_stats")
    official = scalar(conn, "SELECT sum(home_score + away_score) FROM analytics.match_summary")
    assert goals == official == 172                                  # a Copa de 2022 teve 172 gols (incluindo gols contra)


def test_the_copa_2022_known_totals(conn):
    """Totais públicos conferidos nos dados carregados (a Copa de 2022 teve 5 disputas de pênaltis e 228 cartões)."""
    assert scalar(conn, "SELECT count(*) FROM analytics.match_summary WHERE home_penalties IS NOT NULL") == 5
    assert scalar(conn, "SELECT count(*) FROM core.cards") == 228
    assert scalar(conn, "SELECT count(*) FROM core.events WHERE period = 5") == 106       # eventos da disputa (docs/metrics.md)


def test_the_invariants_hold_in_every_match(conn):
    for sql in (
        "SELECT 1 FROM analytics.team_match_stats WHERE finalizacoes_no_alvo > finalizacoes OR npxg > xg + 1e-9 "
        "OR passes_completos > passes_tentados OR passes_progressivos > passes_completos OR passes_para_area > passes_completos",
        # Σ jogadores = time, nas contagens e no xG
        "SELECT 1 FROM analytics.team_match_stats t JOIN (SELECT match_id, team_id, sum(finalizacoes) f, sum(passes_tentados) p, "
        "sum(passes_progressivos) pp, sum(conducoes_progressivas) c, sum(passes_para_area) a, sum(xg) xg FROM analytics.player_match_stats "
        "GROUP BY match_id, team_id) s USING (match_id, team_id) WHERE t.finalizacoes <> s.f OR t.passes_tentados <> s.p "
        "OR t.passes_progressivos <> s.pp OR t.conducoes_progressivas <> s.c OR t.passes_para_area <> s.a OR abs(t.xg - s.xg) > 1e-9",
    ):
        assert conn.execute(text(sql)).all() == [], sql


# --------------------------------------------------------------------------- visualizações em todas as partidas

def test_every_chart_and_table_can_be_built_for_all_64_matches(conn):
    """As views de cada partida, buscadas de uma vez (uma consulta por view) e agrupadas, alimentam todas as figuras e tabelas."""
    import pandas as pd

    def whole(view):
        return pd.read_sql_query(text(f"SELECT * FROM analytics.{view}"), conn)

    matches, xg, bounds, timeline = whole("match_summary"), whole("xg_timeline"), pd.read_sql_query(text(
        "SELECT match_id, period, min(tempo_decorrido_s) AS start_s, max(tempo_decorrido_s) AS end_s FROM analytics.event_clock "
        "GROUP BY match_id, period ORDER BY match_id, period"), conn), whole("match_timeline")
    stats, lineups, shots = whole("team_match_stats"), whole("match_lineups"), pd.read_sql_query(text(
        "SELECT s.*, c.rotulo FROM analytics.shot_events s LEFT JOIN analytics.event_clock c ON c.event_id = s.event_id"), conn)
    assert len(matches) == MATCHES
    for _, header in matches.iterrows():
        match_id, home_id, away_id = header["match_id"], header["home_team_id"], header["away_team_id"]
        names = [(home_id, header["home_team_name"]), (away_id, header["away_team_name"])]
        match_bounds = bounds[bounds["match_id"] == match_id]
        assert not match_bounds.empty
        assert viz.xg_timeline_figure(xg[xg["match_id"] == match_id], match_bounds, names).axes
        assert viz.incident_timeline_figure(timeline[timeline["match_id"] == match_id], home_id, names[0][1], names[1][1], match_bounds).axes
        assert len(p.shot_table(shots[shots["match_id"] == match_id])) >= 1
        assert len(p.comparison_table(stats[stats["match_id"] == match_id]).columns) == 2
        for team_id, _ in names:
            assert len(p.lineup_table(lineups[lineups["match_id"] == match_id], team_id)) >= 11


def test_every_xg_chart_ends_at_the_team_xg_in_all_64_matches(conn):
    last = conn.execute(text(
        "SELECT t.match_id, t.team_id FROM (SELECT DISTINCT ON (match_id, team_id) match_id, team_id, xg_acumulado "
        "FROM analytics.xg_timeline ORDER BY match_id, team_id, period DESC, idx DESC) t "
        "JOIN analytics.team_match_stats s ON s.match_id = t.match_id AND s.team_id = t.team_id WHERE abs(t.xg_acumulado - s.xg) > 1e-9")).all()
    assert last == []
    overlapping = conn.execute(text(
        "SELECT match_id FROM (SELECT match_id, period, min(tempo_decorrido_s) AS s, max(tempo_decorrido_s) AS e FROM analytics.event_clock "
        "GROUP BY match_id, period) x JOIN (SELECT match_id, period - 1 AS prev, min(tempo_decorrido_s) AS s2 FROM analytics.event_clock "
        "GROUP BY match_id, period) y USING (match_id) WHERE x.period = y.prev AND x.e > y.s2 + 1e-9")).all()
    assert overlapping == []


# --------------------------------------------------------------------------- o app em casos de borda

def edge_cases(conn):
    sql = {
        "sem gols": "SELECT match_id FROM analytics.match_summary WHERE home_score = 0 AND away_score = 0 ORDER BY match_id LIMIT 1",
        "disputa de pênaltis": "SELECT match_id FROM analytics.match_summary WHERE home_penalties IS NOT NULL ORDER BY match_id LIMIT 1",
        "gol contra": "SELECT match_id FROM analytics.team_match_stats WHERE gols_contra_a_favor > 0 ORDER BY match_id LIMIT 1",
        "prorrogação": "SELECT match_id FROM core.events WHERE period = 3 ORDER BY match_id LIMIT 1",
    }
    return {name: conn.execute(text(query)).scalar() for name, query in sql.items()}


@pytest.mark.parametrize("case", ["sem gols", "disputa de pênaltis", "gol contra", "prorrogação"])
def test_the_match_page_opens_in_the_edge_cases(conn, case):
    match_id = edge_cases(conn)[case]
    assert match_id is not None, case
    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "pages" / "1_Partida.py"), default_timeout=90).run()
    at.sidebar.selectbox[0].select(match_id).run()
    assert not at.exception, case
    assert len(at.get("image")) == 4
