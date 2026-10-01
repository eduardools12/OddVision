-- analytics.event_clock: o relógio de cada evento em tempo válido (períodos 1 a 4), na forma que o gráfico de xG (M8) e
-- a linha do tempo da partida usam. A disputa de pênaltis (período 5) não tem relógio: fica fora (D08).
--
--   tempo_decorrido_s  eixo de tempo REAL: soma da duração real dos períodos anteriores + ts_in_period. A duração de um
--                      período vem do Half End dele (há dois por período, um por time, com o mesmo horário: conta-se
--                      uma vez); sem Half End, vale o último evento do período. Assim um 1º tempo de 59 minutos não
--                      se sobrepõe ao 2º tempo
--   minuto_futebol     minute + 1 (o minuto da fonte é o decorrido e começa em 0)
--   rotulo             estilo futebol: "23'" e, nos acréscimos, "45+14'" (limites 45, 90, 105 e 120)
--
-- Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.event_clock AS
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
SELECT ev.event_id,
       ev.match_id,
       ev.period,
       (po.offset_s + extract(epoch FROM ev.ts_in_period))::double precision AS tempo_decorrido_s,
       (ev.minute + 1)::integer AS minuto_futebol,
       CASE WHEN ev.minute + 1 > lim.fim THEN lim.fim || '+' || (ev.minute + 1 - lim.fim) || ''''
            ELSE (ev.minute + 1) || '''' END AS rotulo
FROM core.events ev
JOIN period_offsets po ON po.match_id = ev.match_id AND po.period = ev.period
CROSS JOIN LATERAL (SELECT CASE ev.period WHEN 1 THEN 45 WHEN 2 THEN 90 WHEN 3 THEN 105 ELSE 120 END AS fim) lim
WHERE ev.period <= 4;
