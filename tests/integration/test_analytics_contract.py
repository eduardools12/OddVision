"""Contrato da camada analytics: o conjunto de views e as colunas de que a aplicação (Passo 11 em diante) depende.

Se uma coluna sair do lugar ou mudar de nome, a aplicação quebraria em silêncio; aqui isso vira falha de teste.
"""

import pytest
from sqlalchemy import text

VIEWS = {
    "convention_params", "event_clock", "shot_events", "pass_events", "carry_events", "team_match_stats",
    "player_match_stats", "match_summary", "xg_timeline", "match_lineups", "match_timeline",
}

TEAM_STATS = ["match_id", "team_id", "team_name", "is_home", "gols", "gols_contra_a_favor", "penaltis_disputa",
              "finalizacoes", "finalizacoes_no_alvo", "xg", "npxg", "finalizacoes_sem_penalti", "npxg_por_finalizacao_sem_penalti",
              "passes_tentados", "passes_completos", "pct_acerto_passes", "passes_progressivos", "conducoes_progressivas",
              "passes_para_area"]
PLAYER_STATS = ["match_id", "team_id", "player_id", "player_name", "is_starter", "played", "gols"] + TEAM_STATS[7:]


def columns(conn, view):
    return [r.column_name for r in conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'analytics' AND table_name = :v "
        "ORDER BY ordinal_position"), {"v": view})]


def test_the_analytics_schema_has_exactly_the_planned_views_and_nothing_else(analytics):
    objects = analytics.execute(text(
        "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'analytics' AND c.relkind NOT IN ('i', 'S', 'c', 't') ORDER BY c.relname")).all()
    assert {name for name, kind in objects} == VIEWS
    assert {kind for name, kind in objects} == {"v"}   # só views: nenhuma tabela, nada materializado


def test_the_team_and_player_stats_have_the_agreed_columns_in_order(analytics):
    assert columns(analytics, "team_match_stats") == TEAM_STATS
    assert columns(analytics, "player_match_stats") == PLAYER_STATS


def test_the_event_views_start_with_the_same_identity_columns(analytics):
    for view in ("shot_events", "pass_events", "carry_events"):
        cols = columns(analytics, view)
        assert cols[:2] == ["event_id", "match_id"], view
        assert {"idx", "team_id", "team_name", "player_id", "player_name", "period", "x", "y", "end_x", "end_y"} <= set(cols), view


def test_every_metric_column_is_numeric_and_every_flag_is_boolean(analytics):
    types = {(r.table_name, r.column_name): r.data_type for r in analytics.execute(text(
        "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'analytics'"))}
    for view, metric_columns in (("team_match_stats", TEAM_STATS[4:]), ("player_match_stats", PLAYER_STATS[6:])):
        for column in metric_columns:
            assert types[(view, column)] in {"integer", "double precision"}, (view, column)
    flags = [key for key in types if key[1].startswith("is_")]
    assert flags
    assert all(types[key] == "boolean" for key in flags), [key for key in flags if types[key] != "boolean"]


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_every_view_can_be_queried_on_an_empty_database(analytics, view):
    assert analytics.execute(text(f"SELECT count(*) FROM analytics.{view}")).scalar_one() in (0, 1)  # convention_params tem 1 linha
