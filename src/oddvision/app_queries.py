"""Consultas da aplicação Streamlit.

A aplicação só lê o schema `analytics` (nunca `core`, nunca colunas `extra`): um teste confere o texto de cada consulta.
As funções recebem uma conexão SQLAlchemy e devolvem DataFrames (ou um dicionário) sem tipos do NumPy, prontos para
`oddvision.presentation` e para o Streamlit. O cache fica na camada do Streamlit, não aqui.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Connection, text

from oddvision.config import ConfigError, PROJECT_ROOT, database_config_path
from oddvision.db import load_database_config, make_engine

QUERIES = {
    "list_matches": "SELECT * FROM analytics.match_summary ORDER BY match_date, match_id",
    "match_header": "SELECT * FROM analytics.match_summary WHERE match_id = :m",
    "team_stats": "SELECT * FROM analytics.team_match_stats WHERE match_id = :m ORDER BY is_home DESC",
    "lineups": "SELECT * FROM analytics.match_lineups WHERE match_id = :m",
    "shots": ("SELECT s.*, c.rotulo FROM analytics.shot_events s "
              "LEFT JOIN analytics.event_clock c ON c.event_id = s.event_id WHERE s.match_id = :m"),
}


def open_engine():
    """Engine do banco principal (`databases.main`). Levanta ConfigError se `config/database.toml` não existir."""
    path = database_config_path(PROJECT_ROOT)
    if not path.is_file():
        raise ConfigError(f"arquivo de configuração do banco não encontrado: {path} (copie config/database.example.toml)")
    config = load_database_config(path)
    return make_engine(config, config.main_db)


def _frame(conn: Connection, name: str, **params) -> pd.DataFrame:
    return pd.read_sql_query(text(QUERIES[name]), conn, params=params)


def _python_value(value):
    """NULL vira None (nunca NaN) e escalares do NumPy viram tipos do Python."""
    if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def list_matches(conn: Connection) -> pd.DataFrame:
    return _frame(conn, "list_matches")


def match_header(conn: Connection, match_id: int) -> dict | None:
    frame = _frame(conn, "match_header", m=match_id)
    if frame.empty:
        return None
    return {column: _python_value(frame.iloc[0][column]) for column in frame.columns}


def team_stats(conn: Connection, match_id: int) -> pd.DataFrame:
    return _frame(conn, "team_stats", m=match_id)


def lineups(conn: Connection, match_id: int) -> pd.DataFrame:
    return _frame(conn, "lineups", m=match_id)


def shots(conn: Connection, match_id: int) -> pd.DataFrame:
    return _frame(conn, "shots", m=match_id)
