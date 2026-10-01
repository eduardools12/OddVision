# OddVision — Registro de Decisões

Formato leve de ADR (*Architecture Decision Record*). Cada decisão registra o contexto, a escolha feita, as alternativas consideradas e as consequências.

**Status possíveis:** `Aceita` · `Substituída por Dxx` · `Revogada`.

| ID | Decisão | Status |
|---|---|---|
| D01 | Arquitetura híbrida: Python normaliza, SQL calcula | Aceita |
| D02 | PostgreSQL 18 local | Aceita |
| D03 | Python 3.13 | Aceita |
| D04 | Dados brutos imutáveis, fixados em commit e fora do Git | Aceita |
| D05 | `analytics` não lê JSONB | Aceita |
| D06 | `DELETE + INSERT` por partida dentro de transação | Aceita |
| D07 | Uso de `extra JSONB` | Aceita |
| D08 | Exclusão do período 5 de todas as métricas | Aceita |
| D09 | Definição das métricas progressivas (convenção OddVision v1) | Aceita |
| D10 | SQLAlchemy Core + psycopg 3 | Aceita |
| D11 | TOML para configuração | Aceita |
| D12 | Sem `statsbombpy` no pipeline principal | Aceita |
| D13 | Sem Docker, dbt e Airflow no MVP | Aceita |
| D14 | Nomenclatura: inglês no `core`, português minúsculo no `analytics` | Aceita |
| D15 | Convenções analíticas somente em `analytics` | Aceita |
| D16 | Regra de contrato por etapa (entrada, saída, validação) | Aceita |
| D17 | Nenhuma ação automática sobre o PostgreSQL existente | Aceita |
| D18 | Commits manuais pelo autor | Aceita |
| D19 | `pyproject.toml` + layout `src/` + instalação editável | Aceita |
| D20 | Versões fixadas das dependências diretas | Aceita |
| D21 | Política de imutabilidade da ingestão bruta | Aceita |
| D22 | Acesso ao banco, DDL repetível e isolamento dos testes de integração | Aceita |
| D23 | Carga no core: transformações puras, `upsert` e transação única | Aceita |

---

## D01 — Arquitetura híbrida: Python normaliza, SQL calcula

- **Contexto:** os dados do StatsBomb são JSON aninhado. As métricas são agregações com regras analíticas. O projeto é de estudo e deve exercitar tanto Python quanto SQL.
- **Decisão:**
  - Python/Pandas lê o JSON e grava tabelas tipadas no schema `core`.
  - Views SQL no schema `analytics` calculam as métricas.
  - O Streamlit lê somente de `analytics`.
- **Alternativas consideradas:**
  - *ELT puro em SQL* (JSON em `JSONB` e transformação 100% em SQL): SQL sobre JSON aninhado é difícil de ler e depurar em um projeto de estudo.
  - *ETL puro em Pandas* (métricas calculadas em Python): reduz o SQL a armazenamento e afasta o projeto de uma futura migração para dbt.
- **Consequências:**
  - Cada linguagem é usada no que faz melhor.
  - A camada `analytics` é migrável para dbt.
  - Exige manter duas linguagens e um contrato claro entre elas (o schema `core`).

## D02 — PostgreSQL 18 local

- **Contexto:** o projeto precisa de um banco relacional com integridade referencial, JSONB e SQL analítico (CTEs, funções de janela).
- **Decisão:** PostgreSQL 18 instalado localmente. Banco `oddvision` para os dados e `oddvision_test` para os testes de integração.
- **Alternativas:**
  - *Supabase* (Postgres hospedado): útil para deploy, mas desnecessário no MVP local.
  - *SQLite/DuckDB*: mais simples, mas foge do requisito de PostgreSQL e da prática de mercado buscada no portfólio.
  - *Docker*: veja D13.
- **Consequências:** exige resolver a instalação existente e incompleta (D17) no passo 0.

## D03 — Python 3.13

- **Contexto:** a máquina tem Python 3.12, 3.13 e 3.14; o 3.14 é o padrão.
- **Decisão:** o ambiente virtual do projeto usa **Python 3.13**.
- **Alternativas:** *3.14*, que é mais novo, mas tem maior risco de alguma dependência (por exemplo, a pilha científica do `mplsoccer`) ainda não ter *wheels* compatíveis.
- **Consequências:**
  - O venv deve ser criado explicitamente com `py -3.13`.
  - Reavaliar a migração para o 3.14 depois do MVP.
  - As versões das dependências são fixadas no passo 1, após conferir a compatibilidade.

## D04 — Dados brutos imutáveis, fixados em commit e fora do Git

- **Contexto:** o repositório `statsbomb/open-data` é atualizado com frequência (vários arquivos mudaram em 2026). Sem fixar a versão, os resultados não são reprodutíveis.
- **Decisão:**
  - Os arquivos são baixados de URLs fixadas em um **commit específico** (`config/selection.toml`).
  - São gravados em `data/raw/statsbomb/` **sem nenhuma alteração**.
  - O SHA-256 de cada arquivo fica registrado em `data/manifests/statsbomb_manifest.csv`.
  - A pasta `data/` fica fora do Git.
  - O manifest fica em `data/manifests/`, e não dentro de `data/raw/`, para que a pasta bruta contenha somente arquivos da fonte.
- **Alternativas:**
  - *Clonar o repositório inteiro*: vários GB, e só usamos 130 arquivos.
  - *Baixar do branch `master`*: não é reprodutível.
  - *Versionar os JSONs no Git*: incha o repositório, e a licença pede atribuição, não redistribuição.
- **Consequências:**
  - O MVP ingere exatamente **130 arquivos**: 1 `competitions.json`, 1 arquivo de matches, 64 de events e 64 de lineups.
  - Reprocessar nunca exige baixar de novo.
  - Atualizar a fonte é uma decisão explícita: trocar o commit e comparar os resultados.

## D05 — `analytics` não lê JSONB

- **Contexto:** se métricas lessem JSONB, a lógica analítica dependeria de campos não documentados e não tipados.
- **Decisão:** nenhuma view de `analytics` usa colunas `extra` nem operadores JSON (`->`, `->>`, `#>`, `#>>`, `@>`, `?`). Um teste automatizado varre `sql/analytics/` e falha se encontrar algum deles.
- **Alternativas:** permitir JSONB "temporariamente", o que tende a se tornar permanente.
- **Consequências:** quando uma métrica nova precisar de um campo que está em `extra`, esse campo vira primeiro uma coluna tipada, documentada em `data_dictionary.md`.

## D06 — `DELETE + INSERT` por partida dentro de transação

- **Contexto:** o pipeline precisa ser idempotente: rodar duas vezes não pode duplicar dados.
- **Decisão:**
  - **Dados por partida** (`events`, `shots`, `passes`, `carries`, `cards`, `substitutions`, `lineups`): em **uma transação por partida**, apagar as linhas da partida e inserir de novo. As tabelas específicas usam `ON DELETE CASCADE` a partir de `core.events`.
  - **Dimensões compartilhadas** (`competitions`, `teams`, `players`): `INSERT … ON CONFLICT DO UPDATE`, porque não pertencem a uma única partida.
- **Alternativas:** *upsert em tudo* (`ON CONFLICT`). Funciona, mas não remove eventos que tenham deixado de existir na fonte, e é mais complexo de escrever e testar.
- **Consequências:**
  - Uma falha no meio de uma partida desfaz a transação inteira: a partida fica como estava antes, nunca pela metade.
  - O `DELETE` é **restrito a uma partida**, por `match_id`, e nunca é executado sem filtro.

## D07 — Uso de `extra JSONB`

- **Contexto:** a fonte tem muitos campos que o MVP não usa (por exemplo, `freeze_frame`, `tactics`, duelos, pressões). Descartá-los impediria evoluir sem reingestão; modelá-los todos agora seria complexidade prematura.
- **Decisão:**
  - Cada tabela do `core` que vem do JSON tem uma coluna `extra JSONB NOT NULL DEFAULT '{}'`, com a regra **`extra` = objeto de origem − chaves mapeadas para colunas**.
  - O objeto específico de um tipo com tabela própria (`shot`, `pass`, `carry`…) não fica duplicado em `events.extra`: o que sobra dele vai para o `extra` da tabela específica.
  - Toda informação usada em uma métrica do MVP é **coluna tipada**, nunca JSONB.
- **Alternativas:**
  - *Descartar campos não usados*: perde informação.
  - *Uma tabela por tipo de evento*: são 33 tipos, o que é prematuro.
- **Consequências:**
  - Nada da fonte se perde.
  - O `extra` pode ser lido em notebooks e checks, mas nunca em `analytics` (D05).

## D08 — Exclusão do período 5 de todas as métricas

- **Contexto:** o período 5 é a disputa de pênaltis (5 partidas e 106 eventos na Copa 2022). Os chutes da disputa têm xG (0,7835) e resultado `Goal`, mas **não fazem parte do placar** (`matches.home_score` não os inclui; verificado na final: 3–3).
- **Decisão:** `period = 5` fica excluído de **todas** as 8 métricas. O resultado da disputa é exibido como **informação complementar** (`penaltis_disputa`), separado do placar.
- **Alternativas:** incluir a disputa no xG e nas finalizações, o que inflaria as métricas e as tornaria inconsistentes com o placar oficial.
- **Consequências:** a regra é global e é coberta por teste.

## D09 — Definição das métricas progressivas (convenção OddVision v1)

- **Contexto:** não existe definição universal de passe ou condução progressiva. As fontes públicas (FBref, Wyscout e outras) divergem entre si.
- **Decisão:** adotar uma **convenção própria, chamada OddVision v1**, documentada em `metrics.md` (M5 e M6):
  - **Passe progressivo:** passe completo, de jogo corrido, com `x ≥ 48` e (redução da distância ao centro do gol ≥ 10 jardas **ou** entrada na área).
  - **Condução progressiva:** a **mesma regra geométrica** aplicada a `Carry`.
  - Os parâmetros são nomeados (`MIN_START_X = 48`, `MIN_GAIN_YD = 10`) e declarados em uma CTE `params` nas views.
- **Escolhas deliberadas:**
  - *Distância ao centro do gol* em vez de ganho em `x`: valoriza a aproximação ao gol, e não à bandeira de escanteio.
  - *A mesma regra para passes e conduções* (diferente do FBref, que trata conduções pelo ponto final): é consistente e mais fácil de explicar.
  - *Sem regra de sequência* ("últimos N passes"): simplificação do MVP, prevista para a v1.2.
- **Consequências:**
  - Os números **não são comparáveis** com outros provedores.
  - A interface exibe o rótulo "OddVision v1".
  - Mudar a regra cria uma nova versão (v2), registrada aqui.

## D10 — SQLAlchemy Core + psycopg 3

- **Contexto:** o pandas lê e grava no PostgreSQL por meio de uma conexão. O `pandas.read_sql` suporta oficialmente objetos SQLAlchemy; com conexões DBAPI puras (exceto sqlite3), ele emite avisos.
- **Decisão:** `psycopg` 3 como driver e `SQLAlchemy` **Core** (sem ORM) como camada de conexão. O SQL de carga e as views são escritos explicitamente com `text()` e arquivos `.sql`.
- **Alternativas:**
  - *Só `psycopg`*: gera avisos no pandas e mais código manual.
  - *SQLAlchemy ORM*: abstração desnecessária para um pipeline analítico.
  - *`psycopg2`*: geração anterior do driver.
- **Consequências:** o SQL continua visível e é aprendido diretamente, sem ser escondido por um ORM.

## D11 — TOML para configuração

- **Contexto:** o projeto precisa de configuração (competição, commit da fonte) e de credenciais do banco, tanto no pipeline quanto no app.
- **Decisão:**
  - `config/selection.toml` (versionado) e `config/database.toml` (**não versionado**; o modelo fica em `database.example.toml`).
  - A leitura usa `tomllib`, da biblioteca padrão.
- **Alternativas:**
  - *`python-dotenv` + `.env`*: uma dependência a mais.
  - *`.streamlit/secrets.toml`*: acoplaria o pipeline ao Streamlit.
  - *Variáveis de ambiente puras*: pouco práticas no Windows para estudo.
- **Consequências:** zero dependências extras e um único formato de configuração.

## D12 — Sem `statsbombpy` no pipeline principal

- **Contexto:** o `statsbombpy` entrega DataFrames já achatados e esconde a estrutura do JSON, incluindo as ausências com significado.
- **Decisão:** o pipeline lê o JSON bruto diretamente. O `statsbombpy` pode ser usado no futuro **apenas** como ferramenta de conferência cruzada, fora do pipeline, com aviso prévio.
- **Consequências:** mais código de normalização, que é justamente o objetivo de aprendizado.

## D13 — Sem Docker, dbt e Airflow no MVP

- **Contexto:** o MVP é local, com um único usuário, e o volume é pequeno (cerca de 235 mil eventos).
- **Decisão:** nenhuma dessas ferramentas no MVP.
  - A orquestração é um CLI Python.
  - As transformações SQL são arquivos `.sql` versionados.
  - O ambiente é venv + PostgreSQL local.
- **Consequências:**
  - Menos complexidade enquanto os fundamentos são aprendidos.
  - A arquitetura (D01, D15) foi desenhada para permitir a adoção posterior de dbt (camada `analytics`), Docker (ambiente) e um orquestrador (pipeline) sem reescrita conceitual.

## D14 — Nomenclatura: inglês no `core`, português minúsculo no `analytics`

- **Contexto:** o PostgreSQL converte identificadores sem aspas para minúsculas (`xG_acumulado` vira `xg_acumulado`). Os nomes do `core` precisam ser rastreáveis até a fonte, que está em inglês.
- **Decisão:**
  - **`core`:** nomes em inglês, alinhados à fonte (`statsbomb_xg`, `pass_type`, `end_x`).
  - **`analytics`:** nomes das métricas em português, minúsculos, sem acentos (`passes_progressivos`, `conducoes_progressivas`, `xg_acumulado`, `npxg`).
  - A grafia "xG" aparece apenas nos rótulos da interface.
- **Alternativas:** tudo em inglês, ou identificadores com aspas (`"xG"`), que obrigariam a usar aspas em todas as consultas.
- **Consequências:** a mudança de idioma marca visualmente a fronteira entre o dado da fonte e a métrica do OddVision.

## D15 — Convenções analíticas somente em `analytics`

- **Contexto:** se limiares e exclusões morassem no `core`, mudar uma convenção exigiria recarregar os dados.
- **Decisão:**
  - O `core` contém apenas dados da fonte e derivações estruturais determinísticas (por exemplo, `is_complete`).
  - Limiares, mapeamentos ("no alvo") e filtros ("jogo corrido") existem **somente** nas views de `analytics`.
- **Consequências:** trocar uma convenção é uma mudança só de SQL, sem reprocessar os dados.

## D16 — Regra de contrato por etapa

- **Contexto:** regra de trabalho definida pelo autor.
- **Decisão:** nenhuma implementação começa sem **entrada, processamento, saída e critério de validação** definidos. Isso vale para as etapas do pipeline (spec, seção 5) e para os passos do roadmap (spec, seção 9).
- **Consequências:** todo passo tem uma forma objetiva de dizer que está pronto.

## D17 — Nenhuma ação automática sobre o PostgreSQL existente

- **Contexto:** a inspeção somente leitura de 2026-09-29 encontrou:
  - `C:\Program Files\PostgreSQL\18\` com uma pasta `data/` (cluster com `PG_VERSION`, `base`, `current_logfiles`);
  - `bin/` com 46 arquivos (bibliotecas de PostGIS/MobilityDB), **sem** `psql.exe` e sem `postgres.exe`;
  - nenhum serviço Windows do PostgreSQL.

  A pasta `data/` pode conter dados de outros projetos.
- **Decisão:**
  - Antes de qualquer ação relacionada ao PostgreSQL, o ambiente é **reinspecionado e relatado** ao autor.
  - **Nada é apagado, movido, formatado, sobrescrito ou reinstalado automaticamente.**
  - A decisão sobre a instalação existente é do autor.
- **Consequências:** o passo 0 pode exigir uma ação manual do autor (por exemplo, reinstalar ou reparar o PostgreSQL).

## D18 — Commits manuais pelo autor

- **Decisão:** o assistente nunca faz commits. Cada passo do roadmap termina com uma sugestão de mensagem de commit, que o autor revisa e executa.
- **Consequências:** o histórico do Git reflete as decisões do autor.

## D19 — `pyproject.toml` + layout `src/` + instalação editável

- **Contexto:** a spec previa apenas `requirements*.txt`. Mas o pipeline será executado como `python -m oddvision.pipeline`, e os testes e o app precisam importar `oddvision` de qualquer pasta. Com o layout `src/`, isso só funciona com o pacote instalado.
- **Decisão:**
  - `pyproject.toml` com `[build-system]` (setuptools ≥ 64, o mínimo para instalação editável via PEP 660), `[project]` (nome, versão, `requires-python = ">=3.13,<3.14"`) e a configuração do pytest em `[tool.pytest]`.
  - O código fica em `src/oddvision/` e é instalado com `pip install -e .`.
  - `dependencies = []` no `pyproject.toml`: as versões ficam **só** em `requirements*.txt`, que é a fonte única.
- **Alternativas:**
  - *`PYTHONPATH=src`*: frágil, porque depende de cada terminal estar configurado.
  - *Código na raiz* (sem `src/`): os testes passariam importando o código da pasta atual mesmo sem instalação, escondendo erros de empacotamento.
  - *Declarar as dependências também no `pyproject.toml`*: duplicaria as versões em dois lugares.
- **Consequências:**
  - O teste *smoke* verifica que `oddvision` é importado de `src/`.
  - Instalar em Python 3.14 falha de propósito, por causa do `requires-python`.
  - Montar o ambiente exige dois comandos: `pip install -r requirements-dev.txt` e `pip install -e .`.
- **Não é uma dependência nova:** o setuptools é usado apenas na construção do pacote. O pip o obtém num ambiente isolado.

## D20 — Versões fixadas das dependências diretas

- **Contexto:** reprodutibilidade (spec, seção 13). As versões foram verificadas em 2026-09-29 no PyPI (existência de *wheel* `cp313-win_amd64` ou `py3-none-any`) e no Context7.
- **Decisão:** fixar com `==` somente as dependências **diretas**:

| Pacote | Versão | Critério |
|---|---|---|
| pandas | 3.0.6 | Série 3.x estável; *wheel* cp313 |
| psycopg[binary] | 3.3.6 | O extra `[binary]` embute a libpq (18.0.4): não exige PostgreSQL instalado para instalar o driver |
| SQLAlchemy | 2.0.54 | A série **2.1** foi lançada em 24/09/2026 e recebeu um *patch* no dia seguinte. A 2.0 é madura e cobre o uso previsto (Core + `postgresql+psycopg`) |
| streamlit | 1.64.0 | Versão atual |
| mplsoccer | 1.8.1 | Versão atual |
| pytest (dev) | 9.1.1 | Versão atual; configuração TOML nativa |
| ipykernel (dev) | 7.3.0 | A 7.4.0 foi publicada em 2026-09-29, o mesmo dia da escolha. Evitamos versões com horas de vida |

- **Regra de escolha:** usar a versão estável mais recente, **exceto** quando a série ou versão tiver menos de cerca de uma semana. Nesse caso, usar a anterior.
- **Alternativas:** fixar também as dependências transitivas (`pip freeze` completo) ou usar um *lock file*. Fica para depois do MVP, se a reprodutibilidade exigir.
- **Consequências:**
  - As dependências transitivas (numpy, scipy, matplotlib, pyarrow, requests etc.) são resolvidas pelo pip e podem variar entre instalações.
  - O `requests` chega como dependência transitiva do `mplsoccer`, mas **não é usado** pelo OddVision: a ingestão usa `urllib` (spec, seção 13).
  - O teste *smoke* confere as versões diretas.

## D21 — Política de imutabilidade da ingestão bruta

- **Contexto:** o D04 diz que os dados brutos são imutáveis e fixados em um commit. A ingestão (Passo 3) precisa transformar isso em regras verificáveis: o que fazer quando disco, manifest e fonte discordam.
- **Decisão:**
  - **O manifest é a prova.** Cada arquivo baixado tem `sha256`, tamanho, `record_count`, URL e commit registrados em `data/manifests/statsbomb_manifest.csv`.
  - **Arquivo existente:** só é aceito se constar no manifest **e** o `sha256` do disco conferir. Arquivo alterado, ou arquivo sem registro no manifest = `IntegrityError`, sem alterar nada.
  - **Arquivo ausente com registro no manifest:** é baixado de novo, mas o conteúdo novo precisa ter o **mesmo** `sha256`. Conteúdo diferente = erro, e o arquivo novo não é gravado.
  - **Commit:** se o manifest registra um commit diferente do configurado = erro. Trocar a versão da fonte é uma decisão explícita e exige outra pasta de dados.
  - **Só entra JSON válido:** o conteúdo precisa ser um array JSON. Isso é validado **antes** de gravar.
  - **Gravação atômica** (`.part` + renomear) e **manifest regravado a cada arquivo**: uma execução interrompida é retomada de onde parou.
  - **O commit precisa ser um SHA completo** (40 caracteres hexadecimais). Um nome de branch é rejeitado pela configuração, porque não fixa nada.
  - **O repositório canônico é `hudl/open-data`** (o antigo `statsbomb/open-data` foi transferido e ainda redireciona). Os textos do D04 e da spec que citam o nome antigo continuam válidos, porque as duas URLs devolvem os mesmos bytes.
- **Alternativas:**
  - *Sobrescrever silenciosamente* o arquivo alterado: viola D04.
  - *Adotar como válido* um arquivo sem registro no manifest: não há como provar que é o original.
  - *Verificar contra o SHA de blob do Git* (API do GitHub): prova mais forte, mas exige uma API a mais; adiado.
- **Consequências:**
  - Um erro de integridade nunca apaga nem sobrescreve nada. O autor decide o que fazer (restaurar ou remover o arquivo manualmente).
  - Se o manifest for perdido, a ingestão para em vez de "adotar" os arquivos. É intencional.
  - A ingestão é sequencial: os 130 arquivos (192 MB) levam cerca de 1min40 e a 2ª execução leva cerca de 2 segundos.

## D22 — Acesso ao banco, DDL repetível e isolamento dos testes de integração

- **Contexto:** o Passo 4 cria os bancos e o DDL. O servidor desta máquina usa a **porta 1212** (herdada da instalação antiga), e os testes de integração precisam recriar schemas sem nunca tocar nos dados reais.
- **Decisão:**
  - **Credenciais em `config/database.toml`** (fora do Git; o modelo versionado é `database.example.toml`), com `host`, `port`, `user`, `password` e os nomes `main` e `test`. A leitura aceita arquivos com BOM (editores do Windows os gravam assim).
  - **O pipeline usa a role `oddvision_app`**: sem privilégio de superusuário, dona dos dois bancos. O superusuário `postgres` só é usado na criação inicial.
  - **`databases.test` deve terminar em `_test`.** É validado ao carregar a configuração e conferido de novo no servidor (`current_database()`) antes de qualquer `DROP SCHEMA`, que só existe no código de teste.
  - **Sem `config/database.toml`, os testes de integração são pulados** (com o motivo). **Com o arquivo presente e a conexão falhando, eles falham**: erro de configuração nunca passa por "tudo verde".
  - **`init-db` só cria.** Aplica `sql/ddl/NNN_*.sql` em ordem, um arquivo por transação, usando apenas `CREATE ... IF NOT EXISTS`. Um teste estático proíbe `DROP`, `TRUNCATE` e `DELETE FROM` no DDL.
  - **O DDL é validado contra `docs/data_dictionary.md`** por um teste que lê as colunas do próprio documento (nome, tipo, obrigatoriedade e ordem), sem copiá-las para o teste.
  - **`shots.key_pass_id` é `DEFERRABLE INITIALLY DEFERRED`.** Um teste de comportamento mostrou que, com a chave imediata, apagar uma partida (a base da carga por partida, D06) falha: o PostgreSQL confere a chave logo depois de apagar o passe, antes de a cascata remover a finalização. Adiar a conferência para o `COMMIT` mantém a garantia e permite a carga.
- **Alternativas:**
  - *`ON DELETE SET NULL` em `key_pass_id`*: apagaria a informação silenciosamente.
  - *`DROP` + recriar no `init-db`*: destrutivo, contra o D17.
  - *Rodar tudo com o superusuário*: privilégio maior que o necessário.
- **Consequências:**
  - `init-db` não faz `ALTER`: mudar uma tabela que já existe em um banco com dados exigirá uma migração explícita (a decidir quando acontecer).
  - Não há índices além de chaves primárias e `UNIQUE`. Só serão criados se a medição nos Passos 10 e 13 justificar.
  - Um servidor PostgreSQL descartável (pasta de dados e porta próprias, fora do servidor do autor) foi usado para validar o DDL e os testes antes de o autor criar os bancos reais.

## D23 — Carga no core: transformações puras, `upsert` e transação única

- **Contexto:** o Passo 5 é a primeira carga real (competições, times, partidas e `ingestion_log`). As escolhas feitas aqui valem para as cargas de escalações e eventos dos Passos 6 a 8.
- **Decisão:**
  - **Transformação e gravação são separadas.** `transform/*.py` são funções puras (JSON → DataFrame, sem rede, disco nem banco); `load.py` grava. Os testes das transformações não precisam de banco.
  - **Ler e transformar antes de abrir a transação.** Um arquivo bruto adulterado (`read_verified_json` compara o sha256 com o manifest) ou um campo obrigatório ausente (`TransformError`, com a partida e o campo) aborta sem tocar no banco.
  - **Uma transação por carga:** tudo entra junto ou nada entra. Um teste força uma violação de `CHECK` no meio e confere que `competitions` e `teams` também foram desfeitos.
  - **`upsert` genérico** (`INSERT … ON CONFLICT DO UPDATE`) para as dimensões e o `ingestion_log`. Nomes de tabela e coluna são validados como identificadores, porque não podem ir como parâmetro SQL. A coluna `extra` é convertida com `CAST(… AS JSONB)`.
  - **`ingestion_log.loaded_at` guarda o momento da última carga de cada arquivo** e fica nulo para o que ainda não foi carregado. Registrar o manifest de novo não apaga um valor já gravado (`COALESCE`).
  - **`matches.extra` = origem menos o que virou coluna de `matches` ou das tabelas geradas do mesmo objeto** (`competitions`, `teams`). Os pais que ficam vazios são podados; chaves ausentes são ignoradas.
  - **DataFrames com dtype `object`:** guardam os objetos Python exatos (`date`, `time`, `datetime`, `dict`, `None`) que viram os tipos SQL, sem a conversão de nulos para `NaN` do pandas. Para os eventos (234 mil linhas) o dtype será reavaliado se a medição mostrar necessidade.
  - **O mesmo time com atributos diferentes entre partidas é um erro**, e não uma escolha silenciosa. (Na Copa 2022 não ocorre: os 32 times são consistentes.)
- **Alternativas:**
  - *`DataFrame.to_sql`:* não faz *upsert* e não converte `extra` para JSONB.
  - *Uma transação por tabela:* poderia deixar partidas sem a competição carregada, ou o contrário.
  - *Dtypes do pandas (`Int64`, `string`):* `pd.NA` e `NaN` precisariam de conversão manual antes de cada gravação.
- **Consequências:**
  - Cada passo de carga tem uma única função de entrada (`load_p2`, e as próximas), com entrada, saída e validação definidas.
  - A carga carrega as 64 partidas, mas só as 3 sentinelas terão eventos até o Passo 13: o app precisará tratar partidas sem eventos.
