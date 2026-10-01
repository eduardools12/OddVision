"""O app nunca escreve: toda consulta roda numa transação READ ONLY, mesmo com credenciais do dono do banco.

Estes testes gravam de verdade (commit) no banco de TESTES, por isso usam `fresh_schemas`, que o deixa vazio antes e depois.
"""

import psycopg.errors
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from oddvision import app_queries
from oddvision.config import PROJECT_ROOT, analytics_dir
from oddvision.db import apply_analytics


@pytest.fixture
def committed(fresh_schemas):
    """Banco de testes com as views e um time gravado de verdade."""
    with fresh_schemas.begin() as conn:
        conn.execute(text("INSERT INTO core.teams (team_id, team_name) VALUES (1, 'Casa')"))
        apply_analytics(conn, analytics_dir(PROJECT_ROOT))
    return fresh_schemas


def test_a_read_only_connection_reads_the_views(committed):
    with app_queries.read_only_connection(committed) as conn:
        assert app_queries.list_matches(conn).empty            # sem partidas, mas a consulta à view funciona
        assert conn.execute(text("SELECT count(*) FROM core.teams")).scalar_one() == 1


@pytest.mark.parametrize("statement", [
    "INSERT INTO core.teams (team_id, team_name) VALUES (2, 'X')",
    "DELETE FROM core.teams",
    "UPDATE core.teams SET team_name = 'X'",
    "CREATE TABLE analytics.nao_pode (x int)",
    "TRUNCATE core.teams",
])
def test_a_read_only_connection_refuses_every_write(committed, statement):
    # o tipo do erro (SQLSTATE 25006), não o texto: o servidor responde no idioma configurado
    with pytest.raises(DBAPIError) as error:
        with app_queries.read_only_connection(committed) as conn:
            conn.execute(text(statement))
    assert isinstance(error.value.orig, psycopg.errors.ReadOnlySqlTransaction)


def test_the_data_is_untouched_after_refused_writes(committed):
    with pytest.raises(DBAPIError):
        with app_queries.read_only_connection(committed) as conn:
            conn.execute(text("DELETE FROM core.teams"))
    with committed.connect() as conn:
        assert conn.execute(text("SELECT team_name FROM core.teams")).scalar_one() == "Casa"


def test_a_normal_connection_is_not_affected_by_the_read_only_one(committed):
    """A opção vale só para a conexão do app: o pipeline continua escrevendo normalmente."""
    with app_queries.read_only_connection(committed):
        pass
    with committed.begin() as conn:
        conn.execute(text("INSERT INTO core.teams (team_id, team_name) VALUES (2, 'Fora')"))
    with committed.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM core.teams")).scalar_one() == 2
