"""Contrato da aplicação: ela só conhece `analytics`, e as consultas moram em `oddvision.app_queries`."""

import re

import pytest

from oddvision.config import PROJECT_ROOT

APP_FILES = sorted((PROJECT_ROOT / "app").rglob("*.py"))
SUPPORT_FILES = [PROJECT_ROOT / "src" / "oddvision" / name for name in ("presentation.py", "app_support.py")]


def test_the_app_has_the_home_and_the_match_page():
    names = {p.relative_to(PROJECT_ROOT / "app").as_posix() for p in APP_FILES}
    assert {"Home.py", "pages/1_Partida.py"} <= names


@pytest.mark.parametrize("path", APP_FILES + SUPPORT_FILES, ids=lambda p: p.name)
def test_the_app_code_never_names_core_or_extra_or_runs_sql(path):
    code = path.read_text(encoding="utf-8")
    assert not re.search(r"\bcore\.", code), f"{path.name}: a aplicação não toca no schema core"
    assert not re.search(r"\bextra\b", code), f"{path.name}: a aplicação não lê colunas extra"
    assert "sqlalchemy.text" not in code and "from sqlalchemy import text" not in code, f"{path.name}: SQL fica em app_queries"
    assert not re.search(r"\b(SELECT|INSERT|UPDATE|DELETE)\b\s", code), f"{path.name}: SQL fica em app_queries"


def test_the_page_labels_the_version_and_the_credits():
    page = (PROJECT_ROOT / "app" / "pages" / "1_Partida.py").read_text(encoding="utf-8")
    home = (PROJECT_ROOT / "app" / "Home.py").read_text(encoding="utf-8")
    assert "OddVision v1" in page and "StatsBomb" in page
    assert "OddVision v1" in home and "StatsBomb" in home
