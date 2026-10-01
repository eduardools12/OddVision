"""Testes de src/oddvision/checks.py (sem banco): leitura dos arquivos de check, relatório e o C11.

Os checks SQL contra um PostgreSQL de verdade ficam em tests/integration/test_checks.py.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from oddvision.checks import (
    CheckResult,
    format_report,
    has_errors,
    load_sql_checks,
    player_name_conflicts_check,
)
from oddvision.config import PROJECT_ROOT, ConfigError, Selection, checks_dir
from oddvision.ingest import run_ingest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_CHECKS = checks_dir(PROJECT_ROOT)


def write_check(directory, name, *, level="error", title="Um título", body="SELECT 1 WHERE false;"):
    lines = []
    if level is not None:
        lines.append(f"-- level: {level}")
    if title is not None:
        lines.append(f"-- title: {title}")
    (directory / name).write_text("\n".join(lines + [body]) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- leitura dos arquivos

def test_a_check_file_declares_its_level_and_title_in_the_header(tmp_path):
    write_check(tmp_path, "C02_b.sql", level="warning", title="Segundo", body="SELECT 2 WHERE false;")
    write_check(tmp_path, "C01_a.sql", level="error", title="Primeiro")

    checks = load_sql_checks(tmp_path)

    assert [(c.check_id, c.level, c.title) for c in checks] == [("C01", "error", "Primeiro"), ("C02", "warning", "Segundo")]
    assert "SELECT 2 WHERE false;" in checks[1].sql


def test_files_that_are_not_checks_are_ignored(tmp_path):
    write_check(tmp_path, "C01_a.sql")
    (tmp_path / "README.md").write_text("não é um check", encoding="utf-8")
    assert [c.check_id for c in load_sql_checks(tmp_path)] == ["C01"]


@pytest.mark.parametrize("name", ["check_a.sql", "C1_a.sql", "C001_a.sql", "c01_a.sql", "C01.sql"])
def test_the_file_name_must_start_with_the_check_id(tmp_path, name):
    write_check(tmp_path, name)
    with pytest.raises(ConfigError, match="nome"):
        load_sql_checks(tmp_path)


def test_the_level_must_be_error_or_warning(tmp_path):
    write_check(tmp_path, "C01_a.sql", level="critico")
    with pytest.raises(ConfigError, match="level"):
        load_sql_checks(tmp_path)


def test_the_header_is_required(tmp_path):
    write_check(tmp_path, "C01_a.sql", level=None)
    with pytest.raises(ConfigError, match="level"):
        load_sql_checks(tmp_path)
    write_check(tmp_path, "C01_a.sql", title=None)
    with pytest.raises(ConfigError, match="title"):
        load_sql_checks(tmp_path)


def test_a_repeated_check_id_is_rejected(tmp_path):
    write_check(tmp_path, "C01_a.sql")
    write_check(tmp_path, "C01_b.sql")
    with pytest.raises(ConfigError, match="C01"):
        load_sql_checks(tmp_path)


def test_a_missing_or_empty_folder_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="checks"):
        load_sql_checks(tmp_path / "nao_existe")
    with pytest.raises(ConfigError, match="C"):
        load_sql_checks(tmp_path)


def test_the_real_checks_are_c01_to_c10_with_the_levels_of_the_spec():
    """Spec, seção 11. O C11 é feito em Python porque precisa dos arquivos brutos."""
    checks = load_sql_checks(REAL_CHECKS)
    assert {c.check_id: c.level for c in checks} == {
        "C01": "error", "C02": "error", "C03": "error", "C04": "error", "C05": "error",
        "C06": "error", "C07": "error", "C08": "error", "C09": "warning", "C10": "warning",
    }
    assert all(c.title.strip() and "SELECT" in c.sql.upper() for c in checks)


def test_the_real_checks_only_read_they_never_write():
    import re

    for check in load_sql_checks(REAL_CHECKS):
        code = re.sub(r"--[^\n]*", " ", check.sql)
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT)\b", code, re.IGNORECASE), check.check_id


# --------------------------------------------------------------------------- relatório

def result(check_id="C01", level="error", violations=0, sample=(), columns=("match_id",), title="Título"):
    return CheckResult(check_id, level, title, violations, columns, tuple(sample))


def test_an_error_with_violations_makes_the_run_fail():
    assert has_errors([result(level="error", violations=1)]) is True


def test_a_warning_never_makes_the_run_fail():
    assert has_errors([result(level="warning", violations=7)]) is False


def test_checks_without_violations_do_not_fail():
    assert has_errors([result(level="error", violations=0), result("C09", "warning", 0)]) is False


def test_the_report_shows_status_title_sample_and_summary():
    report = format_report([
        result("C01", "error", 0, title="Tudo certo"),
        result("C02", "error", 3, sample=[(3869685,), (3857276,)], title="Placar"),
        result("C09", "warning", 1, sample=[(5503,)], columns=("player_id",), title="Cartões"),
    ])
    lines = report.splitlines()
    assert any(line.startswith("C01") and "OK" in line and "Tudo certo" in line for line in lines)
    assert any(line.startswith("C02") and "FALHA" in line and "3" in line and "Placar" in line for line in lines)
    assert any(line.startswith("C09") and "AVISO" in line and "Cartões" in line for line in lines)
    assert "match_id=3869685" in report and "player_id=5503" in report  # amostra com o nome das colunas
    assert "3 checks" in lines[-1] and "1 erro" in lines[-1] and "1 aviso" in lines[-1]


def test_the_report_says_how_many_rows_the_sample_hides():
    sample = [(i,) for i in range(5)]
    assert "mais 7" in format_report([result("C02", "error", 12, sample=sample)])


# --------------------------------------------------------------------------- C11 (Python, arquivos brutos)

COMMIT = "ab" * 20
SELECTION = Selection("owner/repo", COMMIT, 43, 106, (1,))


def stage_lineups(tmp_path, names_by_match, nicknames_by_match=None):
    """Ingestão sem rede de arquivos de escalação em que o Messi (5503) tem o nome (e o apelido) dados em cada partida."""
    sample = json.loads((FIXTURES / "lineups_sample.json").read_text(encoding="utf-8"))
    files = {"competitions.json": b"[]", "matches/43/106.json": json.dumps([{"match_id": m} for m in names_by_match]).encode()}
    for match_id, name in names_by_match.items():
        teams = json.loads(json.dumps(sample))
        messi = next(p for t in teams for p in t["lineup"] if p["player_id"] == 5503)
        messi["player_name"] = name
        if nicknames_by_match:
            messi["player_nickname"] = nicknames_by_match[match_id]
        files[f"lineups/{match_id}.json"] = json.dumps(teams, ensure_ascii=False).encode()
        files[f"events/{match_id}.json"] = b"[]"
    served = {SELECTION.base_url + rel: data for rel, data in files.items()}
    raw, manifest = tmp_path / "raw", tmp_path / "manifest.csv"
    run_ingest(SELECTION, raw, manifest, download=served.__getitem__, now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    return raw, manifest


def test_c11_warns_about_a_player_with_different_names_in_different_files(tmp_path):
    raw, manifest = stage_lineups(tmp_path, {1: "Messi A", 2: "Messi B", 3: "Messi B"})

    result_c11 = player_name_conflicts_check(raw, manifest)

    assert (result_c11.check_id, result_c11.level) == ("C11", "warning")
    assert result_c11.violations == 1
    assert result_c11.sample == ((5503, "'Messi B' em 2, 'Messi A' em 1", "Messi B"),)
    assert result_c11.columns == ("player_id", "names", "stored")


def test_c11_is_clean_when_every_file_agrees(tmp_path):
    raw, manifest = stage_lineups(tmp_path, {1: "Messi", 2: "Messi"})
    assert player_name_conflicts_check(raw, manifest).violations == 0


def test_c11_is_only_about_names_a_different_nickname_is_not_reported_here(tmp_path):
    # apelido e país divergentes já saem como aviso na carga (D24); o C11 é só sobre o NOME (spec, seção 11)
    raw, manifest = stage_lineups(tmp_path, {1: "Messi", 2: "Messi"}, {1: "Leo", 2: "La Pulga"})
    assert player_name_conflicts_check(raw, manifest).violations == 0
