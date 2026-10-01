"""Fixtures dos testes de integração (exigem o PostgreSQL local e o banco `oddvision_test`).

Regras de segurança:
- Sem config/database.toml, os testes de integração são PULADOS (com o motivo).
  Com o arquivo presente e a conexão falhando, os testes FALHAM: um erro de configuração
  nunca pode passar por "tudo verde".
- Só o banco de testes é recriado. O nome vem de `databases.test`, que a configuração já
  obriga a terminar em `_test`, e é conferido de novo no servidor antes de qualquer DROP.
"""

import pytest
from sqlalchemy import text

from oddvision.config import PROJECT_ROOT, database_config_path, ddl_dir
from oddvision.db import apply_ddl, load_database_config, make_engine


@pytest.fixture(scope="session")
def db_config():
    path = database_config_path(PROJECT_ROOT)
    if not path.exists():
        pytest.skip(f"{path.name} não existe: testes de integração pulados (veja o Passo 4 do plano)")
    return load_database_config(path)


@pytest.fixture(scope="session")
def engine(db_config):
    engine = make_engine(db_config, db_config.test_db)
    try:
        with engine.connect() as conn:
            connected_to = conn.execute(text("SELECT current_database()")).scalar_one()
    except Exception as exc:  # noqa: BLE001 - qualquer falha aqui é erro de configuração
        engine.dispose()
        pytest.fail(
            f"não foi possível conectar ao banco de testes '{db_config.test_db}' em "
            f"{db_config.host}:{db_config.port} como '{db_config.user}': {exc}"
        )
    assert connected_to == db_config.test_db and connected_to.endswith("_test")
    yield engine
    engine.dispose()


def reset_schemas(engine) -> None:
    """Apaga core e analytics do banco de TESTES e recria pelo DDL. Recusa qualquer outro banco."""
    with engine.begin() as conn:
        current = conn.execute(text("SELECT current_database()")).scalar_one()
        if not current.endswith("_test"):
            raise RuntimeError(f"recusado: '{current}' não é um banco de testes")
        conn.execute(text("DROP SCHEMA IF EXISTS analytics CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS core CASCADE"))
    apply_ddl(engine, ddl_dir(PROJECT_ROOT))


@pytest.fixture(scope="session")
def schemas(engine):
    """Engine do banco de testes com core e analytics recém-criados pelo DDL."""
    reset_schemas(engine)
    return engine


@pytest.fixture
def fresh_schemas(schemas):
    """Para testes que GRAVAM de verdade (commit): começa e termina com os schemas vazios,
    para não deixar dados que atrapalhem os outros testes."""
    reset_schemas(schemas)
    yield schemas
    reset_schemas(schemas)


@pytest.fixture
def conn(schemas):
    """Conexão dentro de uma transação que é DESFEITA no fim: cada teste começa do zero."""
    with schemas.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()
