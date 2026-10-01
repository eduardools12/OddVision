-- level: error
-- title: Eventos por partida em core.events = record_count do manifest
--
-- Para cada arquivo events/{match_id}.json marcado como carregado, o nº de eventos no core precisa ser o nº
-- de elementos do arquivo (record_count, gravado pela ingestão). Também é erro haver eventos de uma partida
-- cujo arquivo não consta como carregado. Arquivos nunca carregados (loaded_at nulo, sem eventos) são ignorados.
-- Devolve uma linha por partida com problema.

WITH logged AS (
    SELECT substring(file_path FROM '^events/([0-9]+)\.json$')::integer AS match_id, record_count, loaded_at
    FROM core.ingestion_log
    WHERE file_path ~ '^events/[0-9]+\.json$'
), counted AS (
    SELECT match_id, count(*) AS events_in_core FROM core.events GROUP BY match_id
)
SELECT COALESCE(l.match_id, c.match_id) AS match_id,
       l.record_count AS manifest,
       COALESCE(c.events_in_core, 0) AS in_core,
       l.loaded_at
FROM logged l
FULL JOIN counted c ON c.match_id = l.match_id
WHERE (l.loaded_at IS NOT NULL AND COALESCE(c.events_in_core, 0) <> l.record_count)
   OR (c.events_in_core IS NOT NULL AND (l.match_id IS NULL OR l.loaded_at IS NULL))
ORDER BY 1;
