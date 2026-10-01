-- analytics.pass_events: uma linha por passe (todos, com as marcações que as métricas de passe usam).
--
-- O número 06 faz este arquivo rodar ANTES das views de estatísticas (10, 20), que leem esta view. Os passos
-- seguintes (M7) acrescentam colunas NO FIM.
--
--   is_jogo_corrido  pass_type nulo (regular), 'Recovery' ou 'Interception'. Exclui bolas paradas e lateral
--   is_tentado       M4: passe tentado = período 1 a 4, não é 'Throw-in' (cobrado com a mão) e o resultado não é
--                    'Unknown' nem 'Injury Clearance'. Bola parada com o pé (escanteio, falta, tiro de meta, saída) conta
--   is_progressivo   M5, CONVENÇÃO OddVision v1: passe completo, de jogo corrido, período 1 a 4, com início em
--                    x >= min_start_x e que (aproxima a bola do gol em pelo menos min_gain_yd jardas OU entra na
--                    área). Distância ao gol = distância até o centro do gol, (120, 40). Área: x >= 102 e y de 18 a 62
--
-- "Passe completo" é is_complete (resultado ausente na fonte). Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.pass_events AS
WITH params AS (
    -- Parâmetros da convenção OddVision v1 (docs/metrics.md, M5): mudar a convenção é mudar estes dois números.
    SELECT 48.0::double precision AS min_start_x, 10.0::double precision AS min_gain_yd
), base AS (
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
    LEFT JOIN core.players r ON r.player_id = ps.recipient_id
)
SELECT b.*,
       COALESCE(
           b.is_complete AND b.is_jogo_corrido AND b.period <= 4
           AND b.x >= pr.min_start_x
           AND (sqrt((120 - b.x) ^ 2 + (40 - b.y) ^ 2) - sqrt((120 - b.end_x) ^ 2 + (40 - b.end_y) ^ 2) >= pr.min_gain_yd
                OR (NOT (b.x >= 102 AND b.y BETWEEN 18 AND 62) AND (b.end_x >= 102 AND b.end_y BETWEEN 18 AND 62))),
           false) AS is_progressivo
FROM base b
CROSS JOIN params pr;
