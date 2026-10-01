"""Testes de como as views do schema analytics são aplicadas (db.apply_analytics e o comando init-db).

Política (D29): as views não guardam dados, então `init-db` apaga as views do schema e as recria a partir dos arquivos
de sql/analytics/. Assim o banco reflete exatamente os arquivos (uma view removida do repositório some do banco, e
mudar as colunas de uma view não esbarra no CREATE OR REPLACE). Tabelas no schema analytics são recusadas.
"""

import json
import shutil

import pytest
from sqlalchemy import text

from oddvision.config import PROJECT_ROOT, ConfigError, analytics_dir, ddl_dir
from oddvision.db import analytics_files, apply_analytics
from oddvision.pipeline import main


def views(conn):
    return sorted(conn.execute(text("SELECT table_name FROM information_schema.views WHERE table_schema = 'analytics'")).scalars())


def write(directory, name, sql):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(sql, encoding="utf-8")


def test_apply_creates_the_views_in_file_order(conn, tmp_path):
    write(tmp_path, "10_a.sql", "CREATE VIEW analytics.a AS SELECT 1 AS x;")
    write(tmp_path, "20_b.sql", "CREATE VIEW analytics.b AS SELECT x + 1 AS y FROM analytics.a;")  # depende da anterior

    assert apply_analytics(conn, tmp_path) == ["10_a.sql", "20_b.sql"]

    assert views(conn) == ["a", "b"]
    assert conn.execute(text("SELECT y FROM analytics.b")).scalar_one() == 2


def test_apply_can_be_repeated_even_if_the_columns_of_a_view_change(conn, tmp_path):
    write(tmp_path, "10_a.sql", "CREATE VIEW analytics.a AS SELECT 1 AS x;")
    apply_analytics(conn, tmp_path)

    write(tmp_path, "10_a.sql", "CREATE VIEW analytics.a AS SELECT 'novo' AS texto, 2 AS y;")  # outras colunas
    apply_analytics(conn, tmp_path)

    assert conn.execute(text("SELECT texto, y FROM analytics.a")).one() == ("novo", 2)


def test_a_view_that_left_the_repository_leaves_the_database(conn, tmp_path):
    write(tmp_path, "10_a.sql", "CREATE VIEW analytics.a AS SELECT 1 AS x;")
    write(tmp_path, "20_b.sql", "CREATE VIEW analytics.b AS SELECT 2 AS x;")
    apply_analytics(conn, tmp_path)

    (tmp_path / "20_b.sql").unlink()
    apply_analytics(conn, tmp_path)

    assert views(conn) == ["a"]


def test_apply_never_touches_core_data(conn, tmp_path):
    conn.execute(text("INSERT INTO core.teams (team_id, team_name) VALUES (1, 'A')"))
    write(tmp_path, "10_a.sql", "CREATE VIEW analytics.a AS SELECT team_name FROM core.teams;")

    apply_analytics(conn, tmp_path)
    apply_analytics(conn, tmp_path)

    assert conn.execute(text("SELECT team_name FROM analytics.a")).scalar_one() == "A"
    assert conn.execute(text("SELECT count(*) FROM core.teams")).scalar_one() == 1


def test_a_base_table_in_analytics_is_refused_and_nothing_is_dropped(conn, tmp_path):
    write(tmp_path, "10_a.sql", "CREATE VIEW analytics.a AS SELECT 1 AS x;")
    apply_analytics(conn, tmp_path)
    conn.execute(text("CREATE TABLE analytics.intrusa (x integer)"))  # o contrato diz: só views

    with pytest.raises(ConfigError, match="intrusa"):
        apply_analytics(conn, tmp_path)
    assert "a" in views(conn)  # recusou antes de apagar qualquer coisa


def test_a_missing_folder_changes_nothing(conn, tmp_path):
    write(tmp_path, "10_a.sql", "CREATE VIEW analytics.a AS SELECT 1 AS x;")
    apply_analytics(conn, tmp_path)

    assert apply_analytics(conn, tmp_path / "nao_existe") == []
    assert views(conn) == ["a"]  # não apagou as views por causa de uma pasta ausente


def test_only_sql_files_are_applied_in_name_order(tmp_path):
    write(tmp_path, "20_b.sql", "SELECT 1;")
    write(tmp_path, "10_a.sql", "SELECT 1;")
    write(tmp_path, "README.md", "x")
    assert [p.name for p in analytics_files(tmp_path)] == ["10_a.sql", "20_b.sql"]


def test_a_failing_file_leaves_the_transaction_to_be_rolled_back(conn, tmp_path):
    write(tmp_path, "10_a.sql", "CREATE VIEW analytics.a AS SELECT 1 AS x;")
    write(tmp_path, "20_b.sql", "CREATE VIEW analytics.b AS SELECT * FROM tabela_que_nao_existe;")
    with pytest.raises(Exception):
        apply_analytics(conn, tmp_path)


# --------------------------------------------------------------------------- comando init-db

def test_init_db_applies_the_analytics_views_and_reports_them(fresh_schemas, db_config, tmp_path, capsys):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "database.toml").write_text(
        f"[connection]\nhost = {json.dumps(db_config.host)}\nport = {db_config.port}\n"
        f"user = {json.dumps(db_config.user)}\npassword = {json.dumps(db_config.password)}\n\n"
        f"[databases]\nmain = {json.dumps(db_config.test_db)}\ntest = {json.dumps(db_config.test_db)}\n", encoding="utf-8")
    shutil.copytree(ddl_dir(PROJECT_ROOT), ddl_dir(tmp_path))
    write(analytics_dir(tmp_path), "10_a.sql", "CREATE VIEW analytics.a AS SELECT 1 AS x;")

    for _ in range(2):
        assert main(["init-db"], root=tmp_path) == 0
        out = capsys.readouterr().out
        assert "12 tabelas" in out and "analytics: 1 arquivo" in out and "10_a.sql" in out
    with fresh_schemas.connect() as c:
        assert views(c) == ["a"]
