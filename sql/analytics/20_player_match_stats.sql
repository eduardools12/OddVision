-- analytics.player_match_stats: uma linha por (partida, jogador relacionado), só de partidas com eventos carregados.
--
-- Inclui quem não entrou em campo (played = false, com zeros): a escalação completa fica disponível.
-- Colunas por métrica (docs/metrics.md). Cada passo do plano acrescenta colunas NO FIM; as anteriores não mudam.
--   M1  gols
--
-- Esta view nunca lê colunas JSONB (D05) e nunca grava nada.

CREATE VIEW analytics.player_match_stats AS
WITH played_matches AS (
    SELECT DISTINCT match_id FROM core.events
), shot_goals AS (
    -- Gols do jogador = finalizações dele com resultado 'Goal' nos períodos 1 a 4. O gol contra não conta para
    -- nenhum jogador, e a disputa de pênaltis (período 5) fica de fora (D08).
    SELECT ev.match_id, ev.player_id, count(*) AS goals
    FROM core.shots s
    JOIN core.events ev USING (event_id)
    WHERE s.outcome = 'Goal' AND ev.period <= 4
    GROUP BY ev.match_id, ev.player_id
)
SELECT l.match_id,
       l.team_id,
       l.player_id,
       p.player_name,
       l.is_starter,
       l.played,
       COALESCE(g.goals, 0)::integer AS gols
FROM core.lineups l
JOIN played_matches pm ON pm.match_id = l.match_id
JOIN core.players p ON p.player_id = l.player_id
LEFT JOIN shot_goals g ON g.match_id = l.match_id AND g.player_id = l.player_id;
