-- analytics.convention_params: os parâmetros da CONVENÇÃO OddVision v1 das métricas progressivas (docs/metrics.md, D09).
--
-- Uma linha só. M5 (passes) e M6 (conduções) leem os mesmos números daqui, então as duas métricas não podem divergir:
-- mudar a convenção é mudar este arquivo.
--
--   min_start_x  início mínimo (x) da jogada: 40 por cento de 120 jardas, exclui o terço defensivo ampliado
--   min_gain_yd  ganho mínimo de distância ao gol (jardas), medida até o centro do gol, (120, 40)

CREATE VIEW analytics.convention_params AS
SELECT 48.0::double precision AS min_start_x,
       10.0::double precision AS min_gain_yd;
