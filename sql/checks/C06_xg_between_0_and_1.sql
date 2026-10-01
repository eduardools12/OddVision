-- level: error
-- title: xG de cada finalização informado e entre 0 e 1
--
-- O xG é o do modelo do StatsBomb (o OddVision não calcula xG). NOT NULL e CHECK já protegem a tabela; este check
-- é a segunda barreira.

SELECT event_id, statsbomb_xg
FROM core.shots
WHERE statsbomb_xg IS NULL OR statsbomb_xg NOT BETWEEN 0 AND 1
ORDER BY event_id;
