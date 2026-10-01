-- level: error
-- title: Coordenadas dentro do campo (x de 0 a 120, y de 0 a 80)
--
-- As CHECKs do banco já recusam estes valores; este check é a segunda barreira (e pega o caso de uma restrição
-- removida). Confere a posição dos eventos e o ponto final de passes e conduções. As finalizações ficam de fora:
-- o ponto final de um chute pode, legitimamente, sair do campo.

SELECT 'events' AS tbl, event_id, x, y
FROM core.events
WHERE x NOT BETWEEN 0 AND 120 OR y NOT BETWEEN 0 AND 80 OR ((x IS NULL) <> (y IS NULL))
UNION ALL
SELECT 'passes', event_id, end_x, end_y
FROM core.passes
WHERE end_x NOT BETWEEN 0 AND 120 OR end_y NOT BETWEEN 0 AND 80
UNION ALL
SELECT 'carries', event_id, end_x, end_y
FROM core.carries
WHERE end_x NOT BETWEEN 0 AND 120 OR end_y NOT BETWEEN 0 AND 80
ORDER BY 1, 2;
