-- 001_schemas.sql: os dois schemas do OddVision (spec, seção 4).
--
--   core       dados da fonte, tipados, com chaves e restrições. Sem convenções analíticas (D15).
--   analytics  somente views com as métricas. Nunca lê colunas JSONB (D05).
--
-- Repetível: só cria o que ainda não existe.

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS analytics;

COMMENT ON SCHEMA core IS 'Dados do StatsBomb normalizados e tipados. Derivacoes so estruturais; convencoes ficam em analytics.';
COMMENT ON SCHEMA analytics IS 'Views com as metricas do OddVision. Nao le colunas extra (JSONB).';
