"""Testes dos checks de qualidade (Passo 9) contra um PostgreSQL de verdade.

Estratégia (a do plano: "um check que nunca falha é um check errado"): monta um MUNDO COERENTE mínimo em que
todos os checks passam e, para cada check, injeta o defeito que ele deve pegar e confere que ELE falha.
Tudo acontece em uma transação desfeita no fim. Quando o defeito é algo que uma restrição do banco já impede
(coordenadas, xG), a restrição é removida DENTRO da transação: o check é a segunda barreira.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from oddvision.checks import has_errors, run_checks
from oddvision.config import PROJECT_ROOT, checks_dir
from oddvision.ingest import run_ingest
from oddvision.load import load_p2
from oddvision.pipeline import main

CHECKS = checks_dir(PROJECT_ROOT)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SQL_CHECKS = ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10"]


def run(conn, sql, **params):
    return conn.execute(text(sql), params)


def results(conn):
    return {r.check_id: r for r in run_checks(conn, CHECKS)}


def failing(conn):
    return sorted(check_id for check_id, r in results(conn).items() if r.violations)


# --------------------------------------------------------------------------- o mundo coerente

def add_event(conn, idx, type_name, team, player, *, period=1, x=60.0, y=40.0):
    event_id = uuid.uuid4()
    run(conn, "INSERT INTO core.events (event_id, match_id, idx, period, ts_in_period, minute, second, type_name, team_id, "
              "player_id, possession, possession_team_id, play_pattern, x, y) VALUES (:e, 100, :i, :p, interval '1 second', 0, 1, "
              ":t, :tm, :pl, 1, :tm, 'Regular Play', :x, :y)", e=event_id, i=idx, p=period, t=type_name, tm=team, pl=player, x=x, y=y)
    return event_id


@pytest.fixture
def world(conn):
    """Partida 100 (time 1 x time 2, placar 1 x 0), 22 titulares, 5 eventos e o registro da carga. Tudo coerente."""
    run(conn, "INSERT INTO core.competitions (competition_id, season_id, competition_name, season_name, competition_gender, "
              "competition_youth, competition_international) VALUES (43, 106, 'FIFA World Cup', '2022', 'male', false, true)")
    for team_id in (1, 2, 3):
        run(conn, "INSERT INTO core.teams (team_id, team_name) VALUES (:i, :n)", i=team_id, n=f"Time {team_id}")
    players = [(team, base + n) for team, base in ((1, 100), (2, 200)) for n in range(1, 12)]
    for _, player_id in players:
        run(conn, "INSERT INTO core.players (player_id, player_name) VALUES (:i, :n)", i=player_id, n=f"Jogador {player_id}")
    run(conn, "INSERT INTO core.matches (match_id, competition_id, season_id, match_date, home_team_id, away_team_id, home_score, away_score) "
              "VALUES (100, 43, 106, '2022-12-18', 1, 2, 1, 0)")
    for team, player_id in players:
        run(conn, "INSERT INTO core.lineups (match_id, team_id, player_id, is_starter, played) VALUES (100, :t, :p, true, true)", t=team, p=player_id)

    ids = {
        "goal": add_event(conn, 1, "Shot", 1, 101),
        "pass": add_event(conn, 2, "Pass", 1, 102),
        "carry": add_event(conn, 3, "Carry", 1, 102),
        "foul": add_event(conn, 4, "Foul Committed", 2, 201),
        "penalty": add_event(conn, 5, "Shot", 2, 202, period=5),  # disputa de pênaltis: não conta no placar
    }
    run(conn, "INSERT INTO core.shots (event_id, statsbomb_xg, end_x, end_y, outcome, shot_type) VALUES (:e, 0.1, 120, 40, 'Goal', 'Open Play')", e=ids["goal"])
    run(conn, "INSERT INTO core.shots (event_id, statsbomb_xg, end_x, end_y, outcome, shot_type) VALUES (:e, 0.7835, 120, 40, 'Goal', 'Penalty')", e=ids["penalty"])
    run(conn, "INSERT INTO core.passes (event_id, recipient_id, end_x, end_y, outcome, is_complete) VALUES (:e, 103, 70, 40, NULL, true)", e=ids["pass"])
    run(conn, "INSERT INTO core.carries (event_id, end_x, end_y) VALUES (:e, 65, 40)", e=ids["carry"])
    run(conn, "INSERT INTO core.cards (event_id, card_type) VALUES (:e, 'Yellow Card')", e=ids["foul"])
    run(conn, "UPDATE core.lineups SET extra = CAST(:x AS jsonb) WHERE match_id = 100 AND player_id = 201",
        x=json.dumps({"cards": [{"card_type": "Yellow Card", "time": "10:00", "period": 1, "reason": "Foul Committed"}]}))
    run(conn, "INSERT INTO core.ingestion_log (file_path, source_url, source_commit, sha256, size_bytes, record_count, downloaded_at, loaded_at) "
              "VALUES ('events/100.json', 'http://x', :c, :h, 1, 5, now(), now())", c="ab" * 20, h="0" * 64)
    return ids


def sample(conn, check_id):
    return results(conn)[check_id].sample


# --------------------------------------------------------------------------- linha de base

def test_there_are_ten_sql_checks_and_the_database_is_clean_when_empty(conn):
    found = results(conn)
    assert sorted(found) == SQL_CHECKS
    assert all(r.violations == 0 for r in found.values())


def test_a_coherent_world_passes_every_check(conn, world):
    assert failing(conn) == []
    assert has_errors(list(results(conn).values())) is False


# --------------------------------------------------------------------------- C01: eventos x manifest

def test_c01_catches_a_missing_event(conn, world):
    run(conn, "DELETE FROM core.events WHERE event_id = :e", e=world["carry"])
    assert "C01" in failing(conn)
    assert sample(conn, "C01")[0][:3] == (100, 5, 4)  # partida, record_count do manifest, eventos no core


def test_c01_catches_events_with_no_load_record(conn, world):
    run(conn, "DELETE FROM core.ingestion_log WHERE file_path = 'events/100.json'")
    assert "C01" in failing(conn)


def test_c01_catches_events_whose_file_is_not_marked_as_loaded(conn, world):
    run(conn, "UPDATE core.ingestion_log SET loaded_at = NULL WHERE file_path = 'events/100.json'")
    assert "C01" in failing(conn)


def test_c01_is_quiet_about_files_that_were_never_loaded(conn, world):
    run(conn, "INSERT INTO core.ingestion_log (file_path, source_url, source_commit, sha256, size_bytes, record_count, downloaded_at) "
              "VALUES ('events/999.json', 'http://x', :c, :h, 1, 4000, now())", c="ab" * 20, h="0" * 64)
    assert "C01" not in failing(conn)


# --------------------------------------------------------------------------- C02: placar

def test_c02_catches_a_score_that_the_events_do_not_support(conn, world):
    run(conn, "UPDATE core.matches SET away_score = 1 WHERE match_id = 100")
    assert "C02" in failing(conn)
    assert sample(conn, "C02")[0] == (100, 1, 1, 1, 0)  # partida, placar oficial, gols reconstruídos


def test_c02_counts_own_goals_for_the_beneficiary_team(conn, world):
    add_event(conn, 6, "Own Goal For", 2, None)
    run(conn, "UPDATE core.matches SET away_score = 1 WHERE match_id = 100")
    run(conn, "UPDATE core.ingestion_log SET record_count = 6 WHERE file_path = 'events/100.json'")
    assert failing(conn) == []


def test_c02_does_not_count_the_shootout(conn, world):
    # o pênalti do período 5 é gol, mas o placar oficial (1 x 0) não o inclui
    assert run(conn, "SELECT count(*) FROM core.shots WHERE outcome = 'Goal'").scalar_one() == 2
    assert "C02" not in failing(conn)


def test_c02_ignores_matches_without_events(conn, world):
    run(conn, "INSERT INTO core.matches (match_id, competition_id, season_id, match_date, home_team_id, away_team_id, home_score, away_score) "
              "VALUES (101, 43, 106, '2022-12-19', 1, 3, 4, 4)")
    assert "C02" not in failing(conn)


# --------------------------------------------------------------------------- C03: coordenadas

def test_c03_catches_event_coordinates_outside_the_pitch(conn, world):
    run(conn, "ALTER TABLE core.events DROP CONSTRAINT chk_events_x")  # só dentro desta transação
    run(conn, "UPDATE core.events SET x = 130 WHERE event_id = :e", e=world["pass"])
    assert "C03" in failing(conn)
    assert sample(conn, "C03")[0][0] == "events"


def test_c03_catches_pass_and_carry_end_points_outside_the_pitch(conn, world):
    run(conn, "ALTER TABLE core.passes DROP CONSTRAINT chk_passes_end_y")
    run(conn, "ALTER TABLE core.carries DROP CONSTRAINT chk_carries_end_x")
    run(conn, "UPDATE core.passes SET end_y = -5")
    run(conn, "UPDATE core.carries SET end_x = 121")
    assert {row[0] for row in sample(conn, "C03")} == {"passes", "carries"}


# --------------------------------------------------------------------------- C04: domínios

@pytest.mark.parametrize("sql, field", [
    ("UPDATE core.shots SET outcome = 'Banana' WHERE shot_type = 'Open Play'", "shots.outcome"),
    ("UPDATE core.shots SET shot_type = 'Bicicleta' WHERE shot_type = 'Open Play'", "shots.shot_type"),
    ("UPDATE core.passes SET outcome = 'Misterio', is_complete = false", "passes.outcome"),
    ("UPDATE core.passes SET pass_type = 'Estranho'", "passes.pass_type"),
    ("UPDATE core.cards SET card_type = 'Purple Card'", "cards.card_type"),
])
def test_c04_catches_a_value_outside_the_known_domain(conn, world, sql, field):
    run(conn, sql)
    assert "C04" in failing(conn)
    assert field in {row[0] for row in sample(conn, "C04")}


def test_c04_accepts_the_null_pass_outcome_and_pass_type(conn, world):
    assert run(conn, "SELECT outcome, pass_type FROM core.passes").one() == (None, None)  # passe completo e regular
    assert "C04" not in failing(conn)


# --------------------------------------------------------------------------- C05: tabelas especializadas

def test_c05_catches_an_event_without_its_specialized_row(conn, world):
    run(conn, "DELETE FROM core.shots WHERE event_id = :e", e=world["goal"])
    assert "C05" in failing(conn)
    assert sample(conn, "C05")[0][:2] == ("contagem", 100)


def test_c05_catches_a_specialized_row_that_points_to_an_event_of_the_wrong_type(conn, world):
    wrong = add_event(conn, 6, "Pass", 1, 102)
    run(conn, "INSERT INTO core.shots (event_id, statsbomb_xg, end_x, end_y, outcome, shot_type) VALUES (:e, 0.1, 120, 40, 'Goal', 'Open Play')", e=wrong)
    run(conn, "DELETE FROM core.passes WHERE event_id = :e", e=world["pass"])
    run(conn, "UPDATE core.ingestion_log SET record_count = 6 WHERE file_path = 'events/100.json'")
    assert "C05" in failing(conn)
    assert "tipo errado" in {row[0] for row in sample(conn, "C05")}


# --------------------------------------------------------------------------- C06: xG

def test_c06_catches_an_xg_outside_0_1(conn, world):
    run(conn, "SET CONSTRAINTS ALL IMMEDIATE")  # o PostgreSQL não faz ALTER TABLE com a FK adiada (key_pass_id) pendente
    run(conn, "ALTER TABLE core.shots DROP CONSTRAINT chk_shots_xg")
    run(conn, "UPDATE core.shots SET statsbomb_xg = 1.5 WHERE shot_type = 'Open Play'")
    assert "C06" in failing(conn)


# --------------------------------------------------------------------------- C07: titulares

def test_c07_catches_a_team_without_11_starters(conn, world):
    run(conn, "UPDATE core.lineups SET is_starter = false WHERE match_id = 100 AND player_id = 101")
    assert failing(conn) == ["C07"]
    assert sample(conn, "C07")[0] == (100, 1, 10)  # partida, time, titulares encontrados


def test_c07_catches_a_team_with_more_than_11_starters(conn, world):
    run(conn, "INSERT INTO core.players (player_id, player_name) VALUES (999, 'Extra')")
    run(conn, "INSERT INTO core.lineups (match_id, team_id, player_id, is_starter, played) VALUES (100, 2, 999, true, true)")
    assert failing(conn) == ["C07"]


# --------------------------------------------------------------------------- C08: times dos eventos

def test_c08_catches_an_event_from_a_team_that_is_not_in_the_match(conn, world):
    add_event(conn, 6, "Pass", 3, 102)  # o time 3 existe, mas a partida é do 1 contra o 2
    run(conn, "UPDATE core.ingestion_log SET record_count = 6 WHERE file_path = 'events/100.json'")
    assert "C08" in failing(conn)
    assert sample(conn, "C08")[0][0] == 100


# --------------------------------------------------------------------------- C09 e C10: avisos

def test_c09_warns_when_the_cards_in_events_and_lineups_disagree(conn, world):
    run(conn, "UPDATE core.lineups SET extra = '{\"cards\": []}' WHERE match_id = 100 AND player_id = 201")
    found = results(conn)
    assert failing(conn) == ["C09"]
    assert found["C09"].level == "warning" and has_errors(list(found.values())) is False  # aviso não derruba a execução
    assert found["C09"].sample[0][:3] == (100, 201, "Yellow Card")


def test_c09_also_catches_a_card_that_only_the_lineups_have(conn, world):
    run(conn, "DELETE FROM core.cards")
    assert failing(conn) == ["C09"]


def test_c09_ignores_matches_whose_events_were_never_loaded(conn, world):
    # escalação com cartão em uma partida SEM eventos carregados: não há com o que comparar
    run(conn, "INSERT INTO core.matches (match_id, competition_id, season_id, match_date, home_team_id, away_team_id, home_score, away_score) "
              "VALUES (101, 43, 106, '2022-12-19', 1, 3, 0, 0)")
    run(conn, "INSERT INTO core.lineups (match_id, team_id, player_id, is_starter, played, extra) VALUES (101, 1, 101, true, true, CAST(:x AS jsonb))",
        x=json.dumps({"cards": [{"card_type": "Red Card"}]}))
    assert "C09" not in failing(conn)


def test_c10_warns_when_a_penalty_xg_is_not_the_usual_value(conn, world):
    run(conn, "UPDATE core.shots SET statsbomb_xg = 0.5 WHERE shot_type = 'Penalty'")
    found = results(conn)
    assert failing(conn) == ["C10"]
    assert found["C10"].level == "warning" and has_errors(list(found.values())) is False


# --------------------------------------------------------------------------- erros derrubam a execução

def test_an_error_level_failure_makes_the_run_fail(conn, world):
    run(conn, "UPDATE core.matches SET away_score = 1 WHERE match_id = 100")
    assert has_errors(list(results(conn).values())) is True


# --------------------------------------------------------------------------- CLI

DB_TOML = ("[connection]\nhost = {host}\nport = {port}\nuser = {user}\npassword = {password}\n\n"
           "[databases]\nmain = {db}\ntest = {db}\n")


@pytest.fixture
def cli_root(tmp_path, db_config):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "database.toml").write_text(DB_TOML.format(
        host=json.dumps(db_config.host), port=db_config.port, user=json.dumps(db_config.user),
        password=json.dumps(db_config.password), db=json.dumps(db_config.test_db)), encoding="utf-8")
    import shutil
    shutil.copytree(CHECKS, checks_dir(tmp_path))
    return tmp_path


def test_check_command_on_an_empty_database_is_all_ok(fresh_schemas, cli_root, capsys):
    assert main(["check"], root=cli_root) == 0
    out = capsys.readouterr().out
    assert all(f"C{n:02d}" in out for n in range(1, 11))
    assert "FALHA" not in out and "0 erros" in out


def test_check_command_exits_with_1_and_names_the_failing_check(fresh_schemas, cli_root, capsys):
    with fresh_schemas.begin() as c:  # defeito COMMITADO (o fresh_schemas desfaz no fim): um evento sem registro de carga
        c.execute(text("INSERT INTO core.competitions (competition_id, season_id, competition_name, season_name, competition_gender, "
                       "competition_youth, competition_international) VALUES (43, 106, 'x', '2022', 'male', false, true)"))
        c.execute(text("INSERT INTO core.teams (team_id, team_name) VALUES (1, 'A'), (2, 'B')"))
        c.execute(text("INSERT INTO core.matches (match_id, competition_id, season_id, match_date, home_team_id, away_team_id, home_score, away_score) "
                       "VALUES (100, 43, 106, '2022-12-18', 1, 2, 0, 0)"))
        c.execute(text("INSERT INTO core.events (event_id, match_id, idx, period, ts_in_period, minute, second, type_name, team_id, "
                       "possession, possession_team_id, play_pattern) VALUES (:e, 100, 1, 1, interval '1 second', 0, 1, 'Pressure', 1, 1, 1, 'Regular Play')"),
                  {"e": uuid.uuid4()})  # 'Pressure' não tem tabela própria: só o C01 (sem registro de carga) deve falhar
    assert main(["check"], root=cli_root) == 1
    out = capsys.readouterr().out
    assert any(line.startswith("C01") and "FALHA" in line for line in out.splitlines())
    assert "1 erro" in out.splitlines()[-1]


# --------------------------------------------------------------------------- all: ingest + init-db + load + check

COMMIT = "ab" * 20


def test_all_command_runs_the_whole_pipeline_and_the_checks_reject_the_partial_sample(fresh_schemas, db_config, tmp_path, capsys):
    """A amostra de testes é PARCIAL (22 de 4.407 eventos, 9 jogadores): os checks que comparam com o total
    oficial têm de falhar, e é isso que prova que estão olhando de verdade: C02 (placar) e C07 (11 titulares)."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "selection.toml").write_text(
        f'[source]\nrepo = "owner/repo"\ncommit = "{COMMIT}"\n\n[competition]\ncompetition_id = 43\nseason_id = 106\n\n'
        "[load]\nmatch_ids = [3869685]\n", encoding="utf-8")
    (tmp_path / "config" / "database.toml").write_text(DB_TOML.format(
        host=json.dumps(db_config.host), port=db_config.port, user=json.dumps(db_config.user),
        password=json.dumps(db_config.password), db=json.dumps(db_config.test_db)), encoding="utf-8")
    import shutil
    shutil.copytree(CHECKS, checks_dir(tmp_path))
    shutil.copytree(PROJECT_ROOT / "sql" / "ddl", tmp_path / "sql" / "ddl")

    load = lambda name: json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    matches = load("matches_sample.json")
    base = f"https://raw.githubusercontent.com/owner/repo/{COMMIT}/data/"
    served = {base + "competitions.json": json.dumps(load("competitions_sample.json")).encode(),
              base + "matches/43/106.json": json.dumps(matches).encode()}
    for m in matches:
        served[base + f"events/{m['match_id']}.json"] = json.dumps(load("events_sample.json")).encode()
        served[base + f"lineups/{m['match_id']}.json"] = json.dumps(load("lineups_sample.json"), ensure_ascii=False).encode()

    assert main(["all"], root=tmp_path, download=served.__getitem__) == 1  # os checks de erro falham
    out = capsys.readouterr().out

    assert "baixados" in out and "DDL aplicado" in out and "competitions: 1" in out  # as 3 etapas anteriores rodaram
    failed = {line.split()[0] for line in out.splitlines() if line.startswith("C") and "FALHA" in line}
    assert failed == {"C02", "C07"}
    assert any(line.startswith("C11") for line in out.splitlines())  # o C11 (Python) também rodou
    assert db_config.password not in out
