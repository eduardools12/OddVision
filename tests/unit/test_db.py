"""Testes de src/oddvision/db.py e dos caminhos de config/database.toml (sem banco de dados).

O que exige um PostgreSQL de verdade fica em tests/integration/.
"""

import re
from pathlib import Path

import pytest

from oddvision.config import PROJECT_ROOT, ConfigError, database_config_path, ddl_dir
from oddvision.db import DatabaseConfig, ddl_files, load_database_config, make_engine

SECRET = "s3cr3t-Ünico"


def write_toml(tmp_path: Path, *, port="1212", test='"oddvision_test"', password=f'"{SECRET}"') -> Path:
    path = tmp_path / "database.toml"
    path.write_text(
        f"""
[connection]
host = "localhost"
port = {port}
user = "oddvision_app"
password = {password}

[databases]
main = "oddvision"
test = {test}
""",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- configuração

def test_load_valid_database_config(tmp_path):
    assert load_database_config(write_toml(tmp_path)) == DatabaseConfig(
        host="localhost", port=1212, user="oddvision_app", password=SECRET,
        main_db="oddvision", test_db="oddvision_test",
    )


def test_password_never_appears_in_repr(tmp_path):
    config = load_database_config(write_toml(tmp_path))
    assert SECRET not in repr(config)
    assert SECRET not in str(config)


def test_test_database_name_must_end_with_test(tmp_path):
    # Trava de segurança: os testes de integração recriam os schemas do banco de teste.
    with pytest.raises(ConfigError, match="_test"):
        load_database_config(write_toml(tmp_path, test='"oddvision"'))


def test_port_must_be_an_integer(tmp_path):
    with pytest.raises(ConfigError, match=r"connection\.port"):
        load_database_config(write_toml(tmp_path, port='"1212"'))


def test_password_must_not_be_empty(tmp_path):
    with pytest.raises(ConfigError, match=r"connection\.password"):
        load_database_config(write_toml(tmp_path, password='""'))


def test_missing_key_names_the_key(tmp_path):
    path = tmp_path / "database.toml"
    path.write_text('[connection]\nhost = "localhost"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match=r"connection\.port"):
        load_database_config(path)


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="não encontrado"):
        load_database_config(tmp_path / "nao_existe.toml")


def test_a_file_saved_with_a_utf8_bom_is_accepted(tmp_path):
    """Editores do Windows (e o Set-Content do PowerShell 5.1) gravam UTF-8 com BOM."""
    path = write_toml(tmp_path)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert load_database_config(path).password == SECRET


def test_example_file_is_a_valid_template():
    """O modelo versionado deve carregar: o autor só troca a senha em config/database.toml."""
    config = load_database_config(PROJECT_ROOT / "config" / "database.example.toml")
    assert (config.host, config.port, config.user) == ("localhost", 1212, "oddvision_app")
    assert (config.main_db, config.test_db) == ("oddvision", "oddvision_test")


def test_project_paths(tmp_path):
    assert database_config_path(tmp_path) == tmp_path / "config" / "database.toml"
    assert ddl_dir(tmp_path) == tmp_path / "sql" / "ddl"


# --------------------------------------------------------------------------- engine (não conecta)

def test_engine_url_targets_the_requested_database(tmp_path):
    config = load_database_config(write_toml(tmp_path))
    engine = make_engine(config, config.test_db)
    try:
        url = engine.url
        assert url.drivername == "postgresql+psycopg"
        assert (url.host, url.port, url.username, url.database) == ("localhost", 1212, "oddvision_app", "oddvision_test")
    finally:
        engine.dispose()


def test_engine_url_hides_the_password_when_printed(tmp_path):
    config = load_database_config(write_toml(tmp_path))
    engine = make_engine(config, config.main_db)
    try:
        assert SECRET not in str(engine.url)
        assert SECRET not in repr(engine.url)
        assert engine.url.password == SECRET  # mas o driver recebe a senha correta
    finally:
        engine.dispose()


def test_engine_accepts_special_characters_in_the_password(tmp_path):
    password = "p@ss/w:rd#1 %"
    config = load_database_config(write_toml(tmp_path, password=f'"{password}"'))
    engine = make_engine(config, config.main_db)
    try:
        assert engine.url.password == password
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- arquivos de DDL

def test_ddl_files_are_sorted_and_only_sql(tmp_path):
    for name in ("010_c.sql", "002_b.sql", "001_a.sql", "README.md"):
        (tmp_path / name).write_text("SELECT 1;", encoding="utf-8")
    assert [p.name for p in ddl_files(tmp_path)] == ["001_a.sql", "002_b.sql", "010_c.sql"]


def test_ddl_files_missing_folder_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="DDL"):
        ddl_files(tmp_path / "nao_existe")


def test_ddl_files_empty_folder_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match=r"\.sql"):
        ddl_files(tmp_path)


REAL_DDL = ddl_dir(PROJECT_ROOT)


def test_real_ddl_files_follow_the_step_4_layout():
    assert [p.name for p in ddl_files(REAL_DDL)] == ["001_schemas.sql", "002_core_tables.sql"]


def _sql_without_comments(path: Path) -> str:
    return "\n".join(line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize("path", ddl_files(REAL_DDL) if REAL_DDL.is_dir() else [], ids=lambda p: p.name)
def test_ddl_never_drops_anything(path):
    """init-db não pode destruir dados (D17): o DDL só cria."""
    # "ON DELETE CASCADE" é permitido (é uma regra de FK); o que não pode existir é um comando que apague.
    assert not re.search(r"\bDROP\b|\bTRUNCATE\b|\bDELETE\s+FROM\b", _sql_without_comments(path), re.IGNORECASE)


@pytest.mark.parametrize("path", ddl_files(REAL_DDL) if REAL_DDL.is_dir() else [], ids=lambda p: p.name)
def test_ddl_is_repeatable(path):
    """Todo CREATE usa IF NOT EXISTS, então `init-db` pode rodar quantas vezes for preciso."""
    sql = _sql_without_comments(path)
    assert not re.search(r"\bCREATE\s+(TABLE|SCHEMA)\s+(?!IF\s+NOT\s+EXISTS)", sql, re.IGNORECASE)
