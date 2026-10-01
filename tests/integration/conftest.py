"""Fixtures dos testes de integração (exigem o PostgreSQL local e o banco `oddvision_test`).

Regras de segurança:
- Sem config/database.toml, os testes de integração são PULADOS (com o motivo).
  Com o arquivo presente e a conexão falhando, os testes FALHAM: um erro de configuração
  nunca pode passar por "tudo verde".
- Só o banco de testes é recriado. O nome vem de `databases.test`, que a configuração já
  obriga a terminar em `_test`, e é conferido de novo no servidor antes de qualquer DROP.
"""

import uuid

import pytest
from sqlalchemy import text

from oddvision.config import PROJECT_ROOT, analytics_dir, database_config_path, ddl_dir
from oddvision.db import apply_analytics, apply_ddl, load_database_config, make_engine


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


@pytest.fixture
def analytics(conn):
    """As views de sql/analytics/ aplicadas DENTRO da transação do teste (desfeita no fim)."""
    apply_analytics(conn, analytics_dir(PROJECT_ROOT))
    return conn


class World:
    """Construtor de dados sintéticos para os testes das métricas: uma partida, dois times, eventos à vontade.

    Os valores são escolhidos pelo teste (coordenadas exatas, resultados, tempos), então cada fronteira de uma
    métrica pode ser testada sem depender dos dados reais. Tudo acontece na transação do teste.
    """

    def __init__(self, conn):
        self.conn = conn

    def run(self, sql, **params):
        return self.conn.execute(text(sql), params)

    def scalar(self, sql, **params):
        return self.run(sql, **params).scalar_one()

    def seed(self, match_id=100, home=1, away=2, home_score=0, away_score=0):
        """Competição, times 1 a 3, jogadores 11 a 13 (time 1) e 21 a 23 (time 2) e a partida `match_id`.

        Titulares: 11, 12, 21, 22. Reservas que não entraram: 13 e 23.
        """
        self.run("INSERT INTO core.competitions (competition_id, season_id, competition_name, season_name, competition_gender, "
                 "competition_youth, competition_international) VALUES (43, 106, 'FIFA World Cup', '2022', 'male', false, true)")
        for team_id, name in ((1, "Casa"), (2, "Fora"), (3, "Terceiro")):
            self.run("INSERT INTO core.teams (team_id, team_name) VALUES (:i, :n)", i=team_id, n=name)
        for player_id in (11, 12, 13, 21, 22, 23):
            self.run("INSERT INTO core.players (player_id, player_name) VALUES (:i, :n)", i=player_id, n=f"Jogador {player_id}")
        self.match(match_id, home, away, home_score, away_score)

    def match(self, match_id, home=1, away=2, home_score=0, away_score=0, *, lineups=True):
        self.run("INSERT INTO core.matches (match_id, competition_id, season_id, match_date, competition_stage, home_team_id, away_team_id, "
                 "home_score, away_score) VALUES (:m, 43, 106, '2022-12-18', 'Final', :h, :a, :hs, :as_)",
                 m=match_id, h=home, a=away, hs=home_score, as_=away_score)
        if lineups:
            for team, player, starter, played in ((home, 11, True, True), (home, 12, True, True), (home, 13, False, False),
                                                  (away, 21, True, True), (away, 22, True, True), (away, 23, False, False)):
                if team in (1, 2):  # os jogadores do seed só existem para os times 1 e 2
                    self.run("INSERT INTO core.lineups (match_id, team_id, player_id, is_starter, played) VALUES (:m, :t, :p, :s, :pl)",
                             m=match_id, t=team, p=player, s=starter, pl=played)

    def event(self, idx, type_name, team, player=None, *, period=1, ts=None, x=60.0, y=40.0, match_id=100, possession_team=None):
        """Insere um evento. `ts` = segundos desde o início do período (padrão: o próprio idx)."""
        ts = float(idx if ts is None else ts)
        event_id = uuid.uuid4()
        self.run("INSERT INTO core.events (event_id, match_id, idx, period, ts_in_period, minute, second, type_name, team_id, player_id, "
                 "possession, possession_team_id, play_pattern, x, y) VALUES (:e, :m, :i, :p, make_interval(secs => :ts), :min, :sec, :t, :tm, "
                 ":pl, 1, :ptm, 'Regular Play', :x, :y)",
                 e=event_id, m=match_id, i=idx, p=period, ts=ts, min=int(ts // 60), sec=int(ts % 60), t=type_name, tm=team, pl=player,
                 ptm=possession_team or team, x=x, y=y)
        return event_id

    def shot(self, idx, team, player, *, outcome="Saved", shot_type="Open Play", xg=0.1, period=1, ts=None, x=100.0, y=40.0,
             match_id=100, key_pass=None):
        event_id = self.event(idx, "Shot", team, player, period=period, ts=ts, x=x, y=y, match_id=match_id)
        self.run("INSERT INTO core.shots (event_id, statsbomb_xg, end_x, end_y, outcome, shot_type, key_pass_id) "
                 "VALUES (:e, :xg, 120, 40, :o, :t, :k)", e=event_id, xg=xg, o=outcome, t=shot_type, k=key_pass)
        return event_id

    def pass_(self, idx, team, player, *, x, y, end_x, end_y, outcome=None, pass_type=None, period=1, ts=None, match_id=100, recipient=None):
        event_id = self.event(idx, "Pass", team, player, period=period, ts=ts, x=x, y=y, match_id=match_id)
        self.run("INSERT INTO core.passes (event_id, recipient_id, end_x, end_y, outcome, pass_type, is_complete) "
                 "VALUES (:e, :r, :ex, :ey, :o, :t, :c)", e=event_id, r=recipient, ex=end_x, ey=end_y, o=outcome, t=pass_type, c=outcome is None)
        return event_id

    def carry(self, idx, team, player, *, x, y, end_x, end_y, period=1, ts=None, match_id=100):
        event_id = self.event(idx, "Carry", team, player, period=period, ts=ts, x=x, y=y, match_id=match_id)
        self.run("INSERT INTO core.carries (event_id, end_x, end_y) VALUES (:e, :ex, :ey)", e=event_id, ex=end_x, ey=end_y)
        return event_id


@pytest.fixture
def world(conn):
    return World(conn)
