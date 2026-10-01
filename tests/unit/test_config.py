"""Testes de src/oddvision/config.py: leitura e validação de config/selection.toml."""

from pathlib import Path

import pytest

from oddvision.config import (
    PROJECT_ROOT,
    ConfigError,
    Selection,
    manifest_path,
    raw_dir,
    selection_path,
    load_selection,
)

VALID_COMMIT = "4b73468fc5b0f1950f9f66fada70ad3a4f9327cb"


def write_toml(tmp_path: Path, *, repo='"hudl/open-data"', commit=f'"{VALID_COMMIT}"',
               match_ids="[3869685, 3857276]", extra="") -> Path:
    path = tmp_path / "selection.toml"
    path.write_text(
        f"""
[source]
repo = {repo}
commit = {commit}

[competition]
competition_id = 43
season_id = 106

[load]
match_ids = {match_ids}
{extra}
""",
        encoding="utf-8",
    )
    return path


def test_load_valid_selection(tmp_path):
    selection = load_selection(write_toml(tmp_path))
    assert selection == Selection(
        source_repo="hudl/open-data",
        source_commit=VALID_COMMIT,
        competition_id=43,
        season_id=106,
        load_match_ids=(3869685, 3857276),
    )


def test_base_url_is_pinned_to_the_commit(tmp_path):
    selection = load_selection(write_toml(tmp_path))
    assert selection.base_url == (
        f"https://raw.githubusercontent.com/hudl/open-data/{VALID_COMMIT}/data/"
    )


@pytest.mark.parametrize("bad_commit", ["master", "main", "4b73468", VALID_COMMIT.upper(), VALID_COMMIT + "0"])
def test_commit_must_be_a_full_lowercase_sha(tmp_path, bad_commit):
    # Um nome de branch ("master") NÃO fixa nada: o conteúdo mudaria com o tempo (D04).
    with pytest.raises(ConfigError, match="commit"):
        load_selection(write_toml(tmp_path, commit=f'"{bad_commit}"'))


@pytest.mark.parametrize("bad_repo", ["hudl", "hudl/open-data/extra", "/open-data", ""])
def test_repo_must_be_owner_slash_name(tmp_path, bad_repo):
    with pytest.raises(ConfigError, match="repo"):
        load_selection(write_toml(tmp_path, repo=f'"{bad_repo}"'))


def test_duplicate_match_ids_are_rejected(tmp_path):
    with pytest.raises(ConfigError, match="repetido"):
        load_selection(write_toml(tmp_path, match_ids="[1, 2, 1]"))


def test_match_ids_must_be_integers(tmp_path):
    with pytest.raises(ConfigError, match="match_ids"):
        load_selection(write_toml(tmp_path, match_ids='["3869685"]'))


def test_missing_key_names_the_key(tmp_path):
    path = tmp_path / "selection.toml"
    path.write_text('[source]\nrepo = "hudl/open-data"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match=r"source\.commit"):
        load_selection(path)


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="não encontrado"):
        load_selection(tmp_path / "nao_existe.toml")


def test_invalid_toml_is_a_config_error(tmp_path):
    path = tmp_path / "selection.toml"
    path.write_text("isto = não é [toml", encoding="utf-8")
    with pytest.raises(ConfigError, match="TOML"):
        load_selection(path)


def test_project_paths(tmp_path):
    assert selection_path(tmp_path) == tmp_path / "config" / "selection.toml"
    assert raw_dir(tmp_path) == tmp_path / "data" / "raw" / "statsbomb"
    assert manifest_path(tmp_path) == tmp_path / "data" / "manifests" / "statsbomb_manifest.csv"


def test_real_selection_file_matches_the_step_2_findings():
    """Contrato com docs/data_notes.md: commit fixado e as 64 partidas da Copa (Passo 13), com as 3 sentinelas entre elas."""
    selection = load_selection(selection_path(PROJECT_ROOT))
    assert selection.source_repo == "hudl/open-data"
    assert selection.source_commit == VALID_COMMIT
    assert (selection.competition_id, selection.season_id) == (43, 106)
    assert len(selection.load_match_ids) == 64 == len(set(selection.load_match_ids))
    assert {3869685, 3857276, 3857271} <= set(selection.load_match_ids)
