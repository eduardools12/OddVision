-- level: error
-- title: Placar reconstruído pelos eventos = placar oficial da partida
--
-- Gols de um time = finalizações com resultado 'Goal' + eventos 'Own Goal For' (o gol contra é creditado ao time
-- beneficiado), no tempo regulamentar e na prorrogação (período 1 a 4). A disputa de pênaltis (período 5) não
-- entra: o placar oficial da fonte não a inclui. Só partidas que têm eventos carregados são conferidas.

WITH goals AS (
    SELECT match_id, team_id, count(*) AS n
    FROM (
        SELECT ev.match_id, ev.team_id
        FROM core.shots s JOIN core.events ev USING (event_id)
        WHERE s.outcome = 'Goal' AND ev.period <= 4
        UNION ALL
        SELECT match_id, team_id FROM core.events WHERE type_name = 'Own Goal For' AND period <= 4
    ) g
    GROUP BY match_id, team_id
)
SELECT m.match_id,
       m.home_score, COALESCE(h.n, 0) AS home_goals,
       m.away_score, COALESCE(a.n, 0) AS away_goals
FROM core.matches m
LEFT JOIN goals h ON h.match_id = m.match_id AND h.team_id = m.home_team_id
LEFT JOIN goals a ON a.match_id = m.match_id AND a.team_id = m.away_team_id
WHERE EXISTS (SELECT 1 FROM core.events ev WHERE ev.match_id = m.match_id)
  AND (m.home_score <> COALESCE(h.n, 0) OR m.away_score <> COALESCE(a.n, 0))
ORDER BY m.match_id;
