-- analytics.carry_events: uma linha por condução de bola (Carry), com a marcação da M6.
--
--   is_progressivo   M6, CONVENÇÃO OddVision v1: a mesma regra geométrica da M5 (analytics.pass_events), sem filtro de
--                    "completa" porque a condução não tem resultado na fonte. Período 1 a 4, início em
--                    x >= min_start_x e (ganho de distância ao gol >= min_gain_yd OU entrada na área).
--                    Parâmetros em analytics.convention_params. Área: x >= 102 e y de 18 a 62
--
-- Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.carry_events AS
SELECT ev.event_id,
       ev.match_id,
       ev.idx,
       ev.team_id,
       t.team_name,
       ev.player_id,
       p.player_name,
       ev.period,
       ev.minute,
       ev.second,
       ev.ts_in_period,
       ev.x,
       ev.y,
       c.end_x,
       c.end_y,
       COALESCE(
           ev.period <= 4
           AND ev.x >= pr.min_start_x
           AND (sqrt((120 - ev.x) ^ 2 + (40 - ev.y) ^ 2) - sqrt((120 - c.end_x) ^ 2 + (40 - c.end_y) ^ 2) >= pr.min_gain_yd
                OR (NOT (ev.x >= 102 AND ev.y BETWEEN 18 AND 62) AND (c.end_x >= 102 AND c.end_y BETWEEN 18 AND 62))),
           false) AS is_progressivo
FROM core.carries c
JOIN core.events ev USING (event_id)
JOIN core.teams t ON t.team_id = ev.team_id
LEFT JOIN core.players p ON p.player_id = ev.player_id
CROSS JOIN analytics.convention_params pr;
