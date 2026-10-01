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
| D18 | Commits manuais pelo autor | Substituída por D26 |
| D19 | `pyproject.toml` + layout `src/` + instalação editável | Aceita |
| D20 | Versões fixadas das dependências diretas | Aceita |
| D21 | Política de imutabilidade da ingestão bruta | Aceita |
| D22 | Acesso ao banco, DDL repetível e isolamento dos testes de integração | Aceita |
| D23 | Carga no core: transformações puras, `upsert` e transação única | Aceita |
| D24 | Escalações: ordem cronológica das posições e atributos dos jogadores | Aceita |
| D25 | Eventos: o que sai do `extra`, tempo exato e carga na transação da partida | Aceita |
| D26 | Autorização permanente do autor para commitar e avançar de passo | Aceita |
| D27 | Eventos especializados: nada se perde em silêncio | Aceita |
| D28 | Checks de qualidade: arquivos SQL, erro e aviso, e prova de que falham | Aceita |
| D29 | Camada analytics: views recriadas dos arquivos e três camadas de prova | Aceita |
| D30 | Finalizações como view de eventos (`shot_events`) e M2/M3 sobre ela | Aceita |
| D31 | Passes como view de eventos (`pass_events`) e M4 sobre ela | Aceita |
| D32 | Passes progressivos (M5): a convenção mora em `pass_events` | Aceita |
| D33 | Conduções progressivas (M6) e parâmetros compartilhados da convenção | Aceita |
| D34 | Passes para a área (M7) | Aceita |
| D35 | xG acumulado (M8): `xg_timeline` com eixo de tempo real | Aceita |

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

## D24 — Escalações: ordem cronológica das posições e atributos dos jogadores

- **Contexto:** o Passo 6 carrega `players` e `lineups`. A exploração (Passo 2) mostrou que `positions` nem sempre vem em ordem cronológica (A1) e que alguns jogadores aparecem com grafias diferentes entre arquivos (A2). A carga real mostrou conflitos também no apelido (2 jogadores) e no país (1 jogador).
- **Decisão:**
  - **`is_starter`, `played` e `first_position`** são derivados da primeira posição **cronológica** do jogador (ordenação estável por período e relógio), nunca da primeira listada. `positions` fica inteiro no `lineups.extra`, na **ordem original da fonte**: nada é reordenado nem perdido.
  - **Atributos de `players` (decisão do autor, estendida):** para o nome, vale o valor mais frequente entre os arquivos. Estendi o mesmo critério ao apelido e ao país, em vez de inventar regras diferentes: **o valor mais frequente entre TODOS os arquivos de escalação do manifest (64)**, não só entre as partidas carregadas. Assim o valor gravado não muda quando o Passo 13 carregar as outras 61 partidas.
  - **Nulo não compete** com um valor real (um apelido que falta em alguns arquivos não apaga o que consta em outros). **Empate** fica com a ordem alfabética, o que torna o resultado determinístico e independente da ordem dos arquivos.
  - **Todo conflito é reportado como aviso** (jogador, atributo, contagens e valor gravado), nunca como erro: a regra já decidiu, e um erro bloquearia a carga por um defeito da fonte.
  - **Uma transação por partida** (`load_match`): `players` (upsert) + `DELETE` filtrado por `match_id` + `INSERT` de `lineups` + `loaded_at` do arquivo. Se uma partida falhar, as anteriores já estão gravadas (cada uma é atômica) e a falha é reportada.
  - **A escalação precisa ser coerente com a partida:** os dois times do arquivo devem ser o mandante e o visitante de `core.matches`, senão a carga é recusada.
- **Limitação conhecida:** Anass Zaroury (131037) joga pelo Marrocos, mas a fonte o lista com país "Marrocos" em 3 arquivos e "Bélgica" em 4, então a regra grava `Belgium` em `players.country_name`. É um defeito da fonte que a regra não corrige. **O time de um jogador em uma partida vem sempre de `lineups.team_id`**; `players.country_name` é informativo e nenhuma métrica do MVP o usa.
- **Alternativas:**
  - *Valor da primeira ou da última partida:* depende de qual partida foi carregada, e muda no Passo 13.
  - *Contar só as partidas carregadas:* o nome gravado mudaria quando mais partidas fossem carregadas.
  - *Tratar o conflito como erro:* bloquearia a carga por causa de um dado da fonte.
  - *Usar a ordem da fonte para a primeira posição:* erraria o `first_position` dos jogadores com `positions` fora de ordem.
- **Consequências:**
  - A decisão dos nomes lê os 64 arquivos de escalação (cada um com o hash conferido) a cada carga. Um arquivo adulterado, mesmo de uma partida que não seria carregada, aborta tudo antes de gravar.
  - `core.players` só tem os jogadores das partidas carregadas (153 com as 3 sentinelas), mas o nome de cada um já é o definitivo.

## D25 — Eventos: o que sai do `extra`, tempo exato e carga na transação da partida

- **Contexto:** o Passo 7 carrega `core.events`, a tabela de maior volume (234.637 linhas na Copa inteira). A regra do `extra` (D07) precisa de uma lista exata do que sai, e algumas colunas exigem cuidado com tipos.
- **Decisão:**
  - **O que sai do `extra` dos eventos:** (1) o que virou coluna; (2) os **nomes** `team.name`, `player.name` e `possession_team.name`, porque as chaves estrangeiras já os representam em `core.teams` e `core.players` e eles se repetiriam em cada evento; (3) os objetos `shot`, `pass`, `carry` e `substitution`, que vão para as tabelas próprias no Passo 8; (4) `foul_committed.card` e `bad_behaviour.card`, com a poda do objeto pai quando só tinha o cartão. **Ficam** os ids de domínio (`type.id`, `position.id`, `play_pattern.id`), `related_events`, `tactics`, as flags e os objetos dos tipos sem tabela. Isso refina a lista do dicionário, que citava só `type.id`.
  - **Tempo exato:** `timestamp` ("00:02:16.985") vira `INTERVAL` por aritmética inteira sobre a fração, nunca por `float`, para `.001` continuar sendo 1 milissegundo.
  - **Ausência com significado:** `duration` ausente vira `NULL` (só em `Ball Receipt*`), e `0.0` é mantido como valor; `under_pressure` ausente vira `false`; `location` ausente vira `x` e `y` nulos juntos.
  - **Faixas conferidas na transformação, com o id do evento** (`period` 1 a 5, `second` 0 a 59, `x` 0 a 120, `y` 0 a 80). As `CHECK` do banco continuam como segunda barreira, mas elas não dizem *qual* evento falhou, o que faria falta em 234 mil linhas.
  - **Eventos entram na mesma transação das escalações** (`load_match`): `DELETE` filtrado por `match_id` em `lineups` e em `events`, depois os `INSERT`s. Se qualquer passo falhar, a partida inteira volta atrás: um teste faz o `INSERT` dos eventos falhar (jogador inexistente) e confere que as escalações e os `players` também foram desfeitos.
  - **Os times dos eventos (`team` e `possession_team`) devem ser os da partida**, senão a carga é recusada.
  - **Um arquivo de eventos vazio é erro:** uma partida real sempre tem eventos.
- **Alternativas:**
  - *Manter os nomes no `extra`:* cerca de 60 bytes a mais por evento, sem informação nova.
  - *Descartar também os ids de domínio:* ganharia pouco espaço e perderia informação de forma irreversível.
  - *`INTERVAL` via `float`:* arredondaria os milissegundos em alguns casos.
- **Medição (não é meta, é ponto de partida):** 11.444 eventos (3 partidas) são carregados em cerca de 3,6 s com o `executemany` do psycopg 3, já incluindo as outras etapas do `load`. A regra do `extra` custa 0,036 ms por evento. Projeção linear para os 234.637 eventos: cerca de 1 minuto. **Só otimizar (por exemplo com `COPY`) se a medição do Passo 13 mostrar necessidade.** O `core.events` ocupa cerca de 10 MB para 11 mil linhas, com índices.
- **Consequências:**
  - Entre os Passos 7 e 8, os objetos `shot`, `pass`, `carry` e `substitution` ainda não estão em nenhuma tabela do banco (continuam nos JSONs brutos). É um estado intermediário esperado.
  - O `card.id` e o `substitution.replacement.name` não terão onde ficar no Passo 8, porque `cards` e `substitutions` não têm `extra`. São ids e nomes de domínio deriváveis dos outros campos.

## D26 — Autorização permanente do autor para commitar e avançar de passo

- **Contexto:** até o Passo 7, cada commit e cada avanço de passo dependiam de uma autorização do autor (D18). Ao fim do Passo 7 o autor concedeu uma autorização permanente.
- **Decisão (do autor):**
  - O assistente **faz os commits** de cada passo, sem consultar antes, e **sempre mostra a evidência** de que ocorreram (`git status` e `git log` logo depois).
  - O assistente **segue para os passos seguintes** do plano sem pedir autorização a cada um.
- **Limites que continuam valendo:**
  - Nada de `push`, `amend`, `squash`, `reset --hard` ou outra forma de reescrever o histórico.
  - Cada commit contém só os arquivos do seu passo, com mensagem descritiva, e só é feito depois de a suíte de testes passar.
  - Nenhuma ação destrutiva no ambiente do autor nem no PostgreSQL (D17). O único `DELETE` do projeto continua sendo o da carga por partida, filtrado por `match_id` (D06).
  - Senhas nunca aparecem em saída, em log nem em commit (D22).
  - Ações que só o autor pode fazer (por exemplo, criar um banco como superusuário) continuam com o autor.
  - **Decisões que mudam o que a spec aprovou** continuam sendo registradas em `decisions.md` e destacadas no resumo ao autor, para que ele possa revê-las. Avançar sem consultar não é decidir em silêncio.
- **Alternativas:** manter a consulta a cada passo (mais lento, com o mesmo resultado quando tudo passa).
- **Consequências:** o histórico do Git passa a ser escrito pelo assistente, mas cada commit é revisável a qualquer momento (`git show`, `git revert`), e o autor pode revogar esta decisão quando quiser.

## D27 — Eventos especializados: nada se perde em silêncio

- **Contexto:** o Passo 8 move os objetos `shot`, `pass`, `carry` e `substitution`, e os cartões, de `events.extra` (D25) para as tabelas próprias. Três dessas tabelas (`carries`, `cards`, `substitutions`) não têm `extra`. Sem cuidado, uma chave nova da fonte, ou um objeto no evento errado, sumiria sem aviso.
- **Decisão:**
  - **Uma tabela por tipo, ligada ao evento pelo `event_id`**, na mesma transação da partida (D06), depois de `events` (cada linha aponta para um evento). Recarregar apaga os eventos da partida e as tabelas filhas saem em cascata.
  - **Falhar em vez de perder.** Em `carries`, `cards` e `substitutions`, qualquer chave que o modelo não guarda faz a transformação falhar, com o id do evento. Em `shots` e `passes` a sobra vai para o `extra` da tabela.
  - **Consistência tipo e objeto, nos dois sentidos:** um objeto `shot`, `pass`, `carry` ou `substitution` em um evento de outro tipo é erro, e um evento do tipo sem o seu objeto também. Isso fecha o buraco aberto pelo D25, em que o objeto já não fica no `events.extra`.
  - **`is_complete` é a ausência de `outcome`**, e o banco a reforça com a `CHECK` `is_complete = (outcome IS NULL)`. `pass_type` nulo é passe regular.
  - **`recipient.name` não é guardado** (já está em `core.players`, e todo destinatário das 64 partidas está nas escalações). O objeto `technique` do passe fica inteiro no `extra`.
  - **`end_z` é nulo exatamente nos chutes sem altura** (`Blocked` e `Wayward`, que só trazem x e y).
  - **`key_pass_id` só pode apontar para um evento do mesmo arquivo** (verificado na transformação; no banco a FK é adiada, D22).
  - **O xG vem do StatsBomb**, é validado entre 0 e 1 com o id do evento, e o de todos os 12 pênaltis das sentinelas é 0,7835.
  - **Os cartões dos eventos e os das escalações são conferidos entre si** (partida, jogador e tipo). Nas 3 sentinelas os 14 batem.
- **Alternativas:** *guardar o objeto bruto em colunas `extra` também nas três tabelas pequenas* (mais colunas por uma informação derivável); *ignorar chaves novas* (perda silenciosa, o que o projeto não admite).
- **Consequências:**
  - `card.id`, `substitution.outcome.id` e `replacement.name` não são guardados. Se um dia a fonte trouxer algo novo nesses objetos, a carga para e a decisão passa a ser do autor.
  - Medição: 3 partidas (11.444 eventos e 6.002 linhas especializadas) carregam em cerca de 6 s. Projeção linear para as 64 partidas: menos de 2 minutos. Sem necessidade de otimizar por ora.

## D28 — Checks de qualidade: arquivos SQL, erro e aviso, e prova de que falham

- **Contexto:** o plano diz que "um check que nunca falha é um check errado". O Passo 9 transforma as regras da spec (seção 11) em consultas executáveis e precisa provar que cada uma enxerga o defeito que deveria.
- **Decisão:**
  - **Um check é um arquivo `sql/checks/CNN_nome.sql`** com cabeçalho (`-- level: error|warning`, `-- title: …`) e **uma consulta que devolve as linhas problemáticas**: nenhuma linha = limpo. O nome e o nível ficam junto da regra, e o executor não conhece nenhum check em particular.
  - **Erro derruba, aviso não.** `check` termina com código 1 se um check de nível `error` tiver linhas; um `warning` só é reportado. O `all` (ingest, init-db, load, check) para no primeiro passo que falhar.
  - **Os checks só leem** (um teste proíbe `INSERT`, `UPDATE`, `DELETE`, `DROP`…) e **podem ler JSONB**: não são o schema `analytics`. O contrato de camadas (D05) é verificado por um teste que varre `sql/analytics/` atrás de operadores e funções JSON e da coluna `extra`, e o próprio verificador é testado com casos que devem e que não devem ser pegos.
  - **C01 a C10 em SQL; C11 em Python**, porque compara o nome do jogador entre os arquivos brutos de escalação, que não estão no banco. O C11 só cobre o **nome** (a spec); apelido e país divergentes já saem como aviso na carga (D24).
  - **Escopo dos checks:** o C01 só compara partidas cujo arquivo de eventos consta como carregado; o C02 e o C09 só olham partidas que têm eventos carregados; o C05 confere contagem **e** tipo (uma linha em `shots` apontando para um evento `Pass` passaria numa contagem simples); o C02 não conta a disputa de pênaltis e conta o gol contra para o time beneficiado.
  - **A prova de que falham:** os testes de integração montam um "mundo coerente" mínimo em que todos os checks passam e injetam um defeito por vez, dentro de uma transação desfeita no fim. Quando o defeito é algo que uma `CHECK` do banco já impede (coordenadas, xG), a restrição é removida **dentro da transação**, e o check mostra ser a segunda barreira.
- **Desvio do plano:** o plano previa os arquivos `events_corrupted.json` e `matches_corrupted.json`. Corromper o estado do banco com SQL é mais direto e mais preciso (cada teste diz exatamente o que foi quebrado), e dispensa duas fixtures grandes.
- **Resultado nos dados reais (3 sentinelas):** **0 erros e 1 aviso** (o C11, com os 4 jogadores de nome divergente já conhecidos). A amostra parcial dos testes, por outro lado, é **rejeitada** pelo `all`: o placar (C02) e os 11 titulares (C07) não fecham com 22 de 4.407 eventos e 9 jogadores, como devem.
- **Consequências:** os checks viram o critério de aceite da carga das 64 partidas (Passo 13). O `check` roda no banco principal configurado (`databases.main`) e, sem os arquivos brutos, pula o C11 e avisa.

## D29 — Camada analytics: views recriadas dos arquivos e três camadas de prova

- **Contexto:** o Passo 10 cria as 8 métricas como views SQL em `sql/analytics/`. O `init-db` só conhecia o DDL do `core`, e é preciso decidir como as views são aplicadas e como provar que cada métrica está certa.
- **Decisão:**
  - **O `init-db` apaga as views do schema `analytics` e as recria dos arquivos**, em ordem de nome (`10_…`, `20_…`), numa única transação. Views não guardam dados, então isso é seguro. A política evita o erro do `CREATE OR REPLACE VIEW` quando as colunas mudam e faz o banco refletir exatamente os arquivos (uma view removida do repositório some do banco). Se o schema tiver uma **tabela**, a operação é recusada antes de apagar qualquer coisa (contrato: só views). Pasta ausente não faz nada, e nunca apaga as views por causa disso.
  - **Os arquivos de `analytics` só podem conter** `CREATE VIEW analytics.x` e `COMMENT ON VIEW` (um teste confere cada arquivo). Nenhum operador, função JSON nem a coluna `extra` (D05).
  - **Nomes de arquivo `NN_nome.sql`** e dependências respeitadas pela ordem. Cada passo do plano **acrescenta colunas no fim** das views `team_match_stats` e `player_match_stats`: as colunas anteriores não mudam.
  - **Três camadas de prova por métrica**, como o plano pede: (1) **dados sintéticos** com fronteiras exatas, montados por um construtor (`World`, em `tests/integration/conftest.py`) dentro de uma transação desfeita; (2) a **referência da final**, calculada no Passo 2 por um notebook independente e conferida nos dados reais; (3) **invariantes** (por exemplo, Σ gols dos jogadores + gols contra = gols do time).
  - **Os testes de referência só leem o banco principal:** aplicam as views numa transação que é desfeita no fim, então nada muda no banco do autor. Sem a final carregada (4.407 eventos), são pulados com o motivo.
  - **Pares (partida, time) e (partida, jogador) só existem para partidas com eventos carregados.** O `match_summary` cobre todas as partidas e traz `NULL` na reconstrução quando não há eventos.
  - **Zero e `NULL` têm significados diferentes**, e as views os respeitam: contagens sem ocorrência são 0; taxas com denominador 0 são `NULL`; `penaltis_disputa` é `NULL` quando não houve disputa e 0 quando houve e nenhum pênalti foi convertido.
- **Alternativas:** *`CREATE OR REPLACE VIEW` com migrações* (mais passos manuais para views que não têm dados); *views materializadas* (dados para manter em dia, sem necessidade neste volume); *funções SQL para a distância e a área* (o schema passa a ter outros objetos além de views; preferi expressões inline com uma CTE `params`).
- **Consequências:** mudar uma métrica é mudar um arquivo SQL e rodar `init-db`; nenhum dado é reprocessado (D15).

## D30 — Finalizações como view de eventos (`shot_events`) e M2/M3 sobre ela

- **Contexto:** M2 e M3 agregam finalizações por time e por jogador, e o mapa de finalizações (Passo 12) precisa das mesmas finalizações uma a uma. Duas fontes de regra (uma para a agregação, outra para o mapa) poderiam divergir.
- **Decisão:**
  - `analytics.shot_events` (arquivo `05_shot_events.sql`, número menor que o das views de estatísticas, que dependem dela) guarda **uma linha por finalização**, inclusive as da disputa, com as marcações `is_goal`, `is_no_alvo`, `is_penalty` e `is_shootout`. **A regra "no alvo" (Goal, Saved, Saved to Post) e a de pênalti existem só ali**; `team_match_stats` e `player_match_stats` apenas agregam as marcações.
  - As colunas novas ficam no fim das duas views de estatísticas: `finalizacoes`, `finalizacoes_no_alvo`, `xg`, `npxg`, `finalizacoes_sem_penalti`, `npxg_por_finalizacao_sem_penalti`. Todas excluem o período 5 (D08).
  - **Numerador e denominador da taxa excluem os mesmos eventos:** `npxg` e `finalizacoes_sem_penalti` ignoram todo pênalti (`shot_type = 'Penalty'`), em jogo ou não. Sem finalização sem pênalti a taxa é `NULL`.
  - O gol contra não é finalização: não entra em M2, M3 nem nas contagens por jogador (continua só em `gols`, M1).
- **Alternativas:** *repetir a regra "no alvo" em cada view* (risco de divergência); *agregar direto de `core.shots`* (o mapa teria de reimplementar a regra).
- **Validação:** 20 testes sintéticos (fronteiras de cada resultado, pênalti em jogo, disputa, taxa `NULL`, Σ jogadores = time), a referência da final (Argentina 20/10, xG 2,7583, npxG 1,9748, taxa 0,1039; França 10/5, 2,2726, 0,7056, 0,0882) e 8 mutações na SQL, todas detectadas pelos testes.

## D31 — Passes como view de eventos (`pass_events`) e M4 sobre ela

- **Contexto:** M4 (e, adiante, M5 e M7) agregam passes, e o mapa de passes (Passo 12) precisa dos mesmos passes um a um. Mesma lógica de D30.
- **Decisão:**
  - `analytics.pass_events` (arquivo `06_pass_events.sql`) tem **uma linha por passe**, com `is_jogo_corrido` (pass_type nulo, `Recovery` ou `Interception`) e `is_tentado` (período 1 a 4, não é `Throw-in`, resultado fora de `Unknown` e `Injury Clearance`). Os passos de M5 e M7 acrescentam colunas no fim.
  - `passes_completos` conta só passes **tentados** que são completos: um lateral completo (`Throw-in`) não é tentado, então não entra. Bola parada com o pé (escanteio, falta, tiro de meta, saída) é tentada, e impedimento (`Pass Offside`) é uma tentativa que falhou.
  - **`pct_acerto_passes` não é arredondado na view** (0 a 100, `double precision`, `NULL` sem passes tentados). O arredondamento a 1 casa de `docs/metrics.md` é de apresentação: arredondar na origem perderia precisão para quem agregar depois.
  - **Guarda nova nos arquivos de `analytics`:** nenhum pode conter o caractere `%`, nem em comentário, porque o driver (psycopg) o lê como início de parâmetro e a aplicação falha. Também há um teste de que cada view é definida em arquivo de número menor que os arquivos que a leem.
- **Validação:** 28 testes sintéticos (cada `pass_type` e cada `outcome`, período 5, Σ jogadores = time, percentual nulo), a referência da final (Argentina 661/538, 81,4; França 544/414, 76,1) e 11 mutações, todas detectadas.

## D32 — Passes progressivos (M5): a convenção mora em `pass_events`

- **Contexto:** M5 é a **convenção OddVision v1** (D09). A mesma regra alimenta a contagem por time e por jogador e, no Passo 12, o mapa de passes progressivos.
- **Decisão:**
  - `pass_events.is_progressivo` (coluna nova no fim) implementa a fórmula de `docs/metrics.md` com os dois parâmetros da view `analytics.convention_params` (`min_start_x = 48`, `min_gain_yd = 10`, arquivo `01_convention_params.sql`); `passes_progressivos` só conta a marcação. Mudar a convenção é mudar esses números num único lugar (a M6 lê os mesmos, D33).
  - **A fórmula governa os casos de borda:** um passe de dentro da área para dentro da área com ganho de pelo menos 10 jardas (por exemplo, de `x = 102` a `x = 120`) **é** progressivo, pelo critério de distância. O que a convenção exclui é a *entrada* na área quando o passe já começa dentro (um passe curto dentro da área não conta). O notebook de referência da final aplica a mesma fórmula, e os dois concordam (56 e 39).
  - Valores ausentes: se `x`/`y` de início faltarem, o passe não é progressivo (`COALESCE(..., false)`), nunca `NULL`.
  - As contagens de M4 passaram a usar `count(*) FILTER (...)` sobre todos os passes, para M4 e M5 compartilharem um agrupamento.
- **Validação:** 36 testes (fronteiras de ganho 9,99/10,00/10,01, de início 47,9/48,0/48,1, da área em `x = 102` e `y = 18`/`62` incluindo 101,99, 17,99 e 62,01; incompletos, bolas paradas, período 5; Σ jogadores = time; subconjunto dos completos de jogo corrido), a referência da final (Argentina 56, França 39) e 18 mutações (cada parâmetro, cada comparação, a geometria e as exclusões), todas detectadas. A inspeção visual de 20 passes, prevista em `docs/metrics.md`, fica para o mapa do Passo 12.

## D33 — Conduções progressivas (M6) e parâmetros compartilhados da convenção

- **Contexto:** M6 aplica "a mesma regra geométrica da M5" às conduções (D09). Se cada view tivesse os seus próprios números 48 e 10, as duas métricas poderiam divergir sem que ninguém notasse.
- **Decisão:**
  - `analytics.convention_params` (`01_convention_params.sql`) é uma view de uma linha com `min_start_x` e `min_gain_yd`; `pass_events` e `carry_events` fazem `CROSS JOIN` com ela. Isto substitui a CTE `params` que a D32 descrevia dentro de `pass_events`.
  - `analytics.carry_events` (`07_carry_events.sql`) tem uma linha por `Carry` e `is_progressivo`: período 1 a 4, início em `x ≥ min_start_x` e (ganho ≥ `min_gain_yd` OU entrada na área). **Não há filtro de "completa"**: a condução não tem resultado na fonte.
  - `conducoes_progressivas` (time e jogador) conta a marcação. Os casos de borda seguem os da M5 (D32): de dentro da área para dentro com ganho de 10 jardas ou mais é progressiva.
- **Validação (M6):** 27 testes (as mesmas fronteiras da M5 aplicadas a `Carry`; Σ jogadores = time; condução e passe não se misturam; um teste que garante que passe e condução com a mesma geometria recebem a mesma marcação), a referência da final (Argentina 30, França 31) e 18 mutações (parâmetros, comparações, geometria, período, agregações e duas da M5), todas detectadas.

## D34 — Passes para a área (M7)

- **Contexto:** M7 é uma convenção **geométrica** (a área do campo do StatsBomb), diferente de M5 e M6, que são limiares de progressão.
- **Decisão:** `pass_events.is_passe_para_area` (coluna nova no fim) marca o passe completo, de jogo corrido, período 1 a 4, que começa **fora** da área e termina **dentro** dela, com limites inclusivos (`x ≥ 102` e `18 ≤ y ≤ 62`). **M7 não herda os limiares da M5**: um passe de `x = 30` até a área é "para a área" mesmo sem ser progressivo (o teste confere os dois valores). Começar ao lado da área (`y` fora de 18 a 62) e terminar dentro é entrada; começar em `x = 102` não é. Dados de início ausentes não geram marcação (`COALESCE(..., false)`). `passes_para_area` conta a marcação, por time e por jogador.
- **Validação:** 37 testes (fronteiras `x = 101,99/102,00/102,01`, `y = 17,99/18/62/62,01` no fim e no início; incompletos, bolas paradas, período 5; Σ jogadores = time; subconjunto dos completos de jogo corrido), a referência da final (Argentina 7, França 3) e 15 mutações (cada fronteira, início e fim, cada exclusão, um limiar herdado por engano), todas detectadas.

## D35 — xG acumulado (M8): `xg_timeline` com eixo de tempo real

- **Contexto:** M8 é uma soma acumulada (🟨 cálculo) cujo eixo de tempo é uma decisão de apresentação (`docs/metrics.md`). A soma e o eixo são calculados na view para que o gráfico (Passo 12) só desenhe.
- **Decisão:** `analytics.xg_timeline` (`40_xg_timeline.sql`) tem uma linha por finalização em tempo válido (pênaltis incluídos, período 5 fora), lendo `analytics.shot_events`:
  - `xg_acumulado` é `SUM(statsbomb_xg) OVER (PARTITION BY partida, time ORDER BY period, idx)`; a ordem nunca usa `minute`.
  - `tempo_decorrido_s` = soma da duração real dos períodos anteriores + `ts_in_period`. A duração de um período vem do `Half End` (os dois, um por time, têm o mesmo horário, e a view usa o máximo, então não soma duas vezes). **Sem `Half End`, vale o último evento do período**: o eixo continua correto e sem sobreposição.
  - `minuto_futebol = minute + 1` e `rotulo` em estilo futebol (`23'`, `45+14'`), com limites 45, 90, 105 e 120.
  - Time sem finalizações não tem linhas e o ponto inicial (0, 0) é da apresentação, como na especificação.
- **Mutante equivalente conhecido:** retirar só o `WHERE NOT is_shootout` não muda o resultado, porque o `JOIN` com as durações (só períodos 1 a 4) já descarta o período 5. As duas proteções são mantidas de propósito (defesa em profundidade) e o teste falha quando as duas são retiradas.
- **Validação:** 25 testes sintéticos (soma por time, pênalti como degrau, disputa fora, ordem `(period, idx)` com minuto e `idx` invertidos, 1º tempo de 60 minutos, dois `Half End` contados uma vez, sem `Half End`, 14 rótulos nas fronteiras), a referência da final (último ponto = xG de M3: Argentina 2,7583 e França 2,2726; degraus de pênalti nos minutos 22, 79 e 117, rótulos 23', 80' e 118'; cada degrau de 0,7835), as invariantes em todas as partidas carregadas (último ponto = `xg` da M3; tempo crescente com `(period, idx)`) e Inglaterra x Irã (1º tempo longo sem sobreposição). 18 mutações: 16 detectadas de primeira; "ordenar só por `idx`" sobreviveu e levou ao teste de `idx` invertido entre períodos (agora detectada); a outra sobrevivente é o equivalente acima.
