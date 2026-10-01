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
