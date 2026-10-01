"""Contrato dos arquivos de sql/analytics/: só definem views (e comentários sobre elas), nada que grave ou apague dados.

O contrato de JSONB (D05) está em test_layer_contract.py. Aqui: o que um arquivo de analytics pode CONTER.
"""

import re

import pytest

from oddvision.config import PROJECT_ROOT

ANALYTICS_DIR = PROJECT_ROOT / "sql" / "analytics"
FILES = sorted(ANALYTICS_DIR.glob("*.sql")) if ANALYTICS_DIR.is_dir() else []
ALLOWED_START = re.compile(r"(CREATE\s+(OR\s+REPLACE\s+)?VIEW\s+analytics\.\w+|COMMENT\s+ON\s+VIEW\s+analytics\.\w+)", re.IGNORECASE)


def statements(sql: str) -> list[str]:
    code = re.sub(r"--[^\n]*", " ", sql)
    code = re.sub(r"'(?:[^']|'')*'", "''", code)  # ponto e vírgula dentro de texto não separa comandos
    return [part.strip() for part in code.split(";") if part.strip()]


def test_the_helper_splits_statements_and_ignores_comments_and_strings():
    sql = "-- comentário; com ponto e vírgula\nCREATE VIEW analytics.a AS SELECT 'a;b' AS t;\nCOMMENT ON VIEW analytics.a IS 'x; y';"
    assert len(statements(sql)) == 2


@pytest.mark.parametrize("sql", [
    "DROP VIEW analytics.a",
    "CREATE TABLE analytics.t (x int)",
    "CREATE VIEW core.v AS SELECT 1",
    "INSERT INTO analytics.a VALUES (1)",
    "UPDATE core.matches SET home_score = 0",
    "DELETE FROM core.events",
    "CREATE VIEW analytics.a AS SELECT 1; DROP TABLE core.events",
])
def test_the_rules_reject_anything_but_views_in_analytics(sql):
    assert any(not ALLOWED_START.match(s) for s in statements(sql))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_an_analytics_file_only_creates_views_in_the_analytics_schema(path):
    for statement in statements(path.read_text(encoding="utf-8")):
        assert ALLOWED_START.match(statement), f"{path.name}: comando não permitido: {statement[:80]!r}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_an_analytics_file_name_starts_with_its_order_number(path):
    assert re.fullmatch(r"\d{2}_[a-z0-9_]+\.sql", path.name), path.name


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_an_analytics_file_has_no_percent_sign(path):
    """O driver (psycopg) lê '%' como início de parâmetro, até dentro de comentário: escreva 'percentual'."""
    assert "%" not in path.read_text(encoding="utf-8"), path.name


def test_every_view_is_defined_before_the_files_that_read_it():
    defined_in = {}
    for path in FILES:
        for view in re.findall(r"CREATE\s+VIEW\s+analytics\.(\w+)", path.read_text(encoding="utf-8"), re.IGNORECASE):
            defined_in[view] = path.name
    for path in FILES:
        code = re.sub(r"--[^\n]*", " ", path.read_text(encoding="utf-8"))
        for view in set(re.findall(r"(?:FROM|JOIN)\s+analytics\.(\w+)", code, re.IGNORECASE)):
            assert defined_in[view] < path.name, f"{path.name} lê analytics.{view}, definida em {defined_in[view]}"
