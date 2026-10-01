"""Suporte do Streamlit: engine e cache das consultas de `oddvision.app_queries`.

Fica separado de `app_queries` (que não conhece o Streamlit) para a consulta continuar testável sem a interface.
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy.exc import OperationalError, ProgrammingError

from oddvision import app_queries
from oddvision.config import ConfigError
from oddvision.db import DATABASE_URL_ENV

ALLOWED_QUERIES = frozenset({"list_matches", "match_header", "team_stats", "lineups", "shots", "passes", "xg_timeline",
                             "match_timeline", "period_bounds"})
CACHE_SECONDS = 600


def _secret_url() -> str | None:
    """URL do banco nos secrets do Streamlit (na nuvem). Sem arquivo de secrets, `st.secrets` levanta erro: vale o resto."""
    try:
        return st.secrets.get(DATABASE_URL_ENV)
    except Exception:  # noqa: BLE001 - sem secrets.toml o acesso falha de formas diferentes entre versões
        return None


@st.cache_resource
def engine():
    """Um engine para todas as sessões (recurso, não dado)."""
    return app_queries.open_engine(_secret_url())


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def run_query(name: str, match_id: int | None = None):
    """Executa uma consulta de `app_queries` e guarda o resultado por 10 minutos (o banco só muda quando o pipeline roda)."""
    if name not in ALLOWED_QUERIES:
        raise ValueError(f"consulta desconhecida: {name}")
    function = getattr(app_queries, name)
    with app_queries.read_only_connection(engine()) as conn:  # o app nunca escreve
        return function(conn) if match_id is None else function(conn, match_id)


def safe_query(name: str, match_id: int | None = None):
    """Como run_query, mas mostra uma mensagem útil e interrompe a página se o banco ou as views não estiverem prontos."""
    try:
        return run_query(name, match_id)
    except ConfigError as error:
        st.error(f"Banco não configurado: {error}")
    except OperationalError:
        st.error("Não foi possível conectar ao PostgreSQL. Confira se o servidor está ligado e os dados de `config/database.toml`.")
    except ProgrammingError:
        st.error("As views de `analytics` não existem neste banco. Rode `python -m oddvision.pipeline init-db` e depois `load`.")
    st.stop()
