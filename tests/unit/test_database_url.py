"""Conexão por URL (publicação na nuvem): a senha nunca vaza e os erros não repetem a URL."""

import pytest

from oddvision import app_queries
from oddvision.config import ConfigError
from oddvision.db import DATABASE_URL_ENV, engine_from_url

PASSWORD = "p@ss/w:rd#Ünico"
URL = "postgresql://reader:p%40ss%2Fw%3Ard%23%C3%9Cnico@ep-exemplo.neon.tech/neondb?sslmode=require"


@pytest.mark.parametrize("scheme", ["postgresql", "postgres", "postgresql+psycopg"])
def test_every_common_scheme_becomes_the_psycopg_driver(scheme):
    engine = engine_from_url(URL.replace("postgresql", scheme, 1))
    assert engine.url.drivername == "postgresql+psycopg"
    assert (engine.url.host, engine.url.database, engine.url.username) == ("ep-exemplo.neon.tech", "neondb", "reader")
    assert engine.url.query.get("sslmode") == "require"


def test_the_password_is_decoded_but_never_shown():
    engine = engine_from_url(URL)
    assert engine.url.password == PASSWORD
    assert PASSWORD not in repr(engine) and PASSWORD not in str(engine.url) and "p%40ss" not in repr(engine)


def test_the_remote_engine_waits_longer_for_a_cold_start_and_avoids_server_side_prepared_statements():
    """Bancos gratuitos acordam devagar e costumam ficar atrás de um pooler (pgbouncer)."""
    engine = engine_from_url(URL)
    connect_args = engine.dialect.create_connect_args(engine.url)[1]
    assert connect_args["sslmode"] == "require"
    # os connect_args extras ficam no pool; o importante é o contrato: timeout maior e sem prepared statements
    from oddvision.db import REMOTE_CONNECT_ARGS
    assert REMOTE_CONNECT_ARGS["connect_timeout"] >= 30 and REMOTE_CONNECT_ARGS["prepare_threshold"] is None


@pytest.mark.parametrize("bad", ["", "   ", "mysql://u:p@h/d", "postgresql://", "postgresql://u:SEGREDO@/d", "postgresql://u:SEGREDO@host", "não é uma url SEGREDO"])
def test_a_bad_url_is_rejected_without_echoing_it(bad):
    with pytest.raises(ConfigError) as error:
        engine_from_url(bad)
    assert "SEGREDO" not in str(error.value) and DATABASE_URL_ENV in str(error.value)


def test_open_engine_prefers_an_explicit_url_over_the_toml_file(monkeypatch, tmp_path):
    monkeypatch.setenv(DATABASE_URL_ENV, URL)
    assert app_queries.open_engine().url.host == "ep-exemplo.neon.tech"


def test_open_engine_accepts_a_url_passed_by_the_caller(monkeypatch):
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert app_queries.open_engine(URL).url.host == "ep-exemplo.neon.tech"


def test_open_engine_without_url_or_toml_explains_both_options(monkeypatch, tmp_path):
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    monkeypatch.setattr(app_queries, "PROJECT_ROOT", tmp_path)
    with pytest.raises(ConfigError) as error:
        app_queries.open_engine()
    assert DATABASE_URL_ENV in str(error.value) and "database.toml" in str(error.value)


def test_a_connect_timeout_in_the_url_wins_over_the_default():
    from oddvision.db import REMOTE_CONNECT_ARGS

    default = engine_from_url(URL)
    custom = engine_from_url(URL + "&connect_timeout=2")
    assert custom.url.query["connect_timeout"] == "2"
    assert "connect_timeout" not in default.url.query and REMOTE_CONNECT_ARGS["connect_timeout"] == 30
