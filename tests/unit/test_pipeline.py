"""Testes do CLI (src/oddvision/pipeline.py): subcomando `ingest`."""

import pytest

from oddvision.pipeline import main

SELECTION_TOML = """
[source]
repo = "owner/repo"
commit = "{commit}"

[competition]
competition_id = 43
season_id = 106

[load]
match_ids = [101]
"""


@pytest.fixture
def project_root(tmp_path, fake_source):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "selection.toml").write_text(
        SELECTION_TOML.format(commit=fake_source.selection.source_commit), encoding="utf-8"
    )
    return tmp_path


def test_ingest_downloads_and_then_reports_zero_new_downloads(project_root, fake_source, capsys):
    assert main(["ingest"], root=project_root, download=fake_source.download) == 0
    first = capsys.readouterr().out
    assert "6 baixados, 0 existentes" in first
    assert "baixado" in first and "events/101.json" in first

    assert main(["ingest"], root=project_root, download=fake_source.download) == 0
    assert "0 baixados, 6 existentes" in capsys.readouterr().out

    assert (project_root / "data" / "raw" / "statsbomb" / "events" / "101.json").is_file()
    assert (project_root / "data" / "manifests" / "statsbomb_manifest.csv").is_file()


def test_ingest_reports_integrity_errors_with_exit_code_1(project_root, fake_source, capsys):
    main(["ingest"], root=project_root, download=fake_source.download)
    capsys.readouterr()
    (project_root / "data" / "raw" / "statsbomb" / "events" / "101.json").write_bytes(b"[]")

    assert main(["ingest"], root=project_root, download=fake_source.download) == 1
    assert "events/101.json" in capsys.readouterr().err


def test_ingest_reports_a_missing_config_with_exit_code_1(tmp_path, fake_source, capsys):
    assert main(["ingest"], root=tmp_path, download=fake_source.download) == 1
    assert "não encontrado" in capsys.readouterr().err


def test_a_subcommand_is_required():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


# --------------------------------------------------------------------------- init-db (sem banco)

PASSWORD = "s3cr3t-Ünico"


def write_database_toml(root, port=1212):
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "database.toml").write_text(
        f'[connection]\nhost = "localhost"\nport = {port}\nuser = "oddvision_app"\npassword = "{PASSWORD}"\n\n'
        '[databases]\nmain = "oddvision"\ntest = "oddvision_test"\n',
        encoding="utf-8",
    )


def test_init_db_reports_a_missing_database_config(tmp_path, capsys):
    assert main(["init-db"], root=tmp_path) == 1
    assert "não encontrado" in capsys.readouterr().err


def test_init_db_reports_a_missing_ddl_folder(tmp_path, capsys):
    write_database_toml(tmp_path)
    assert main(["init-db"], root=tmp_path) == 1
    assert "DDL" in capsys.readouterr().err


def test_load_reports_a_missing_database_config(project_root, capsys):
    assert main(["load"], root=project_root) == 1
    assert "database.toml" in capsys.readouterr().err


def test_load_reports_a_missing_manifest_before_touching_the_database(project_root, capsys):
    write_database_toml(project_root, port=1)  # se tentasse conectar, falharia por outro motivo
    assert main(["load"], root=project_root) == 1
    err = capsys.readouterr().err
    assert "manifest" in err and "ingest" in err


def test_init_db_reports_an_unreachable_server_without_leaking_the_password(tmp_path, capsys):
    write_database_toml(tmp_path, port=1)  # nada escuta na porta 1
    (tmp_path / "sql" / "ddl").mkdir(parents=True)
    (tmp_path / "sql" / "ddl" / "001_x.sql").write_text("SELECT 1;", encoding="utf-8")

    assert main(["init-db"], root=tmp_path) == 1

    captured = capsys.readouterr()
    assert "não foi possível" in captured.err
    assert "oddvision" in captured.err and "localhost:1" in captured.err
    assert PASSWORD not in captured.err and PASSWORD not in captured.out


# --------------------------------------------------------------------------- --database (verificação em banco vazio)

def ddl_root(tmp_path):
    write_database_toml(tmp_path, port=1)  # nada escuta na porta 1: a mensagem de erro revela o banco que se tentou usar
    (tmp_path / "sql" / "ddl").mkdir(parents=True)
    (tmp_path / "sql" / "ddl" / "001_x.sql").write_text("SELECT 1;", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("command", ["init-db", "load", "check"])
@pytest.mark.parametrize("database", ["postgres", "oddvision_test", "template1", "outro"])
def test_the_database_option_refuses_anything_but_the_main_or_a_verify_database(project_root, capsys, command, database):
    root = ddl_root(project_root)
    assert main(["--database", database, command], root=root) == 1
    err = capsys.readouterr().err
    assert "_verify" in err and database in err
    assert "não foi possível" not in err                       # recusou antes de tentar conectar


def test_the_database_option_targets_the_verify_database_end_to_end(project_root, capsys):
    root = ddl_root(project_root)
    assert main(["--database", "oddvision_verify", "init-db"], root=root) == 1
    err = capsys.readouterr().err
    assert "banco oddvision_verify " in err and "não foi possível" in err     # tentou conectar no banco pedido


@pytest.mark.parametrize("requested, expected", [
    (None, "oddvision"), ("oddvision", "oddvision"), ("oddvision_verify", "oddvision_verify"), ("copa_verify", "copa_verify"),
])
def test_pick_database_accepts_the_main_and_verify_databases(requested, expected):
    from oddvision.db import DatabaseConfig
    from oddvision.pipeline import _pick_database

    config = DatabaseConfig(host="h", port=1, user="u", password="p", main_db="oddvision", test_db="oddvision_test")
    assert _pick_database(config, requested) == expected


@pytest.mark.parametrize("requested", ["postgres", "oddvision_test", "template1", "verify", "oddvision_verify2", ""])
def test_pick_database_refuses_everything_else(requested):
    from oddvision.config import ConfigError
    from oddvision.db import DatabaseConfig
    from oddvision.pipeline import _pick_database

    config = DatabaseConfig(host="h", port=1, user="u", password="p", main_db="oddvision", test_db="oddvision_test")
    with pytest.raises(ConfigError, match="_verify"):
        _pick_database(config, requested)
