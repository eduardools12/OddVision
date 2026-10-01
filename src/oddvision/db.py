"""Acesso ao PostgreSQL: configuração, engine e aplicação do DDL (D10, D11).

SQLAlchemy é usado só no nível Core (sem ORM): o SQL continua explícito e visível.
A senha nunca aparece em repr/str/log: `DatabaseConfig` a esconde e a URL do engine a mascara.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import URL, Connection, Engine, create_engine, make_url, text

from oddvision.config import ConfigError, read_toml, require


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)  # fora do repr: não vaza em logs nem em mensagens de erro
    main_db: str  # banco de trabalho do pipeline
    test_db: str  # banco dos testes de integração (sempre termina em _test)


def load_database_config(path: Path) -> DatabaseConfig:
    data = read_toml(path)

    config = DatabaseConfig(
        host=require(data, "connection", "host", str),
        port=require(data, "connection", "port", int),
        user=require(data, "connection", "user", str),
        password=require(data, "connection", "password", str),
        main_db=require(data, "databases", "main", str),
        test_db=require(data, "databases", "test", str),
    )
    if not config.password:
        raise ConfigError("connection.password não pode ser vazio")
    if not config.test_db.endswith("_test"):
        # Os testes de integração RECRIAM os schemas do banco de testes: o nome precisa deixar claro.
        raise ConfigError(f"databases.test deve terminar em '_test' (recebido {config.test_db!r})")
    return config


def make_engine(config: DatabaseConfig, database: str) -> Engine:
    """Engine do SQLAlchemy para `database`. Não conecta até o primeiro uso."""
    url = URL.create(
        "postgresql+psycopg",  # psycopg 3
        username=config.user,
        password=config.password,  # URL.create cuida de escapar caracteres especiais
        host=config.host,
        port=config.port,
        database=database,
    )
    return create_engine(
        url,
        connect_args={"connect_timeout": 10, "client_encoding": "utf8"},
        pool_pre_ping=True,
    )


# Publicação na nuvem: a conexão vem de uma única URL (variável de ambiente ou secret do Streamlit), sem arquivo local.
DATABASE_URL_ENV = "ODDVISION_DATABASE_URL"
# Bancos gratuitos "acordam" devagar (timeout maior) e costumam ficar atrás de um pooler (pgbouncer), que não combina com
# prepared statements do lado do servidor (prepare_threshold=None os desliga). client_encoding igual ao do banco local.
REMOTE_CONNECT_ARGS = {"connect_timeout": 30, "client_encoding": "utf8", "prepare_threshold": None}


def engine_from_url(url: str) -> Engine:
    """Engine a partir de uma URL `postgresql://usuario:senha@host/banco?sslmode=require` (também aceita `postgres://`).

    A senha vem codificada na URL (ex.: `@` vira `%40`) e nunca aparece em repr nem em mensagens de erro: as mensagens
    de erro não repetem a URL. Não conecta até o primeiro uso.
    """
    problem = ConfigError(f"{DATABASE_URL_ENV} inválida: use postgresql://usuario:senha@host/banco?sslmode=require")
    try:
        parsed = make_url((url or "").strip())
    except Exception:  # noqa: BLE001 - a mensagem original pode conter a URL (e a senha)
        raise problem from None
    if parsed.get_backend_name() not in ("postgresql", "postgres") or not parsed.host or not parsed.database:
        raise problem
    connect_args = dict(REMOTE_CONNECT_ARGS)
    if "connect_timeout" in parsed.query:  # o que vier na URL (?connect_timeout=5) vale mais que o padrão
        del connect_args["connect_timeout"]
    return create_engine(
        parsed.set(drivername="postgresql+psycopg"),  # psycopg 3
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=300,  # bancos gratuitos derrubam conexões ociosas
    )


def ddl_files(directory: Path) -> list[Path]:
    """Arquivos .sql do DDL em ordem de nome (001_, 002_…)."""
    if not directory.is_dir():
        raise ConfigError(f"pasta de DDL não encontrada: {directory}")
    files = sorted(directory.glob("*.sql"), key=lambda p: p.name)
    if not files:
        raise ConfigError(f"nenhum arquivo .sql em {directory}")
    return files


def apply_ddl(engine: Engine, directory: Path) -> list[str]:
    """Aplica os arquivos de DDL em ordem, um por transação. Devolve os nomes aplicados.

    O DDL só cria (IF NOT EXISTS) e nunca apaga: repetir é seguro e preserva os dados.
    O psycopg 3 aceita vários comandos numa chamada quando não há parâmetros (é o caso aqui).
    """
    applied = []
    for path in ddl_files(directory):
        with engine.begin() as conn:
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied


def analytics_files(directory: Path) -> list[Path]:
    """Arquivos .sql das views de métricas em ordem de nome. Pasta ausente = nenhum arquivo (não é erro)."""
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.sql"), key=lambda p: p.name)


def apply_analytics(conn: Connection, directory: Path) -> list[str]:
    """Recria as views do schema analytics a partir dos arquivos. Devolve os nomes aplicados.

    As views não guardam dados: apaga as que existem (com as dependentes) e cria de novo na ordem dos arquivos.
    Assim o banco reflete exatamente os arquivos. Se o schema tiver uma TABELA, recusa antes de apagar qualquer
    coisa (o contrato é: só views). Sem arquivos (pasta ausente), não faz nada. A transação é de quem chama.
    """
    files = analytics_files(directory)
    if not files:
        return []
    tables = list(conn.exec_driver_sql(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'analytics' AND table_type = 'BASE TABLE'"
    ).scalars())
    if tables:
        raise ConfigError(f"o schema analytics só pode ter views, mas tem tabela(s): {tables}")
    for view in list(conn.exec_driver_sql("SELECT table_name FROM information_schema.views WHERE table_schema = 'analytics'").scalars()):
        conn.exec_driver_sql('DROP VIEW IF EXISTS analytics."' + view.replace('"', '""') + '" CASCADE')
    for path in files:
        conn.exec_driver_sql(path.read_text(encoding="utf-8"))
    return [path.name for path in files]


def core_table_names(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'core' AND table_type = 'BASE TABLE' ORDER BY table_name"
                )
            ).scalars()
        )
