-- analytics.xg_timeline: M8, xG acumulado ao longo da partida. Uma linha por finalização em tempo válido
-- (períodos 1 a 4, pênaltis incluídos, disputa de pênaltis fora), com o xG acumulado DO TIME até aquela finalização.
--
--   xg_acumulado       soma do statsbomb_xg das finalizações do time com (period, idx) até esta, inclusive.
--                      A ordem é (period, idx), nunca o campo minute (o minuto decorrido não é monotônico entre períodos)
--   tempo_decorrido_s, minuto_futebol e rotulo  vêm de analytics.event_clock (eixo de tempo real e rótulo em estilo
--                      futebol, "23'" e "45+14'"): a mesma régua da linha do tempo da partida
--
-- Um time sem finalizações não tem linhas: a série dele é constante em 0 (o gráfico trata). O primeiro ponto (0, 0)
-- também fica por conta da apresentação. Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.xg_timeline AS
SELECT s.event_id,
       s.match_id,
       s.idx,
       s.team_id,
       s.team_name,
       s.player_id,
       s.player_name,
       s.period,
       s.minute,
       s.second,
       clk.tempo_decorrido_s,
       clk.minuto_futebol,
       clk.rotulo,
       s.statsbomb_xg,
       s.is_goal,
       s.is_penalty,
       sum(s.statsbomb_xg) OVER (PARTITION BY s.match_id, s.team_id ORDER BY s.period, s.idx
                                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS xg_acumulado
FROM analytics.shot_events s
JOIN analytics.event_clock clk ON clk.event_id = s.event_id
WHERE NOT s.is_shootout;
