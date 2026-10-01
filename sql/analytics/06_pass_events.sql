-- analytics.pass_events: uma linha por passe (todos, com as marcações que as métricas de passe usam).
--
-- O número 06 faz este arquivo rodar ANTES das views de estatísticas (10, 20), que leem esta view. Os passos
-- seguintes (M5, M7) acrescentam colunas NO FIM.
--
--   is_jogo_corrido  pass_type nulo (regular), 'Recovery' ou 'Interception'. Exclui bolas paradas e lateral
--   is_tentado       M4: passe tentado = período 1 a 4, não é 'Throw-in' (cobrado com a mão) e o resultado não é
--                    'Unknown' nem 'Injury Clearance'. Bola parada com o pé (escanteio, falta, tiro de meta, saída) conta
--
-- "Passe completo" é is_complete (resultado ausente na fonte). Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.pass_events AS
SELECT ev.event_id,
       ev.match_id,
       ev.idx,
       ev.team_id,
       t.team_name,
       ev.player_id,
       p.player_name,
       ps.recipient_id,
       r.player_name AS recipient_name,
       ev.period,
       ev.minute,
       ev.second,
       ev.ts_in_period,
       ev.x,
       ev.y,
       ps.end_x,
       ps.end_y,
       ps.length,
       ps.height,
       ps.pass_type,
       ps.body_part,
       ps.outcome,
       ps.is_complete,
       ps.is_cross,
       ps.is_switch,
       ps.is_through_ball,
       ps.is_shot_assist,
       ps.is_goal_assist,
       (ps.pass_type IS NULL OR ps.pass_type IN ('Recovery', 'Interception')) AS is_jogo_corrido,
       (ev.period <= 4
        AND ps.pass_type IS DISTINCT FROM 'Throw-in'
        AND (ps.outcome IS NULL OR ps.outcome NOT IN ('Unknown', 'Injury Clearance'))) AS is_tentado
FROM core.passes ps
JOIN core.events ev USING (event_id)
JOIN core.teams t ON t.team_id = ev.team_id
LEFT JOIN core.players p ON p.player_id = ev.player_id
LEFT JOIN core.players r ON r.player_id = ps.recipient_id;
