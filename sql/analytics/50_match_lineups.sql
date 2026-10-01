-- analytics.match_lineups: uma linha por jogador relacionado na partida (titulares, reservas que entraram e reservas
-- que não entraram), com os nomes e os dados de súmula. Cobre toda partida que tenha escalação carregada.
--
-- Para a página da partida: ordene por is_starter DESC, jersey_number. As estatísticas por jogador estão em
-- analytics.player_match_stats. Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.match_lineups AS
SELECT l.match_id,
       l.team_id,
       t.team_name,
       l.player_id,
       p.player_name,
       p.player_nickname,
       l.jersey_number,
       l.is_starter,
       l.played,
       l.first_position
FROM core.lineups l
JOIN core.teams t ON t.team_id = l.team_id
JOIN core.players p ON p.player_id = l.player_id;
