-- analytics.team_match_stats: uma linha por (partida, time), só de partidas com eventos carregados.
--
-- Colunas por métrica (docs/metrics.md). Cada passo do plano acrescenta colunas NO FIM; as anteriores não mudam.
--   M1  gols, gols_contra_a_favor, penaltis_disputa
--
-- Esta view nunca lê colunas JSONB (D05) e nunca grava nada.

CREATE VIEW analytics.team_match_stats AS
WITH played_matches AS (
    SELECT m.match_id, m.home_team_id, m.away_team_id
    FROM core.matches m
    WHERE EXISTS (SELECT 1 FROM core.events e WHERE e.match_id = m.match_id)
), match_teams AS (
    SELECT match_id, home_team_id AS team_id, true AS is_home FROM played_matches
    UNION ALL
    SELECT match_id, away_team_id, false FROM played_matches
), shot_goals AS (
    -- Tempo de jogo válido = períodos 1 a 4. A disputa de pênaltis (período 5) é contada à parte (D08).
    SELECT ev.match_id, ev.team_id,
           count(*) FILTER (WHERE ev.period <= 4) AS goals,
           count(*) FILTER (WHERE ev.period = 5) AS shootout_goals
    FROM core.shots s
    JOIN core.events ev USING (event_id)
    WHERE s.outcome = 'Goal'
    GROUP BY ev.match_id, ev.team_id
), own_goals AS (
    -- Gol contra: o evento 'Own Goal For' é do time BENEFICIADO e não tem jogador.
    SELECT match_id, team_id, count(*) AS n
    FROM core.events
    WHERE type_name = 'Own Goal For' AND period <= 4
    GROUP BY match_id, team_id
), shootouts AS (
    SELECT DISTINCT match_id FROM core.events WHERE period = 5
)
SELECT mt.match_id,
       mt.team_id,
       t.team_name,
       mt.is_home,
       -- M1: gols = finalizações com resultado 'Goal' + gols contra a favor (períodos 1 a 4)
       (COALESCE(g.goals, 0) + COALESCE(og.n, 0))::integer AS gols,
       COALESCE(og.n, 0)::integer AS gols_contra_a_favor,
       -- Sem disputa de pênaltis é NULL (não houve); com disputa, 0 é um valor válido (nenhum convertido).
       CASE WHEN so.match_id IS NULL THEN NULL ELSE COALESCE(g.shootout_goals, 0)::integer END AS penaltis_disputa
FROM match_teams mt
JOIN core.teams t ON t.team_id = mt.team_id
LEFT JOIN shot_goals g ON g.match_id = mt.match_id AND g.team_id = mt.team_id
LEFT JOIN own_goals og ON og.match_id = mt.match_id AND og.team_id = mt.team_id
LEFT JOIN shootouts so ON so.match_id = mt.match_id;
