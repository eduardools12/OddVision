-- level: error
-- title: Cada tabela especializada tem uma linha por evento do seu tipo (e só de eventos do tipo certo)
--
-- shots = eventos 'Shot', passes = 'Pass', carries = 'Carry', substitutions = 'Substitution', por partida.
-- Os cartões (cards) não são 1:1 com um tipo de evento: são conferidos com as escalações no C09.
-- Duas famílias de problema: 'contagem' (número de linhas diferente) e 'tipo errado' (a linha aponta para
-- um evento de outro tipo, o que a contagem sozinha poderia esconder).

WITH expected AS (
    SELECT match_id, type_name, count(*) AS n
    FROM core.events
    WHERE type_name IN ('Shot', 'Pass', 'Carry', 'Substitution')
    GROUP BY match_id, type_name
), found AS (
    SELECT ev.match_id, 'Shot' AS type_name, count(*) AS n FROM core.shots t JOIN core.events ev USING (event_id) GROUP BY ev.match_id
    UNION ALL
    SELECT ev.match_id, 'Pass', count(*) FROM core.passes t JOIN core.events ev USING (event_id) GROUP BY ev.match_id
    UNION ALL
    SELECT ev.match_id, 'Carry', count(*) FROM core.carries t JOIN core.events ev USING (event_id) GROUP BY ev.match_id
    UNION ALL
    SELECT ev.match_id, 'Substitution', count(*) FROM core.substitutions t JOIN core.events ev USING (event_id) GROUP BY ev.match_id
)
SELECT 'contagem' AS kind,
       COALESCE(x.match_id, f.match_id) AS match_id,
       COALESCE(x.type_name, f.type_name) || ': ' || COALESCE(x.n, 0) || ' eventos, ' || COALESCE(f.n, 0) || ' linhas' AS detail
FROM expected x
FULL JOIN found f ON f.match_id = x.match_id AND f.type_name = x.type_name
WHERE COALESCE(x.n, 0) <> COALESCE(f.n, 0)
UNION ALL
SELECT 'tipo errado', ev.match_id, 'shots -> ' || ev.type_name
FROM core.shots t JOIN core.events ev USING (event_id) WHERE ev.type_name <> 'Shot'
UNION ALL
SELECT 'tipo errado', ev.match_id, 'passes -> ' || ev.type_name
FROM core.passes t JOIN core.events ev USING (event_id) WHERE ev.type_name <> 'Pass'
UNION ALL
SELECT 'tipo errado', ev.match_id, 'carries -> ' || ev.type_name
FROM core.carries t JOIN core.events ev USING (event_id) WHERE ev.type_name <> 'Carry'
UNION ALL
SELECT 'tipo errado', ev.match_id, 'substitutions -> ' || ev.type_name
FROM core.substitutions t JOIN core.events ev USING (event_id) WHERE ev.type_name <> 'Substitution'
UNION ALL
SELECT 'tipo errado', ev.match_id, 'cards -> ' || ev.type_name
FROM core.cards t JOIN core.events ev USING (event_id) WHERE ev.type_name NOT IN ('Foul Committed', 'Bad Behaviour')
ORDER BY 1, 2, 3;
