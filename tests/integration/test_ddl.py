"""Testes do DDL (Passo 4): o banco criado corresponde ao docs/data_dictionary.md?

Validação independente do código: as colunas esperadas são LIDAS DO DOCUMENTO, não copiadas
para dentro dos testes. As restrições (CHECK, FK, UNIQUE, CASCADE) são testadas pelo
COMPORTAMENTO: tentamos gravar dados ruins e conferimos que o banco recusa.
"""

import datetime
import itertools
import json
import re
import shutil
import uuid

import psycopg.errors as pg_errors
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from oddvision.config import PROJECT_ROOT, ddl_dir
from oddvision.db import apply_ddl
from oddvision.pipeline import main

DICTIONARY = PROJECT_ROOT / "docs" / "data_dictionary.md"

EXPECTED_TABLES = [
    "competitions", "teams", "players", "matches", "lineups", "events",
    "shots", "passes", "carries", "cards", "substitutions", "ingestion_log",
]

# Tipo do dicionário -> (data_type, character_maximum_length) em information_schema.columns
PG_TYPES = {
    "INTEGER": ("integer", None),
    "SMALLINT": ("smallint", None),
    "BIGINT": ("bigint", None),
    "TEXT": ("text", None),
    "BOOLEAN": ("boolean", None),
    "DATE": ("date", None),
    "TIME": ("time without time zone", None),
    "TIMESTAMP": ("timestamp without time zone", None),
    "TIMESTAMPTZ": ("timestamp with time zone", None),
    "JSONB": ("jsonb", None),
    "UUID": ("uuid", None),
    "INTERVAL": ("interval", None),
    "DOUBLE PRECISION": ("double precision", None),
    "CHAR(64)": ("character", 64),
}

PRIMARY_KEYS = {
    "competitions": ("competition_id", "season_id"),
    "teams": ("team_id",),
    "players": ("player_id",),
    "matches": ("match_id",),
    "lineups": ("match_id", "player_id"),
    "events": ("event_id",),
    "shots": ("event_id",),
    "passes": ("event_id",),
    "carries": ("event_id",),
    "cards": ("event_id",),
    "substitutions": ("event_id",),
    "ingestion_log": ("file_path",),
}

# (tabela, colunas, tabela referenciada, colunas referenciadas, regra de DELETE: c = CASCADE, a = NO ACTION)
FOREIGN_KEYS = {
    ("matches", ("competition_id", "season_id"), "core.competitions", ("competition_id", "season_id"), "a"),
    ("matches", ("home_team_id",), "core.teams", ("team_id",), "a"),
    ("matches", ("away_team_id",), "core.teams", ("team_id",), "a"),
    ("lineups", ("match_id",), "core.matches", ("match_id",), "c"),
    ("lineups", ("team_id",), "core.teams", ("team_id",), "a"),
    ("lineups", ("player_id",), "core.players", ("player_id",), "a"),
    ("events", ("match_id",), "core.matches", ("match_id",), "c"),
    ("events", ("team_id",), "core.teams", ("team_id",), "a"),
    ("events", ("possession_team_id",), "core.teams", ("team_id",), "a"),
    ("events", ("player_id",), "core.players", ("player_id",), "a"),
    ("shots", ("event_id",), "core.events", ("event_id",), "c"),
    ("shots", ("key_pass_id",), "core.events", ("event_id",), "a"),
    ("passes", ("event_id",), "core.events", ("event_id",), "c"),
    ("passes", ("recipient_id",), "core.players", ("player_id",), "a"),
    ("carries", ("event_id",), "core.events", ("event_id",), "c"),
    ("cards", ("event_id",), "core.events", ("event_id",), "c"),
    ("substitutions", ("event_id",), "core.events", ("event_id",), "c"),
    ("substitutions", ("player_on_id",), "core.players", ("player_id",), "a"),
}


def parse_data_dictionary() -> dict[str, list[tuple[str, str, bool]]]:
    """Lê as tabelas de colunas de docs/data_dictionary.md: {tabela: [(coluna, tipo, not_null)]}."""
    tables: dict[str, list[tuple[str, str, bool]]] = {}
    current = None
    for line in DICTIONARY.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## \d+\. `core\.(\w+)`", line)
        if heading:
            current = heading.group(1)
            tables[current] = []
        elif line.startswith("## "):
            current = None
        elif current:
            row = re.match(r"^\| `(\w+)` \| `([^`]+)` \| (NÃO|SIM)", line)
            if row:
                tables[current].append((row.group(1), row.group(2), row.group(3) == "NÃO"))
    return tables


# --------------------------------------------------------------------------- o dicionário (sem banco)

def test_dictionary_documents_exactly_the_12_core_tables():
    assert list(parse_data_dictionary()) == EXPECTED_TABLES


def test_every_documented_type_is_known():
    documented = {t for cols in parse_data_dictionary().values() for _, t, _ in cols}
    assert documented <= set(PG_TYPES)


# --------------------------------------------------------------------------- estrutura (catálogo)

def test_schemas_exist(schemas):
    with schemas.connect() as c:
        names = set(c.execute(text("SELECT schema_name FROM information_schema.schemata")).scalars())
    assert {"core", "analytics"} <= names


def test_core_has_exactly_the_12_tables(schemas):
    with schemas.connect() as c:
        tables = set(c.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'core' AND table_type = 'BASE TABLE'")).scalars())
    assert tables == set(EXPECTED_TABLES)


def test_analytics_has_no_base_tables(schemas):
    """analytics só terá views (D05, D15)."""
    with schemas.connect() as c:
        tables = list(c.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'analytics' AND table_type = 'BASE TABLE'")).scalars())
    assert tables == []


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_columns_match_the_data_dictionary(schemas, table):
    expected = [(name, PG_TYPES[doc_type], not_null) for name, doc_type, not_null in parse_data_dictionary()[table]]
    with schemas.connect() as c:
        rows = c.execute(text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns WHERE table_schema = 'core' AND table_name = :t "
            "ORDER BY ordinal_position"), {"t": table}).all()
    actual = [(r.column_name, (r.data_type, r.character_maximum_length), r.is_nullable == "NO") for r in rows]
    assert actual == expected


def test_primary_keys(schemas):
    with schemas.connect() as c:
        rows = c.execute(text("""
            SELECT cl.relname AS tbl,
                   (SELECT array_agg(a.attname ORDER BY k.ord)
                      FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
                      JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS cols
            FROM pg_constraint con
            JOIN pg_class cl ON cl.oid = con.conrelid
            WHERE con.contype = 'p' AND cl.relnamespace = 'core'::regnamespace
        """)).all()
    assert {r.tbl: tuple(r.cols) for r in rows} == PRIMARY_KEYS


def test_foreign_keys(schemas):
    with schemas.connect() as c:
        rows = c.execute(text("""
            SELECT cl.relname AS tbl, ref.relnamespace::regnamespace::text || '.' || ref.relname AS ref_tbl,
                   con.confdeltype AS delete_rule,
                   (SELECT array_agg(a.attname ORDER BY k.ord)
                      FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
                      JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS cols,
                   (SELECT array_agg(a.attname ORDER BY k.ord)
                      FROM unnest(con.confkey) WITH ORDINALITY k(attnum, ord)
                      JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum) AS ref_cols
            FROM pg_constraint con
            JOIN pg_class cl ON cl.oid = con.conrelid
            JOIN pg_class ref ON ref.oid = con.confrelid
            WHERE con.contype = 'f' AND cl.relnamespace = 'core'::regnamespace
        """)).all()
    actual = {(r.tbl, tuple(r.cols), r.ref_tbl, tuple(r.ref_cols), r.delete_rule) for r in rows}
    assert actual == FOREIGN_KEYS


def test_only_the_key_pass_foreign_key_is_deferred(schemas):
    """shots.key_pass_id é conferida no COMMIT: ao apagar uma partida, a finalização e o passe
    saem no mesmo comando, mas o banco checa a chave entre uma exclusão e a outra."""
    with schemas.connect() as c:
        rows = c.execute(text(
            "SELECT conname, condeferrable, condeferred FROM pg_constraint "
            "WHERE contype = 'f' AND connamespace = 'core'::regnamespace AND condeferrable")).all()
    assert [(r.conname, r.condeferrable, r.condeferred) for r in rows] == [("shots_key_pass_id_fkey", True, True)]


def test_a_shot_pointing_to_a_missing_pass_is_rejected_at_commit(conn, seed):
    insert_shot(conn, key_pass_id=uuid.uuid4())  # nenhum evento com esse id: o INSERT ainda passa...
    with pytest.raises(IntegrityError) as info:
        run(conn, "SET CONSTRAINTS ALL IMMEDIATE")  # ...mas a conferência (feita no COMMIT) recusa
    assert isinstance(info.value.orig, pg_errors.ForeignKeyViolation)


def test_events_are_unique_per_match_and_idx(schemas):
    with schemas.connect() as c:
        rows = c.execute(text("""
            SELECT (SELECT array_agg(a.attname ORDER BY k.ord)
                      FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
                      JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS cols
            FROM pg_constraint con
            WHERE con.contype = 'u' AND con.conrelid = 'core.events'::regclass
        """)).all()
    assert [tuple(r.cols) for r in rows] == [("match_id", "idx")]


# --------------------------------------------------------------------------- comportamento

_IDX = itertools.count(1)


def run(conn, sql, **params):
    return conn.execute(text(sql), params)


@pytest.fixture
def seed(conn):
    """Uma competição, 2 times, 2 jogadores e a partida 100 (time 1 x time 2)."""
    run(conn, "INSERT INTO core.competitions (competition_id, season_id, competition_name, season_name, "
              "competition_gender, competition_youth, competition_international) "
              "VALUES (43, 106, 'FIFA World Cup', '2022', 'male', false, true)")
    for team_id, name in ((1, "Argentina"), (2, "France")):
        run(conn, "INSERT INTO core.teams (team_id, team_name) VALUES (:i, :n)", i=team_id, n=name)
    for player_id in (10, 11):
        run(conn, "INSERT INTO core.players (player_id, player_name) VALUES (:i, :n)", i=player_id, n=f"Jogador {player_id}")
    insert_match(conn, 100)


def insert_match(conn, match_id, **overrides):
    row = {"match_id": match_id, "home_team_id": 1, "away_team_id": 2, "home_score": 3, "away_score": 3, **overrides}
    run(conn, "INSERT INTO core.matches (match_id, competition_id, season_id, match_date, home_team_id, "
              "away_team_id, home_score, away_score) "
              "VALUES (:match_id, 43, 106, '2022-12-18', :home_team_id, :away_team_id, :home_score, :away_score)", **row)


EVENT_DEFAULTS = dict(
    match_id=100, period=1, ts_in_period=datetime.timedelta(seconds=1), minute=0, second=1, type_name="Pass",
    team_id=1, player_id=10, possession=1, possession_team_id=1, play_pattern="Regular Play",
    x=60.0, y=40.0, duration=1.0,
)


def insert_event(conn, **overrides):
    row = {**EVENT_DEFAULTS, "event_id": uuid.uuid4(), "idx": next(_IDX), **overrides}
    run(conn, "INSERT INTO core.events (event_id, match_id, idx, period, ts_in_period, minute, second, type_name, "
              "team_id, player_id, possession, possession_team_id, play_pattern, x, y, duration) "
              "VALUES (:event_id, :match_id, :idx, :period, :ts_in_period, :minute, :second, :type_name, "
              ":team_id, :player_id, :possession, :possession_team_id, :play_pattern, :x, :y, :duration)", **row)
    return row["event_id"]


def insert_shot(conn, event_id=None, **overrides):
    event_id = event_id or insert_event(conn, type_name="Shot")
    row = {"event_id": event_id, "statsbomb_xg": 0.1, "end_x": 120.0, "end_y": 40.0, "outcome": "Goal",
           "shot_type": "Open Play", "key_pass_id": None, **overrides}
    run(conn, "INSERT INTO core.shots (event_id, statsbomb_xg, end_x, end_y, outcome, shot_type, key_pass_id) "
              "VALUES (:event_id, :statsbomb_xg, :end_x, :end_y, :outcome, :shot_type, :key_pass_id)", **row)
    return event_id


def insert_pass(conn, event_id=None, **overrides):
    event_id = event_id or insert_event(conn, type_name="Pass")
    row = {"event_id": event_id, "recipient_id": 11, "end_x": 70.0, "end_y": 40.0, "outcome": None,
           "is_complete": True, **overrides}
    run(conn, "INSERT INTO core.passes (event_id, recipient_id, end_x, end_y, outcome, is_complete) "
              "VALUES (:event_id, :recipient_id, :end_x, :end_y, :outcome, :is_complete)", **row)
    return event_id


def insert_carry(conn, **overrides):
    row = {"event_id": insert_event(conn, type_name="Carry"), "end_x": 65.0, "end_y": 40.0, **overrides}
    run(conn, "INSERT INTO core.carries (event_id, end_x, end_y) VALUES (:event_id, :end_x, :end_y)", **row)
    return row["event_id"]


def insert_lineup(conn, player_id, is_starter, played):
    run(conn, "INSERT INTO core.lineups (match_id, team_id, player_id, is_starter, played) "
              "VALUES (100, 1, :p, :s, :pl)", p=player_id, s=is_starter, pl=played)


def assert_rejected(conn, error, action):
    """`action` deve ser recusada pelo banco com `error`. O SAVEPOINT mantém a transação do teste viva."""
    with pytest.raises(IntegrityError) as info:
        with conn.begin_nested():
            action()
    assert isinstance(info.value.orig, error), type(info.value.orig)


@pytest.mark.parametrize("override", [
    {"period": 0}, {"period": 6}, {"second": 60}, {"second": -1},
    {"x": 120.1}, {"x": -0.1}, {"y": 80.1}, {"y": -0.1},
    {"x": None}, {"y": None},  # x e y são nulos juntos ou não são
], ids=str)
def test_events_reject_invalid_values(conn, seed, override):
    assert_rejected(conn, pg_errors.CheckViolation, lambda: insert_event(conn, **override))


@pytest.mark.parametrize("override", [
    {"x": 0.0, "y": 0.0}, {"period": 5, "x": 120.0, "y": 80.0, "second": 59}, {"x": None, "y": None},
], ids=str)
def test_events_accept_boundary_values(conn, seed, override):
    insert_event(conn, **override)


def test_events_defaults(conn, seed):
    event_id = insert_event(conn)
    row = run(conn, "SELECT extra, under_pressure FROM core.events WHERE event_id = :e", e=event_id).one()
    assert row.extra == {}
    assert row.under_pressure is False


def test_events_are_unique_per_match_and_idx_behavior(conn, seed):
    insert_event(conn, idx=500)
    assert_rejected(conn, pg_errors.UniqueViolation, lambda: insert_event(conn, idx=500))


def test_events_require_existing_teams_and_players(conn, seed):
    assert_rejected(conn, pg_errors.ForeignKeyViolation, lambda: insert_event(conn, team_id=999))
    assert_rejected(conn, pg_errors.ForeignKeyViolation, lambda: insert_event(conn, player_id=999))


@pytest.mark.parametrize("xg", [-0.01, 1.01])
def test_shots_reject_xg_outside_0_1(conn, seed, xg):
    assert_rejected(conn, pg_errors.CheckViolation, lambda: insert_shot(conn, statsbomb_xg=xg))


@pytest.mark.parametrize("xg", [0.0, 0.7835, 1.0])
def test_shots_accept_xg_in_0_1(conn, seed, xg):
    insert_shot(conn, statsbomb_xg=xg)


@pytest.mark.parametrize("override", [
    {"outcome": None, "is_complete": False},      # sem outcome = completo
    {"outcome": "Out", "is_complete": True},      # com outcome = incompleto
    {"end_x": 120.1}, {"end_y": -0.1},
], ids=str)
def test_passes_reject_inconsistent_rows(conn, seed, override):
    assert_rejected(conn, pg_errors.CheckViolation, lambda: insert_pass(conn, **override))


@pytest.mark.parametrize("override", [
    {"outcome": None, "is_complete": True}, {"outcome": "Incomplete", "is_complete": False},
], ids=str)
def test_passes_accept_consistent_rows(conn, seed, override):
    insert_pass(conn, **override)


@pytest.mark.parametrize("override", [{"end_x": -1.0}, {"end_x": 120.1}, {"end_y": 80.1}, {"end_y": -0.1}], ids=str)
def test_carries_reject_coordinates_outside_the_pitch(conn, seed, override):
    assert_rejected(conn, pg_errors.CheckViolation, lambda: insert_carry(conn, **override))


def test_lineups_reject_a_starter_who_did_not_play(conn, seed):
    assert_rejected(conn, pg_errors.CheckViolation, lambda: insert_lineup(conn, 10, is_starter=True, played=False))


@pytest.mark.parametrize("is_starter, played", [(True, True), (False, True), (False, False)])
def test_lineups_accept_valid_combinations(conn, seed, is_starter, played):
    insert_lineup(conn, 10, is_starter, played)


def test_matches_reject_the_same_team_twice_and_negative_scores(conn, seed):
    assert_rejected(conn, pg_errors.CheckViolation, lambda: insert_match(conn, 101, away_team_id=1))
    assert_rejected(conn, pg_errors.CheckViolation, lambda: insert_match(conn, 102, home_score=-1))


def test_deleting_a_match_removes_everything_that_belongs_to_it(conn, seed):
    """A carga por partida (D06) é DELETE + INSERT: apagar a partida limpa todas as tabelas filhas,
    inclusive quando uma finalização aponta para o passe que a originou (key_pass_id)."""
    pass_id = insert_pass(conn)
    insert_shot(conn, key_pass_id=pass_id)
    insert_carry(conn)
    card_event = insert_event(conn, type_name="Foul Committed")
    run(conn, "INSERT INTO core.cards (event_id, card_type) VALUES (:e, 'Yellow Card')", e=card_event)
    sub_event = insert_event(conn, type_name="Substitution")
    run(conn, "INSERT INTO core.substitutions (event_id, player_on_id) VALUES (:e, 11)", e=sub_event)
    insert_lineup(conn, 10, True, True)
    insert_match(conn, 101)
    other_event = insert_event(conn, match_id=101)

    run(conn, "DELETE FROM core.matches WHERE match_id = 100")
    # key_pass_id é DEFERRED (conferida no COMMIT). Como o teste termina em ROLLBACK, força a conferência
    # agora: se sobrou uma finalização apontando para um passe apagado, isto falha.
    run(conn, "SET CONSTRAINTS ALL IMMEDIATE")

    for table in ("events", "lineups"):
        assert run(conn, f"SELECT count(*) FROM core.{table} WHERE match_id = 100").scalar_one() == 0
    for table in ("shots", "passes", "carries", "cards", "substitutions"):
        assert run(conn, f"SELECT count(*) FROM core.{table}").scalar_one() == 0
    # as dimensões e as outras partidas não são tocadas
    assert run(conn, "SELECT count(*) FROM core.events WHERE event_id = :e", e=other_event).scalar_one() == 1
    assert run(conn, "SELECT count(*) FROM core.teams").scalar_one() == 2
    assert run(conn, "SELECT count(*) FROM core.players").scalar_one() == 2


def test_dimensions_are_protected_from_deletion_while_referenced(conn, seed):
    insert_event(conn)
    assert_rejected(conn, pg_errors.ForeignKeyViolation, lambda: run(conn, "DELETE FROM core.teams WHERE team_id = 1"))


# --------------------------------------------------------------------------- repetibilidade

def test_applying_the_ddl_again_keeps_the_data(schemas):
    with schemas.begin() as c:
        run(c, "INSERT INTO core.competitions (competition_id, season_id, competition_name, season_name, "
               "competition_gender, competition_youth, competition_international) "
               "VALUES (999999, 1, 'Teste de repetibilidade', 'x', 'male', false, false)")
    try:
        applied = apply_ddl(schemas, ddl_dir(PROJECT_ROOT))
        assert applied == ["001_schemas.sql", "002_core_tables.sql"]
        with schemas.connect() as c:
            assert run(c, "SELECT count(*) FROM core.competitions WHERE competition_id = 999999").scalar_one() == 1
    finally:
        with schemas.begin() as c:
            run(c, "DELETE FROM core.competitions WHERE competition_id = 999999")


# --------------------------------------------------------------------------- comando init-db

def test_init_db_command_is_repeatable(schemas, db_config, tmp_path, capsys):
    """`python -m oddvision.pipeline init-db`, apontado para o banco de TESTES."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "database.toml").write_text(
        f"[connection]\nhost = {json.dumps(db_config.host)}\nport = {db_config.port}\n"
        f"user = {json.dumps(db_config.user)}\npassword = {json.dumps(db_config.password)}\n\n"
        f"[databases]\nmain = {json.dumps(db_config.test_db)}\ntest = {json.dumps(db_config.test_db)}\n",
        encoding="utf-8",
    )
    shutil.copytree(ddl_dir(PROJECT_ROOT), ddl_dir(tmp_path))

    for _ in range(2):
        assert main(["init-db"], root=tmp_path) == 0
        out = capsys.readouterr().out
        assert "12 tabelas" in out
        assert "001_schemas.sql" in out and "002_core_tables.sql" in out
        assert db_config.password not in out
