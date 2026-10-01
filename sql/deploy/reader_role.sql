-- Role SÓ DE LEITURA para a aplicação publicada. Rode UMA vez no banco da nuvem, conectado como o dono do banco (a mesma
-- role que roda `init-db`), e troque a senha abaixo. NÃO é aplicado pelo pipeline: fica fora de sql/ddl e sql/analytics.
--
-- O que ela pode: conectar e ler as views do schema analytics. O que ela NÃO pode: escrever em nada e ler o schema
-- das tabelas-fonte (as views rodam com os privilégios do dono, então ela não precisa de acesso a essas tabelas).
-- O ALTER DEFAULT PRIVILEGES vale para as views que o `init-db` recria: o acesso continua depois de cada recriação.

CREATE ROLE oddvision_reader LOGIN PASSWORD 'TROQUE-ESTA-SENHA';
DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO oddvision_reader', current_database()); END $$;
GRANT USAGE ON SCHEMA analytics TO oddvision_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO oddvision_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO oddvision_reader;
