-- level: warning
-- title: xG de pênalti = 0,7835 (o valor do modelo do StatsBomb em todos os 64 pênaltis da Copa 2022)
--
-- Se o modelo mudar de versão (matches.shot_fidelity_version), o valor pode mudar: por isso é aviso, não erro.

SELECT event_id, statsbomb_xg, 0.7835 AS expected
FROM core.shots
WHERE shot_type = 'Penalty' AND abs(statsbomb_xg - 0.7835) > 0.000001
ORDER BY event_id;
