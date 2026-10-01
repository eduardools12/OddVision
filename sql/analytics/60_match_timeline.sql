-- analytics.match_timeline: os incidentes da partida em tempo válido (períodos 1 a 4), um por linha: gols, gols contra,
-- cartões e substituições. Ordene por (period, idx); tempo_decorrido_s, minuto_futebol e rotulo vêm de
-- analytics.event_clock (a mesma régua do gráfico de xG).
--
--   incident_type  'Goal' | 'Own Goal' | 'Card' | 'Substitution'
--   detail         Goal: 'Penalty' quando é pênalti, senão NULL. Card: 'Yellow Card', 'Second Yellow' ou 'Red Card'.
--                  Substitution: o motivo da fonte ('Tactical', 'Injury'...)
--   player_id      quem fez: o autor do gol, o cartão recebido, quem SAIU na substituição. Gol contra não tem jogador:
--                  o evento 'Own Goal For' é do time BENEFICIADO e a fonte não dá o autor nele
--   related_player_id  só na substituição: quem ENTROU
--
-- A disputa de pênaltis (período 5) não aparece (D08). Nunca lê colunas JSONB (D05).

CREATE VIEW analytics.match_timeline AS
WITH incidents AS (
    SELECT event_id, 'Goal' AS incident_type,
           CASE WHEN is_penalty THEN 'Penalty' END AS detail,
           NULL::integer AS related_player_id
    FROM analytics.shot_events
    WHERE is_goal AND NOT is_shootout
    UNION ALL
    SELECT event_id, 'Own Goal', NULL, NULL
    FROM core.events
    WHERE type_name = 'Own Goal For'
    UNION ALL
    SELECT event_id, 'Card', card_type, NULL
    FROM core.cards
    UNION ALL
    SELECT event_id, 'Substitution', reason, player_on_id
    FROM core.substitutions
)
SELECT ev.match_id,
       i.event_id,
       ev.idx,
       ev.period,
       ev.minute,
       ev.second,
       clk.tempo_decorrido_s,
       clk.minuto_futebol,
       clk.rotulo,
       i.incident_type,
       i.detail,
       ev.team_id,
       t.team_name,
       ev.player_id,
       p.player_name,
       i.related_player_id,
       rp.player_name AS related_player_name
FROM incidents i
JOIN core.events ev ON ev.event_id = i.event_id
JOIN analytics.event_clock clk ON clk.event_id = i.event_id
JOIN core.teams t ON t.team_id = ev.team_id
LEFT JOIN core.players p ON p.player_id = ev.player_id
LEFT JOIN core.players rp ON rp.player_id = i.related_player_id;
