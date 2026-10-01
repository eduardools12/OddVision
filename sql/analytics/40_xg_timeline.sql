-- analytics.xg_timeline: M8, xG acumulado ao longo da partida. Uma linha por finalização em tempo válido
-- (períodos 1 a 4, pênaltis incluídos, disputa de pênaltis fora), com o xG acumulado DO TIME até aquela finalização.
--
--   xg_acumulado       soma do statsbomb_xg das finalizações do time com (period, idx) até esta, inclusive.
--                      A ordem é (period, idx), nunca o campo minute (o minuto decorrido não é monotônico entre períodos)
--   tempo_decorrido_s  eixo de tempo REAL: soma da duração real dos períodos anteriores + ts_in_period. A duração de um
--                      período vem do Half End dele (há dois por período, um por time, com o mesmo horário: conta-se
--                      uma vez); sem Half End, vale o último evento do período. Assim um 1º tempo de 59 minutos não
--                      se sobrepõe ao 2º tempo
--   minuto_futebol     minute + 1 (o minuto da fonte é o decorrido e começa em 0)
--   rotulo             estilo futebol: "23'" e, nos acréscimos, "45+14'" (limites 45, 90, 105 e 120)
--
-- Um time sem finalizações não tem linhas: a série dele é constante em 0 (o gráfico trata). O primeiro ponto (0, 0)
-- também fica por conta da apresentação. Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.xg_timeline AS
WITH period_durations AS (
    SELECT match_id, period,
           COALESCE(max(extract(epoch FROM ts_in_period)) FILTER (WHERE type_name = 'Half End'),
                    max(extract(epoch FROM ts_in_period)))::double precision AS duration_s
    FROM core.events
    WHERE period <= 4
    GROUP BY match_id, period
), period_offsets AS (
    SELECT match_id, period,
           COALESCE(sum(duration_s) OVER (PARTITION BY match_id ORDER BY period
                                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS offset_s
    FROM period_durations
)
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
       (po.offset_s + extract(epoch FROM s.ts_in_period))::double precision AS tempo_decorrido_s,
       (s.minute + 1)::integer AS minuto_futebol,
       CASE WHEN s.minute + 1 > lim.fim THEN lim.fim || '+' || (s.minute + 1 - lim.fim) || ''''
            ELSE (s.minute + 1) || '''' END AS rotulo,
       s.statsbomb_xg,
       s.is_goal,
       s.is_penalty,
       sum(s.statsbomb_xg) OVER (PARTITION BY s.match_id, s.team_id ORDER BY s.period, s.idx
                                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS xg_acumulado
FROM analytics.shot_events s
JOIN period_offsets po ON po.match_id = s.match_id AND po.period = s.period
CROSS JOIN LATERAL (SELECT CASE s.period WHEN 1 THEN 45 WHEN 2 THEN 90 WHEN 3 THEN 105 ELSE 120 END AS fim) lim
WHERE NOT s.is_shootout;
