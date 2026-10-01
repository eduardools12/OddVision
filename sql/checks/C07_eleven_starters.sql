-- level: error
-- title: Cada time de cada partida tem exatamente 11 titulares
--
-- Titular = a primeira posição cronológica do jogador começou como 'Starting XI' (confirmado no Passo 2: coincide
-- com o evento Starting XI). Devolve o time e o nº de titulares encontrados quando não for 11.

SELECT match_id, team_id, count(*) FILTER (WHERE is_starter) AS starters
FROM core.lineups
GROUP BY match_id, team_id
HAVING count(*) FILTER (WHERE is_starter) <> 11
ORDER BY match_id, team_id;
