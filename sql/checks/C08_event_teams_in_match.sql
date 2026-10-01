-- level: error
-- title: Todo evento é de um dos dois times da partida (mandante ou visitante)
--
-- Protege o match_id, que vem do NOME do arquivo (o JSON de eventos não o contém): se um arquivo fosse gravado
-- com a partida errada, os times dos eventos não bateriam com os da partida. Confere o time do evento e o time
-- com a posse.

SELECT e.match_id, e.event_id, e.team_id, e.possession_team_id
FROM core.events e
JOIN core.matches m USING (match_id)
WHERE e.team_id NOT IN (m.home_team_id, m.away_team_id)
   OR e.possession_team_id NOT IN (m.home_team_id, m.away_team_id)
ORDER BY e.match_id, e.idx;
