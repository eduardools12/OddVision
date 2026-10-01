"""Arquivos de publicação: o script da role de leitura e a configuração das páginas na nuvem."""

import re

import pytest

from oddvision.config import PROJECT_ROOT

READER_SQL = PROJECT_ROOT / "sql" / "deploy" / "reader_role.sql"
APP_FILES = [PROJECT_ROOT / "app" / "Home.py", PROJECT_ROOT / "app" / "pages" / "1_Partida.py"]


def statements(sql):
    code = re.sub(r"--[^\n]*", " ", sql)
    return [s.strip() for s in re.split(r";\s*(?:\n|$)", code) if s.strip()]


def test_the_reader_role_script_exists_and_has_a_placeholder_password():
    sql = READER_SQL.read_text(encoding="utf-8")
    assert "TROQUE-ESTA-SENHA" in sql


def test_the_reader_role_only_creates_a_login_role_and_grants_select_on_analytics():
    sql = READER_SQL.read_text(encoding="utf-8")
    allowed = re.compile(
        r"(CREATE ROLE oddvision_reader LOGIN|DO \$\$.*GRANT CONNECT ON DATABASE.*\$\$|GRANT USAGE ON SCHEMA analytics TO oddvision_reader"
        r"|GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO oddvision_reader"
        r"|ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO oddvision_reader)", re.IGNORECASE | re.DOTALL)
    for statement in statements(sql):
        assert allowed.match(statement), f"comando não permitido: {statement[:80]!r}"


def test_the_reader_role_never_gets_write_privileges_or_access_to_core():
    code = re.sub(r"--[^\n]*", " ", READER_SQL.read_text(encoding="utf-8")).upper()
    for forbidden in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALL PRIVILEGES", "SUPERUSER", "CREATEDB", "CREATEROLE", "SCHEMA CORE", "CORE."):
        assert forbidden not in code, forbidden


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.name)
def test_the_pages_put_src_on_the_import_path_so_the_cloud_does_not_need_to_install_the_package(path):
    code = path.read_text(encoding="utf-8")
    assert "sys.path.insert(0," in code and '"src"' in code
    first_import = min(code.index(marker) for marker in ("from oddvision", "import oddvision") if marker in code)
    assert code.index("sys.path.insert(0,") < first_import, "o caminho precisa ser ajustado antes do primeiro import do oddvision"


def test_the_src_folder_the_pages_point_to_holds_the_package():
    assert (PROJECT_ROOT / "src" / "oddvision" / "__init__.py").is_file()


def test_the_streamlit_secrets_file_is_never_versioned():
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".streamlit/secrets.toml" in ignored


def test_runtime_requirements_have_everything_the_app_imports_and_nothing_for_development():
    text = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    for package in ("streamlit", "pandas", "SQLAlchemy", "psycopg", "mplsoccer"):
        assert package in text
    assert "pytest" not in text and "ipykernel" not in text
