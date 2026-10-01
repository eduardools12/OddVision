-- analytics.shot_events: uma linha por finalização (inclusive as da disputa de pênaltis, marcadas), com os nomes e as
-- marcações que as métricas M2 e M3 e o mapa de finalizações precisam.
--
-- O número 05 faz este arquivo rodar ANTES das views de estatísticas (10, 20), que leem esta view.
--
--   is_goal      resultado 'Goal'
--   is_no_alvo   M2, convenção OddVision: 'Goal', 'Saved' e 'Saved to Post' (docs/metrics.md)
--   is_penalty   shot_type 'Penalty' (cobrança durante o jogo OU da disputa)
--   is_shootout  período 5: a disputa de pênaltis fica fora de todas as métricas (D08)
--
-- statsbomb_xg é o xG do modelo do StatsBomb; o OddVision não calcula xG. Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.shot_events AS
SELECT ev.event_id,
       ev.match_id,
       ev.idx,
       ev.team_id,
       t.team_name,
       ev.player_id,
       p.player_name,
       ev.period,
       ev.minute,
       ev.second,
       ev.ts_in_period,
       ev.x,
       ev.y,
       s.end_x,
       s.end_y,
       s.end_z,
       s.outcome,
       s.shot_type,
       s.body_part,
       s.technique,
       s.statsbomb_xg,
       s.key_pass_id,
       (s.outcome = 'Goal') AS is_goal,
       (s.outcome IN ('Goal', 'Saved', 'Saved to Post')) AS is_no_alvo,
       (s.shot_type = 'Penalty') AS is_penalty,
       (ev.period = 5) AS is_shootout
FROM core.shots s
JOIN core.events ev USING (event_id)
JOIN core.teams t ON t.team_id = ev.team_id
LEFT JOIN core.players p ON p.player_id = ev.player_id;
