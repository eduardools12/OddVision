-- analytics.player_match_stats: uma linha por (partida, jogador relacionado), só de partidas com eventos carregados.
--
-- Inclui quem não entrou em campo (played = false, com zeros): a escalação completa fica disponível.
-- Colunas por métrica (docs/metrics.md). Cada passo do plano acrescenta colunas NO FIM; as anteriores não mudam.
--   M1  gols
--   M2  finalizacoes, finalizacoes_no_alvo
--   M3  xg, npxg, finalizacoes_sem_penalti, npxg_por_finalizacao_sem_penalti
--   M4  passes_tentados, passes_completos, pct_acerto_passes
--   M5  passes_progressivos
--   M6  conducoes_progressivas
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
), shot_stats AS (
    -- M2 e M3 do jogador, com as mesmas regras do time (analytics.team_match_stats).
    SELECT match_id, player_id,
           count(*) AS shots,
           count(*) FILTER (WHERE is_no_alvo) AS shots_on_target,
           sum(statsbomb_xg) AS xg,
           COALESCE(sum(statsbomb_xg) FILTER (WHERE NOT is_penalty), 0) AS npxg,
           count(*) FILTER (WHERE NOT is_penalty) AS shots_no_pen
    FROM analytics.shot_events
    WHERE NOT is_shootout
    GROUP BY match_id, player_id
), pass_stats AS (
    -- M4 do jogador, com as mesmas regras do time (analytics.team_match_stats).
    SELECT match_id, player_id,
           count(*) FILTER (WHERE is_tentado) AS attempted,
           count(*) FILTER (WHERE is_tentado AND is_complete) AS completed,
           count(*) FILTER (WHERE is_progressivo) AS progressive
    FROM analytics.pass_events
    GROUP BY match_id, player_id
), carry_stats AS (
    -- M6 do jogador, com as mesmas regras do time (analytics.team_match_stats).
    SELECT match_id, player_id, count(*) AS progressive
    FROM analytics.carry_events
    WHERE is_progressivo
    GROUP BY match_id, player_id
)
SELECT l.match_id,
       l.team_id,
       l.player_id,
       p.player_name,
       l.is_starter,
       l.played,
       COALESCE(g.goals, 0)::integer AS gols,
       COALESCE(ss.shots, 0)::integer AS finalizacoes,
       COALESCE(ss.shots_on_target, 0)::integer AS finalizacoes_no_alvo,
       COALESCE(ss.xg, 0)::double precision AS xg,
       COALESCE(ss.npxg, 0)::double precision AS npxg,
       COALESCE(ss.shots_no_pen, 0)::integer AS finalizacoes_sem_penalti,
       CASE WHEN COALESCE(ss.shots_no_pen, 0) = 0 THEN NULL ELSE ss.npxg / ss.shots_no_pen END AS npxg_por_finalizacao_sem_penalti,
       COALESCE(pst.attempted, 0)::integer AS passes_tentados,
       COALESCE(pst.completed, 0)::integer AS passes_completos,
       CASE WHEN COALESCE(pst.attempted, 0) = 0 THEN NULL ELSE 100.0 * pst.completed / pst.attempted END::double precision AS pct_acerto_passes,
       COALESCE(pst.progressive, 0)::integer AS passes_progressivos,
       COALESCE(cst.progressive, 0)::integer AS conducoes_progressivas
FROM core.lineups l
JOIN played_matches pm ON pm.match_id = l.match_id
JOIN core.players p ON p.player_id = l.player_id
LEFT JOIN shot_goals g ON g.match_id = l.match_id AND g.player_id = l.player_id
LEFT JOIN shot_stats ss ON ss.match_id = l.match_id AND ss.player_id = l.player_id
LEFT JOIN pass_stats pst ON pst.match_id = l.match_id AND pst.player_id = l.player_id
LEFT JOIN carry_stats cst ON cst.match_id = l.match_id AND cst.player_id = l.player_id;
