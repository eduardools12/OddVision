-- level: warning
-- title: Cartões dos eventos = cartões registrados nas escalações
--
-- Duas fontes do mesmo dado: os eventos (foul_committed.card e bad_behaviour.card, hoje em core.cards) e as
-- escalações (lineups.extra->'cards'). Comparadas por (partida, jogador, tipo de cartão). Aviso, não erro: a
-- divergência pode ser da fonte. Este check lê JSONB de propósito: está em sql/checks/, não em sql/analytics/.

WITH from_events AS (
    SELECT e.match_id, e.player_id, c.card_type, count(*) AS n
    FROM core.cards c JOIN core.events e USING (event_id)
    GROUP BY e.match_id, e.player_id, c.card_type
), from_lineups AS (
    SELECT l.match_id, l.player_id, card ->> 'card_type' AS card_type, count(*) AS n
    FROM core.lineups l, jsonb_array_elements(l.extra -> 'cards') AS card
    WHERE EXISTS (SELECT 1 FROM core.events ev WHERE ev.match_id = l.match_id)
    GROUP BY l.match_id, l.player_id, card ->> 'card_type'
)
SELECT COALESCE(a.match_id, b.match_id) AS match_id,
       COALESCE(a.player_id, b.player_id) AS player_id,
       COALESCE(a.card_type, b.card_type) AS card_type,
       COALESCE(a.n, 0) AS in_events,
       COALESCE(b.n, 0) AS in_lineups
FROM from_events a
FULL JOIN from_lineups b
  ON a.match_id = b.match_id AND a.player_id = b.player_id AND a.card_type = b.card_type
WHERE COALESCE(a.n, 0) <> COALESCE(b.n, 0)
ORDER BY 1, 2, 3;
