-- analytics.match_summary: uma linha por partida (todas as de core.matches, tenham eventos ou não).
--
-- M1: o placar OFICIAL da fonte ao lado do reconstruído pelos eventos, e a disputa de pênaltis como informação
-- COMPLEMENTAR (ela não faz parte do placar: D08). Sem eventos carregados, a reconstrução é NULL.

CREATE VIEW analytics.match_summary AS
SELECT m.match_id,
       m.match_date,
       m.competition_stage,
       m.home_team_id,
       ht.team_name AS home_team_name,
       m.away_team_id,
       at.team_name AS away_team_name,
       m.home_score,
       m.away_score,
       (h.match_id IS NOT NULL) AS has_events,
       h.gols AS home_goals,
       a.gols AS away_goals,
       CASE WHEN h.match_id IS NULL THEN NULL
            ELSE (h.gols = m.home_score AND a.gols = m.away_score) END AS score_matches_events,
       h.penaltis_disputa AS home_penalties,
       a.penaltis_disputa AS away_penalties
FROM core.matches m
JOIN core.teams ht ON ht.team_id = m.home_team_id
JOIN core.teams at ON at.team_id = m.away_team_id
LEFT JOIN analytics.team_match_stats h ON h.match_id = m.match_id AND h.team_id = m.home_team_id
LEFT JOIN analytics.team_match_stats a ON a.match_id = m.match_id AND a.team_id = m.away_team_id;
