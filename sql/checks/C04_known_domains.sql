-- level: error
-- title: Valores categóricos dentro do domínio conhecido
--
-- Os domínios são os observados nas 64 partidas da Copa 2022 (docs/data_notes.md). Um valor novo (ou uma
-- grafia diferente) merece uma decisão humana antes de entrar nas métricas, por isso é erro. Nulo é válido em
-- passes.outcome (passe completo) e em passes.pass_type (passe regular).

SELECT 'shots.outcome' AS field, outcome AS value, count(*) AS n
FROM core.shots
WHERE outcome NOT IN ('Blocked', 'Goal', 'Off T', 'Post', 'Saved', 'Saved Off Target', 'Saved to Post', 'Wayward')
GROUP BY outcome
UNION ALL
SELECT 'shots.shot_type', shot_type, count(*)
FROM core.shots
WHERE shot_type NOT IN ('Open Play', 'Free Kick', 'Penalty', 'Corner')
GROUP BY shot_type
UNION ALL
SELECT 'passes.outcome', outcome, count(*)
FROM core.passes
WHERE outcome IS NOT NULL AND outcome NOT IN ('Incomplete', 'Out', 'Unknown', 'Pass Offside', 'Injury Clearance')
GROUP BY outcome
UNION ALL
SELECT 'passes.pass_type', pass_type, count(*)
FROM core.passes
WHERE pass_type IS NOT NULL
  AND pass_type NOT IN ('Recovery', 'Throw-in', 'Free Kick', 'Goal Kick', 'Corner', 'Interception', 'Kick Off')
GROUP BY pass_type
UNION ALL
SELECT 'cards.card_type', card_type, count(*)
FROM core.cards
WHERE card_type NOT IN ('Yellow Card', 'Second Yellow', 'Red Card')
GROUP BY card_type
ORDER BY 1, 2;
