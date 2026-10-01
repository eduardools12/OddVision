-- 002_core_tables.sql: as 12 tabelas do schema core.
--
-- Fonte da verdade: docs/data_dictionary.md. Colunas, tipos e obrigatoriedade seguem o
-- documento NA MESMA ORDEM; tests/integration/test_ddl.py compara o banco com o documento.
--
-- Repetível: CREATE TABLE IF NOT EXISTS. Este arquivo só cria e nunca apaga dados.
-- A ordem das tabelas respeita as chaves estrangeiras (dimensões, partidas, eventos, especializadas).
--
-- Convenções:
--   * Colunas `extra JSONB` guardam o que a fonte traz e o modelo ainda não usa (D07).
--     Nenhuma métrica do MVP pode depender delas.
--   * ON DELETE CASCADE só de partida -> filhas e evento -> tabelas especializadas: é o que
--     permite a carga por partida (apagar a partida e inserir de novo, D06).
--   * Booleanos "presentes só quando verdadeiros" na fonte ficam NOT NULL DEFAULT false.

-- ------------------------------------------------------------------ dimensões

CREATE TABLE IF NOT EXISTS core.competitions (
    competition_id            INTEGER NOT NULL,
    season_id                 INTEGER NOT NULL,
    competition_name          TEXT    NOT NULL,
    season_name               TEXT    NOT NULL,
    country_name              TEXT,
    competition_gender        TEXT    NOT NULL,
    competition_youth         BOOLEAN NOT NULL,
    competition_international BOOLEAN NOT NULL,
    extra                     JSONB   NOT NULL DEFAULT '{}',
    PRIMARY KEY (competition_id, season_id)
);
COMMENT ON TABLE core.competitions IS 'Uma linha por par competicao/temporada (competitions.json).';

CREATE TABLE IF NOT EXISTS core.teams (
    team_id      INTEGER NOT NULL PRIMARY KEY,
    team_name    TEXT    NOT NULL,
    team_gender  TEXT,
    country_name TEXT
);
COMMENT ON TABLE core.teams IS 'Uma linha por time (selecao), lido dos objetos home_team e away_team das partidas.';

CREATE TABLE IF NOT EXISTS core.players (
    player_id       INTEGER NOT NULL PRIMARY KEY,
    player_name     TEXT    NOT NULL,
    player_nickname TEXT,
    country_name    TEXT
);
COMMENT ON TABLE core.players IS 'Uma linha por jogador, lido das escalacoes.';

-- ------------------------------------------------------------------ partida

CREATE TABLE IF NOT EXISTS core.matches (
    match_id              INTEGER  NOT NULL PRIMARY KEY,
    competition_id        INTEGER  NOT NULL,
    season_id             INTEGER  NOT NULL,
    match_date            DATE     NOT NULL,
    kick_off              TIME,
    home_team_id          INTEGER  NOT NULL REFERENCES core.teams (team_id),
    away_team_id          INTEGER  NOT NULL REFERENCES core.teams (team_id),
    home_score            SMALLINT NOT NULL,
    away_score            SMALLINT NOT NULL,
    match_week            SMALLINT,
    competition_stage     TEXT,
    stadium_name          TEXT,
    referee_name          TEXT,
    match_status          TEXT,
    data_version          TEXT,
    shot_fidelity_version TEXT,
    xy_fidelity_version   TEXT,
    last_updated          TIMESTAMP,
    extra                 JSONB    NOT NULL DEFAULT '{}',
    FOREIGN KEY (competition_id, season_id) REFERENCES core.competitions (competition_id, season_id),
    CONSTRAINT chk_matches_teams_differ CHECK (home_team_id <> away_team_id),
    CONSTRAINT chk_matches_home_score   CHECK (home_score >= 0),
    CONSTRAINT chk_matches_away_score   CHECK (away_score >= 0)
);
COMMENT ON TABLE core.matches IS 'Uma linha por partida. O placar NAO inclui a disputa de penaltis.';

CREATE TABLE IF NOT EXISTS core.lineups (
    match_id       INTEGER  NOT NULL REFERENCES core.matches (match_id) ON DELETE CASCADE,
    team_id        INTEGER  NOT NULL REFERENCES core.teams (team_id),
    player_id      INTEGER  NOT NULL REFERENCES core.players (player_id),
    jersey_number  SMALLINT,
    is_starter     BOOLEAN  NOT NULL,
    played         BOOLEAN  NOT NULL,
    first_position TEXT,
    extra          JSONB    NOT NULL DEFAULT '{}',
    PRIMARY KEY (match_id, player_id),
    CONSTRAINT chk_lineups_starter_played CHECK (NOT is_starter OR played)
);
COMMENT ON TABLE core.lineups IS 'Uma linha por jogador relacionado na partida, inclusive quem nao entrou em campo.';

-- ------------------------------------------------------------------ eventos

CREATE TABLE IF NOT EXISTS core.events (
    event_id           UUID             NOT NULL PRIMARY KEY,
    match_id           INTEGER          NOT NULL REFERENCES core.matches (match_id) ON DELETE CASCADE,
    idx                INTEGER          NOT NULL,
    period             SMALLINT         NOT NULL,
    ts_in_period       INTERVAL         NOT NULL,
    minute             SMALLINT         NOT NULL,
    second             SMALLINT         NOT NULL,
    type_name          TEXT             NOT NULL,
    team_id            INTEGER          NOT NULL REFERENCES core.teams (team_id),
    player_id          INTEGER          REFERENCES core.players (player_id),
    position_name      TEXT,
    possession         INTEGER          NOT NULL,
    possession_team_id INTEGER          NOT NULL REFERENCES core.teams (team_id),
    play_pattern       TEXT             NOT NULL,
    x                  DOUBLE PRECISION,
    y                  DOUBLE PRECISION,
    duration           DOUBLE PRECISION,
    under_pressure     BOOLEAN          NOT NULL DEFAULT false,
    extra              JSONB            NOT NULL DEFAULT '{}',
    CONSTRAINT uq_events_match_idx UNIQUE (match_id, idx),
    CONSTRAINT chk_events_period   CHECK (period BETWEEN 1 AND 5),
    CONSTRAINT chk_events_second   CHECK (second BETWEEN 0 AND 59),
    CONSTRAINT chk_events_x        CHECK (x BETWEEN 0 AND 120),
    CONSTRAINT chk_events_y        CHECK (y BETWEEN 0 AND 80),
    CONSTRAINT chk_events_xy_pair  CHECK ((x IS NULL) = (y IS NULL))
);
COMMENT ON TABLE core.events IS 'Um evento da partida (nucleo do modelo). A ordem temporal e (period, idx), nunca minute.';

-- ------------------------------------------------------------------ eventos especializados (1:1 com events)

CREATE TABLE IF NOT EXISTS core.shots (
    event_id     UUID             NOT NULL PRIMARY KEY REFERENCES core.events (event_id) ON DELETE CASCADE,
    statsbomb_xg DOUBLE PRECISION NOT NULL,
    end_x        DOUBLE PRECISION NOT NULL,
    end_y        DOUBLE PRECISION NOT NULL,
    end_z        DOUBLE PRECISION,
    outcome      TEXT             NOT NULL,
    shot_type    TEXT             NOT NULL,
    body_part    TEXT,
    technique    TEXT,
    -- DEFERRABLE INITIALLY DEFERRED: conferida no COMMIT, e nao a cada comando. Sem isso, apagar uma
    -- partida falha: o banco checa esta chave logo depois de apagar o passe, quando a finalizacao que
    -- aponta para ele ainda nao foi removida pela cascata. A garantia continua valendo, so muda o momento.
    key_pass_id  UUID             REFERENCES core.events (event_id) DEFERRABLE INITIALLY DEFERRED,
    extra        JSONB            NOT NULL DEFAULT '{}',
    CONSTRAINT chk_shots_xg CHECK (statsbomb_xg BETWEEN 0 AND 1)
);
COMMENT ON TABLE core.shots IS 'Finalizacoes. statsbomb_xg e o xG do modelo do StatsBomb; o OddVision nao calcula xG.';

CREATE TABLE IF NOT EXISTS core.passes (
    event_id        UUID             NOT NULL PRIMARY KEY REFERENCES core.events (event_id) ON DELETE CASCADE,
    recipient_id    INTEGER          REFERENCES core.players (player_id),
    end_x           DOUBLE PRECISION NOT NULL,
    end_y           DOUBLE PRECISION NOT NULL,
    length          DOUBLE PRECISION,
    angle           DOUBLE PRECISION,
    height          TEXT,
    pass_type       TEXT,
    body_part       TEXT,
    outcome         TEXT,
    is_complete     BOOLEAN          NOT NULL,
    is_cross        BOOLEAN          NOT NULL DEFAULT false,
    is_switch       BOOLEAN          NOT NULL DEFAULT false,
    is_through_ball BOOLEAN          NOT NULL DEFAULT false,
    is_shot_assist  BOOLEAN          NOT NULL DEFAULT false,
    is_goal_assist  BOOLEAN          NOT NULL DEFAULT false,
    extra           JSONB            NOT NULL DEFAULT '{}',
    CONSTRAINT chk_passes_complete CHECK (is_complete = (outcome IS NULL)),
    CONSTRAINT chk_passes_end_x    CHECK (end_x BETWEEN 0 AND 120),
    CONSTRAINT chk_passes_end_y    CHECK (end_y BETWEEN 0 AND 80)
);
COMMENT ON TABLE core.passes IS 'Passes. outcome nulo significa passe completo; pass_type nulo significa passe regular.';

CREATE TABLE IF NOT EXISTS core.carries (
    event_id UUID             NOT NULL PRIMARY KEY REFERENCES core.events (event_id) ON DELETE CASCADE,
    end_x    DOUBLE PRECISION NOT NULL,
    end_y    DOUBLE PRECISION NOT NULL,
    CONSTRAINT chk_carries_end_x CHECK (end_x BETWEEN 0 AND 120),
    CONSTRAINT chk_carries_end_y CHECK (end_y BETWEEN 0 AND 80)
);
COMMENT ON TABLE core.carries IS 'Conducoes de bola. O objeto carry da fonte so tem end_location.';

CREATE TABLE IF NOT EXISTS core.cards (
    event_id  UUID NOT NULL PRIMARY KEY REFERENCES core.events (event_id) ON DELETE CASCADE,
    card_type TEXT NOT NULL
);
COMMENT ON TABLE core.cards IS 'Cartoes mostrados (eventos Foul Committed e Bad Behaviour com cartao).';

CREATE TABLE IF NOT EXISTS core.substitutions (
    event_id     UUID    NOT NULL PRIMARY KEY REFERENCES core.events (event_id) ON DELETE CASCADE,
    player_on_id INTEGER NOT NULL REFERENCES core.players (player_id),
    reason       TEXT
);
COMMENT ON TABLE core.substitutions IS 'Substituicoes. Quem sai e events.player_id; quem entra e player_on_id.';

-- ------------------------------------------------------------------ rastreabilidade

CREATE TABLE IF NOT EXISTS core.ingestion_log (
    file_path     TEXT        NOT NULL PRIMARY KEY,
    source_url    TEXT        NOT NULL,
    source_commit TEXT        NOT NULL,
    sha256        CHAR(64)    NOT NULL,
    size_bytes    BIGINT      NOT NULL,
    record_count  INTEGER,
    downloaded_at TIMESTAMPTZ NOT NULL,
    loaded_at     TIMESTAMPTZ
);
COMMENT ON TABLE core.ingestion_log IS 'Um arquivo bruto por linha (espelho do manifest da ingestao).';
