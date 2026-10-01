"""Contrato das camadas (D05, D15): o schema `analytics` NUNCA lê JSONB.

O `core` guarda o que a fonte traz e o modelo ainda não usa em colunas `extra JSONB`. Uma métrica que dependesse
dessas colunas dependeria de campos sem tipo nem documentação. Por isso as views de sql/analytics/ não podem usar
operadores JSON, funções JSON nem a coluna `extra`. (Os checks de sql/checks/ PODEM: não são `analytics`.)
"""

import re

import pytest

from oddvision.config import PROJECT_ROOT

ANALYTICS_DIR = PROJECT_ROOT / "sql" / "analytics"

# operadores (-> ->> #> #>> @> <@ ? ?| ?&), funções json/jsonb e a coluna extra
JSON_USE = re.compile(r"->>?|#>>?|@>|<@|\?|\bjsonb?_\w+|\bto_jsonb?\b|\bjson_\w+|\bextra\b", re.IGNORECASE)


def strip_comments_and_literals(sql: str) -> str:
    """Tira comentários e textos entre aspas: '->' dentro de uma string não é um operador."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def json_violations(sql: str) -> list[str]:
    return [m.group(0) for m in JSON_USE.finditer(strip_comments_and_literals(sql))]


# --------------------------------------------------------------------------- o verificador em si

@pytest.mark.parametrize("sql", [
    "SELECT extra->'cards' FROM core.lineups",
    "SELECT extra ->> 'k' FROM core.events",
    "SELECT extra #> '{a,b}' FROM core.events",
    "SELECT extra #>> '{a,b}' FROM core.events",
    "SELECT * FROM core.events WHERE extra @> '{\"a\": 1}'",
    "SELECT * FROM core.events WHERE extra ? 'shot'",
    "SELECT * FROM core.events WHERE extra ?| array['a']",
    "SELECT jsonb_array_elements(extra->'x') FROM core.events",
    "SELECT jsonb_each(e.extra) FROM core.events e",
    "SELECT to_jsonb(e) FROM core.events e",
    "SELECT json_extract_path(x, 'a') FROM t",
    "SELECT e.extra FROM core.events e",
    "SELECT EXTRA FROM core.events",
], ids=lambda sql: sql[:40])
def test_the_scanner_catches_every_form_of_json_access(sql):
    assert json_violations(sql), sql


@pytest.mark.parametrize("sql", [
    "SELECT team_id, count(*) FROM core.shots GROUP BY team_id",
    "SELECT x - y FROM core.events WHERE x > 1 AND y < 2",
    "SELECT 'texto com -> e extra e ?' AS nota",
    "-- extra e jsonb_each em um comentário\nSELECT 1",
    "/* extra -> 'x' */ SELECT 1",
    "SELECT outcome FROM core.shots WHERE outcome <> 'Goal'",
], ids=lambda sql: sql[:40])
def test_the_scanner_does_not_flag_sql_that_does_not_read_json(sql):
    assert json_violations(sql) == [], sql


def test_the_scanner_ignores_quotes_escaped_inside_a_string():
    assert json_violations("SELECT 'it''s extra' AS t") == []


# --------------------------------------------------------------------------- os arquivos reais

def test_no_analytics_view_reads_jsonb():
    offenders = {}
    for path in sorted(ANALYTICS_DIR.rglob("*.sql")) if ANALYTICS_DIR.is_dir() else []:
        found = json_violations(path.read_text(encoding="utf-8"))
        if found:
            offenders[path.name] = found
    assert offenders == {}, f"views de analytics que leem JSONB: {offenders}"


def test_the_quality_checks_are_allowed_to_read_jsonb_because_they_are_not_analytics():
    """O C09 compara com lineups.extra->'cards': isso é permitido fora de sql/analytics/."""
    checks = PROJECT_ROOT / "sql" / "checks"
    if not checks.is_dir():
        pytest.skip("sql/checks ainda não existe")
    assert any(json_violations(p.read_text(encoding="utf-8")) for p in checks.glob("*.sql"))
