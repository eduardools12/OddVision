# OddVision — Plano de Implementação do MVP

| Campo | Valor |
|---|---|
| Status | Aprovado em 2026-09-29 |
| Spec | [`../specs/2026-09-29-oddvision-mvp-design.md`](../specs/2026-09-29-oddvision-mvp-design.md) |
| Referências | [`../metrics.md`](../metrics.md) · [`../data_dictionary.md`](../data_dictionary.md) · [`../decisions.md`](../decisions.md) |
| Execução | Uma etapa por vez, nesta sessão, com explicação. Ao fim de cada etapa: pausa → o autor valida → o autor faz o commit manualmente |

---

## Regras globais (valem para todas as etapas)

- **Contrato por etapa (D16):** nenhuma etapa começa sem entrada, saída e validação definidas.
- **Camadas separadas:**
  - `raw` só é gravado pela ingestão.
  - `core` só é gravado pelo `load`.
  - `analytics` contém somente views e nunca lê JSONB (D05, D15).
- **Métricas progressivas:** são **convenção OddVision v1** (D09).
- **Validações independentes:** os valores esperados vêm de uma fonte diferente do código testado. Exemplos: o notebook do Passo 2 (Python puro), `Get-FileHash`, contagens feitas direto no JSON.
- **TDD** nos Passos 3 e 5–10: o teste falha antes da implementação.
- **Windows:** comandos na forma `.venv\Scripts\python.exe -m …`, sem ativar o venv.
- **Sem ações destrutivas:**
  - O único `DELETE` é o da carga por partida, filtrado por `match_id` (D06).
  - Remover schemas só acontece automaticamente no banco `oddvision_test`.
  - No banco `oddvision`, nunca sem autorização explícita do autor.
- **PostgreSQL (D17):** nada é reinstalado, reparado, removido, movido ou alterado sem autorização explícita.
- **Encoding:** arquivos abertos com `encoding="utf-8"`; bancos criados com `ENCODING 'UTF8'`.
- **Commits:** sempre manuais pelo autor (D18), e somente com os arquivos da etapa.
- **Fora do MVP:** Docker, dbt, Airflow, ML, Supabase e outras tecnologias não listadas na spec.

---

## Passo 0 — Ambiente

1. **Objetivo:** repositório Git próprio, venv com Python 3.13 e diagnóstico **somente leitura** do PostgreSQL.
2. **Pré-requisitos:** spec aprovada.
3. **Arquivos:** `.gitignore`; `docs/plans/2026-09-29-oddvision-mvp-plan.md`. O `.venv/` é criado, mas fica fora do Git.
4. **Comandos:**
   - Confirmar a pasta: `Get-Location`.
   - Git: `git init -b main`; `git rev-parse --show-toplevel`, que deve retornar exatamente `C:/Users/Eduardo/Documentos/Projetos/oddvision`.
   - Identidade: `git config user.name` e `git config user.email`. **Somente verificar.** Se algum estiver vazio ou incorreto, informar o autor e não alterar.
   - Python: `py -0p`; `py -3.13 -m venv .venv`; `.venv\Scripts\python.exe --version`.
   - Diagnóstico do PostgreSQL, **somente leitura**:
     - Executáveis (`psql.exe`, `postgres.exe`, `pg_ctl.exe`).
     - Serviço.
     - Registro do Windows.
     - Porta.
     - Processos.
     - Diretório de dados: `PG_VERSION`, subpastas de `base`, configuração, logs.
5. **Implementação:** nenhuma. Apenas `.gitignore`, venv e relatório.
6. **Aprendizado:**
   - Repositórios aninhados.
   - venv.
   - No PostgreSQL, binários, cluster (diretório de dados) e serviço são coisas separadas.
7. **Validação:**
   - Raiz do Git correta.
   - `git status` sem `.venv`.
   - Python 3.13.x no venv.
   - Relatório respondendo: onde estão os executáveis, se o servidor está instalado, se há serviço, versão, diretório de dados e bancos existentes.
8. **Problemas:**
   - Raiz do Git ainda em `C:/Users/Eduardo`: o `init` rodou fora da pasta.
   - `py -3.13` ausente.
   - Acesso negado ao diretório de dados: registrar, sem elevar permissões.
9. **Commit:** depois de a raiz estar correta. **Conteúdo exato:** `.gitignore`, os 4 documentos de `docs/` e este plano.
10. **Mensagem:** `docs: add MVP spec, metrics, data dictionary, decisions and implementation plan`

> **Portão do PostgreSQL (ação do autor):** a partir do diagnóstico, o autor decide o que fazer e executa por conta própria.
> **Validação do portão:** `psql --version` = 18.x; serviço `Running`; `select version()` responde.
> **O portão só bloqueia a partir do Passo 4.**

---

## Passo 1 — Esqueleto e dependências

1. **Objetivo:** pacote importável, dependências instaladas e fixadas, pytest rodando.
2. **Pré-requisitos:** Passo 0 commitado.
3. **Arquivos:**
   - `pyproject.toml`: metadados, `requires-python = ">=3.13,<3.14"`, layout `src/`, configuração do pytest.
   - `requirements.txt`: pandas, psycopg[binary], SQLAlchemy, streamlit, mplsoccer.
   - `requirements-dev.txt`: `-r requirements.txt`, pytest, ipykernel.
   - `README.md` (esqueleto com créditos ao StatsBomb).
   - `src/oddvision/__init__.py`, `tests/unit/test_smoke.py`
   - `docs/decisions.md`: acrescentar **D19**, justificando o `pyproject.toml`.
4. **Comandos:**
   - Conferir, via Context7 e PyPI, se há *wheels* `cp313-win_amd64`.
   - `… -m pip install --upgrade pip`
   - `… -m pip install -r requirements-dev.txt`
   - `… -m pip install -e .`
   - `… -m pip freeze`
   - `… -m pytest`
5. **Implementação:** teste *smoke* que importa `oddvision` e as 5 bibliotecas; versões com `==` nas dependências diretas.
6. **Aprendizado:** layout `src/`; instalação editável; dependências diretas vs transitivas; por que fixar versões.
7. **Validação:** `pytest` passa; `git status` não mostra `.venv`; `pip freeze` lista as versões fixadas.
8. **Problemas:**
   - Falta de *wheel* para 3.13: escolher outra versão da biblioteca, não trocar a versão do Python.
   - Conflitos de versão.
   - `import` falha no pytest: a instalação editável não foi feita.
9. **Commit:** `pytest` verde.
10. **Mensagem:** `build: add project skeleton, pinned dependencies and smoke test`

---

## Passo 2 — Exploração guiada dos dados reais

1. **Objetivo:**
   - Fixar o commit da fonte.
   - Confirmar os **7 caminhos ⚠️** do dicionário.
   - Congelar os valores de referência.
   - Escolher 3 partidas-sentinela.
2. **Pré-requisitos:** Passo 1 commitado.
3. **Arquivos:**
   - Criados: `notebooks/01_exploracao.ipynb`, `docs/data_notes.md` e `tests/fixtures/reference_final_3869685.json` (valores copiados à mão da saída revisada do notebook).
   - Alterados: `docs/data_dictionary.md` (remover os ⚠️ com evidência) e `docs/metrics.md` (reconfirmar os exemplos no commit fixado).
4. **Comandos:**
   - Obter o SHA do commit atual de `statsbomb/open-data` pela API do GitHub (leitura).
   - Executar o notebook no VS Code com o kernel `.venv`.
   - Validar com "Restart & Run All".
   - Usar a skill `data:explore-data`.
5. **Implementação:** notebook em **Python puro** (json + collections), que lê os arquivos **em memória**, a partir de URLs fixadas no commit. Seções:
   - Estrutura dos arquivos.
   - matches e lineups (ordem de `positions` e critério de titular).
   - Eventos: chaves, tipos, períodos, nulos.
   - `shot.end_location` (define o `end_z`).
   - `pass.through_ball` vs `pass.technique`.
   - Cartões (`foul_committed.card`, `bad_behaviour.card`) comparados com `lineups.cards`.
   - `substitution.replacement` e `substitution.outcome`.
   - Eventos `Half End` por período.
   - Referências da final.
   - Escolha das sentinelas **pelos dados**: a final (disputa e prorrogação), uma partida com gol contra e a partida com o 1º tempo mais longo.
6. **Aprendizado:** JSON aninhado; ausência de campo com significado; sistema de coordenadas; exploração independente como oráculo de testes.
7. **Validação:**
   - Roda do início ao fim.
   - Reproduz 4.407 eventos, 38 finalizações e 8 no período 5 (ou documenta a diferença no commit fixado).
   - Os 7 ⚠️ resolvidos com evidência. Se algum caminho não existir, **corrigir a documentação, não inventar**.
   - JSON de referência com M1–M8.
   - Sentinelas registradas.
8. **Problemas:**
   - Acentos corrompidos: verificar o encoding.
   - Limite da API do GitHub: só precisamos de 1 requisição.
   - Números diferentes: documentar, não "ajustar".
9. **Commit:** "Restart & Run All" limpo e documentos atualizados.
10. **Mensagem:** `docs: explore StatsBomb WC2022 data, pin source commit and confirm JSON paths`

---

## Passo 3 — Ingestão bruta (P1)

1. **Objetivo:** baixar exatamente **130 arquivos**, sem alteração, e gerar o manifest.
2. **Pré-requisitos:** Passo 2 commitado.
3. **Arquivos:**
   - `config/selection.toml` (competição 43, temporada 106, commit, `load_match_ids` com as sentinelas).
   - `src/oddvision/config.py`, `src/oddvision/ingest.py`
   - `src/oddvision/pipeline.py` (subcomando `ingest`).
   - `tests/unit/test_config.py`, `tests/unit/test_ingest.py`
4. **Comandos:**
   - `… -m pytest tests/unit`
   - `… -m oddvision.pipeline ingest`, **duas vezes**.
   - `(Get-ChildItem data\raw\statsbomb -Recurse -File -Filter *.json).Count`
   - `Get-FileHash -Algorithm SHA256` em 3 arquivos, comparando com o manifest.
5. **Implementação:**
   - Primeiro competitions + matches; os `match_id` são lidos do arquivo de matches; depois os 64 events e os 64 lineups.
   - `urllib` com timeout e 3 tentativas.
   - Gravação atômica (`.part` → renomear).
   - Arquivo existente com hash igual ao manifest: pula. Hash diferente: **erro**.
   - Manifest com caminhos no formato POSIX.
   - Testes com `tmp_path` e função de download falsa (sem rede).
6. **Aprendizado:** idempotência; gravação atômica; hash como prova de integridade; injeção de dependência.
7. **Validação:**
   - 130 arquivos.
   - 2ª execução: "0 baixados, 130 existentes".
   - `Get-FileHash` confere com o manifest.
   - Manifest com 130 linhas; soma de `record_count` dos events = notebook.
   - `git status` sem `data/`.
8. **Problemas:** falha de rede (sobra um `.part`); proxy; barras invertidas nos caminhos.
9. **Commit:** testes verdes + 130 arquivos validados.
10. **Mensagem:** `feat(ingest): download pinned StatsBomb WC2022 raw files with manifest`

---

## Passo 4 — DDL e banco

1. **Objetivo:** bancos `oddvision` e `oddvision_test` com os schemas `core` e `analytics` e as 12 tabelas.
2. **Pré-requisitos:** portão do PostgreSQL aprovado; Passo 3 commitado.
3. **Arquivos:**
   - `sql/ddl/001_schemas.sql`, `sql/ddl/002_core_tables.sql`
   - `config/database.example.toml`
   - `src/oddvision/db.py`
   - `pipeline.py` (subcomando `init-db`).
   - `tests/integration/conftest.py` (recria os schemas **somente** no `oddvision_test`).
   - `tests/integration/test_ddl.py`
4. **Comandos:**
   - **Executados pelo autor no `psql`** (ele digita a senha):
     - Criar a role `oddvision_app` sem superusuário.
     - Criar `oddvision` e `oddvision_test` com `OWNER oddvision_app ENCODING 'UTF8' TEMPLATE template0`.
     - O autor preenche o `config/database.toml`.
   - Depois:
     - `init-db`, duas vezes.
     - `\dn`, `\dt core.*`, `SHOW server_encoding`.
     - `pytest tests/integration/test_ddl.py`
5. **Implementação:** DDL igual ao `data_dictionary.md` (tipos, PK, FK, `ON DELETE CASCADE`, CHECK); `IF NOT EXISTS`; o `db.py` nunca registra a senha em log.
6. **Aprendizado:** role vs banco vs schema; privilégio mínimo; constraints; `template0` e encoding.
7. **Validação:** 2 schemas e 12 tabelas; `server_encoding = UTF8`; `init-db` repetível; teste confere PK, FK e CHECK via catálogo.
8. **Problemas:**
   - Falha de autenticação: verificar o TOML e o `pg_hba.conf`.
   - Erro de encoding ou *locale*: usar `template0`.
   - *Code page* no `psql` do Windows: `chcp 65001`.
   - Permissão negada ao criar o schema.
9. **Commit:** DDL aplicado + teste verde.
10. **Mensagem:** `feat(db): create core and analytics schemas with core tables`

---

## Passo 5 — Partidas e dimensões (P2)

1. **Objetivo:** carregar `competitions`, `teams`, `matches` e `ingestion_log`.
2. **Pré-requisitos:** Passo 4 commitado.
3. **Arquivos:**
   - `src/oddvision/transform/__init__.py`
   - `transform/common.py` (`extract_extra`: regra do D07)
   - `transform/matches.py`
   - `src/oddvision/load.py`
   - `pipeline.py` (subcomando `load`).
   - `tests/fixtures/matches_sample.json` (escrito à mão, 2 partidas).
   - `tests/unit/test_extract_extra.py`, `tests/unit/test_transform_matches.py`, `tests/integration/test_load_matches.py`
4. **Comandos:** `pytest` (vermelho → verde); `load`; SQL de validação.
5. **Implementação:** transformações puras JSON → DataFrame; upsert em competitions, teams e matches; `ingestion_log` carregado a partir do manifest.
6. **Aprendizado:** função pura vs efeito colateral; upsert; granularidade.
7. **Validação:**
   - 1 competição, 64 partidas, 32 times, 130 linhas no `ingestion_log`.
   - A final confere com o JSON.
   - `load` duas vezes produz as mesmas contagens.
   - O `extra` não duplica colunas mapeadas.
8. **Problemas:** ordem de carga × FK; `kick_off` com milissegundos; `NaN` em colunas `NOT NULL`.
9. **Commit:** testes verdes + contagens validadas.
10. **Mensagem:** `feat(core): load competitions, teams, matches and ingestion log`

---

## Passo 6 — Escalações (P3)

1. **Objetivo:** carregar `players` e `lineups` das 3 sentinelas.
2. **Pré-requisitos:** Passo 5 commitado; critério de titular confirmado no Passo 2.
3. **Arquivos:**
   - `transform/lineups.py`
   - `load.py` (`load_match`, com transação por partida).
   - `tests/fixtures/lineups_sample.json` (titular, reserva que entrou, reserva que não entrou).
   - `tests/unit/test_transform_lineups.py`, `tests/integration/test_load_lineups.py`
4. **Comandos:** `pytest`; `load`; SQL de validação.
5. **Implementação:**
   - `is_starter` e `played` pela regra confirmada no Passo 2.
   - Upsert de players antes das lineups.
   - `DELETE` + `INSERT` das lineups em `engine.begin()`.
   - Aviso quando o mesmo jogador tem nomes divergentes.
6. **Aprendizado:** transação; upsert vs substituição; derivação estrutural vs convenção.
7. **Validação:**
   - 11 titulares por time.
   - Linhas = elementos `lineup` contados diretamente no JSON.
   - Constraint `NOT is_starter OR played`.
   - Acentos corretos.
   - Uma falha simulada não deixa linhas parciais.
8. **Problemas:** *code page* do console; partida com ≠ 11 titulares (investigar a regra antes de "corrigir").
9. **Commit:** testes verdes + validação nas sentinelas.
10. **Mensagem:** `feat(core): load players and lineups per match in a transaction`

---

## Passo 7 — Eventos (P4)

1. **Objetivo:** carregar `core.events` das sentinelas.
2. **Pré-requisitos:** Passo 6 commitado.
3. **Arquivos:**
   - `transform/events.py` (`parse_events`)
   - `load.py` (eventos na mesma transação de `load_match`).
   - `tests/fixtures/events_sample.json`: cerca de 15 eventos escritos à mão, cobrindo evento sem `location`, sem `player`, com e sem `under_pressure`, período 5, `Ball Receipt*` e um tipo sem tabela própria.
   - `tests/unit/test_transform_events.py`, `tests/integration/test_load_events.py`
4. **Comandos:** `pytest`; `load`; SQL de validação.
5. **Implementação:**
   - `timestamp` → `INTERVAL`, `id` → `UUID`, `location` → `x`/`y`.
   - `under_pressure` ausente → `false`.
   - `extra` sem os objetos que vão para tabelas próprias.
   - `to_sql` com os tipos JSONB, UUID e Interval (otimização só no Passo 13, se medida).
6. **Aprendizado:** tipagem; nulo esperado vs nulo erro; ordenação por `idx`.
7. **Validação:**
   - Eventos por partida = manifest (a final tem 4.407).
   - Contagem por `type_name` = notebook.
   - IDs únicos.
   - Times ∈ {mandante, visitante}.
   - Coordenadas no campo.
8. **Problemas:**
   - FK de `player_id`: investigar, não remover a FK.
   - Formato do `timestamp`.
   - Lentidão: medir e anotar.
9. **Commit:** testes verdes + validações.
10. **Mensagem:** `feat(core): load match events with typed columns and extra jsonb`

---

## Passo 8 — Eventos específicos (P5)

1. **Objetivo:** carregar `shots`, `passes`, `carries`, `cards` e `substitutions`.
2. **Pré-requisitos:** Passo 7 commitado; caminhos confirmados no Passo 2.
3. **Arquivos:**
   - `transform/events.py`: parsers de shots, passes, carries, cards e substitutions.
   - `load.py` (`load_match` completo).
   - Casos novos em `events_sample.json`.
   - `tests/unit/test_transform_specific.py`, `tests/integration/test_load_specific.py`
4. **Comandos:** `pytest`; `load`; SQL de validação.
5. **Implementação:**
   - `is_complete` = ausência de `outcome`.
   - Flags de passe ausentes → `false`.
   - `end_z`, cartões e substituições **conforme o Passo 2**.
   - `extra` de cada tabela = objeto − chaves mapeadas.
   - `CASCADE` a partir de `events`.
6. **Aprendizado:** modelagem 1:1 (supertipo e subtipo); `ON DELETE CASCADE`; conciliação entre fontes.
7. **Validação:**
   - Contagem de cada tabela = eventos do tipo.
   - Domínios = notebook.
   - CHECK de `is_complete`.
   - xG de pênalti = 0,7835.
   - Cartões conferem com as escalações.
   - `events.extra` sem `shot`, `pass` e `carry`.
8. **Problemas:** cartões divergentes (registrar como aviso e investigar); violação do CHECK de `is_complete`.
9. **Commit:** testes verdes + validações.
10. **Mensagem:** `feat(core): load shots, passes, carries, cards and substitutions`

---

## Passo 9 — Qualidade e testes (P6)

1. **Objetivo:** checks C01–C11 executáveis e testados.
2. **Pré-requisitos:** Passo 8 commitado.
3. **Arquivos:**
   - `sql/checks/C01_*.sql` … `C11_*.sql` (cabeçalho com nível e regra).
   - `src/oddvision/checks.py`
   - `pipeline.py` (subcomandos `check` e `all`).
   - `tests/fixtures/events_corrupted.json`, `tests/fixtures/matches_corrupted.json`
   - `tests/integration/test_checks.py`
   - `tests/unit/test_layer_contract.py`
4. **Comandos:** `pytest`; `… -m oddvision.pipeline check`; `echo $LASTEXITCODE`.
5. **Implementação:** runner com relatório e código de saída ≠ 0 em caso de erro; domínios do C04 = valores observados no Passo 2; revisão com `data:sql-queries`.
6. **Aprendizado:** constraint vs check; erro vs aviso; testar checks com dados ruins; código de saída.
7. **Validação:**
   - 0 erros nos dados reais.
   - Cada fixture corrompida derruba o check correspondente.
   - `$LASTEXITCODE` ≠ 0 quando há erro.
   - Teste de contrato de camadas verde.
8. **Problemas:** check que nunca falha; falsos positivos em C09 ou C11.
9. **Commit:** tudo verde, e as fixtures corrompidas falhando como esperado.
10. **Mensagem:** `feat(quality): add data quality checks, runner and layer contract test`

---

## Passo 10 — Métricas (P7), uma por vez

**Estrutura comum aos subpassos:**

- **Pré-requisito:** o subpasso anterior commitado.
- **Arquivos:** `sql/analytics/NN_*.sql` (`CREATE OR REPLACE VIEW`, CTE `params`, comentário apontando para `metrics.md`), aplicados pelo `init-db`; `tests/integration/test_metric_Mx.py`.
- **Comandos:** `pytest`; `init-db`; consulta no `psql`.
- **Validação em três camadas:** fixture sintética de fronteira + referência da final + invariantes.
- **Problemas recorrentes:**
  - Divisão inteira: usar `::numeric` + `NULLIF`.
  - Fronteiras em ponto flutuante: usar coordenadas de distância exata (por exemplo, ao longo de `y = 40`).
  - Time sem eventos: `LEFT JOIN` + `COALESCE` para contagens; `NULL` para taxas.

| Sub | Implementação | Aprendizado | Validação específica | Mensagem de commit |
|---|---|---|---|---|
| 10.1 | M1: `match_summary`, gols por time e por jogador, `gols_contra_a_favor`, `penaltis_disputa` | `FILTER`; NULL vs 0 | Placar reconstruído = oficial; final 3–3 (4–2) | `feat(analytics): add M1 score and goals` |
| 10.2 | M2 e M3: `shot_events`, finalizações, no alvo, `xg`, `npxg`, taxa | Mapeamento de domínio; taxa coerente | `no_alvo ≤ finalizacoes`; `npxg ≤ xg`; referência | `feat(analytics): add M2 shots and M3 xG` |
| 10.3 | M4: passes e % | Exclusões explícitas | Conciliação por `outcome`; 81,4% / 76,1% | `feat(analytics): add M4 passes and accuracy` |
| 10.4 | M5: `pass_events` (`is_jogo_corrido`, `is_progressivo`) | Geometria em SQL; parâmetros | Fronteiras 9,99/10,00 e 47,9/48,0; área → área; 56/39 | `feat(analytics): add M5 progressive passes (OddVision v1)` |
| 10.5 | M6: `carry_events` (`is_progressiva`) | Consistência de regra | Mesmas fronteiras; 30/31 | `feat(analytics): add M6 progressive carries (OddVision v1)` |
| 10.6 | M7: `is_passe_para_area` | Pontos na linha | x = 102; y = 18/62; x = 101,99; 7/3 | `feat(analytics): add M7 passes into the box` |
| 10.7 | M8: `xg_timeline` (`SUM() OVER` por `(period, idx)`; duração do período = maior `Half End` do período) | Funções de janela; eixo de tempo | Último ponto = `xg`; monotônica; sentinela de 1º tempo longo | `feat(analytics): add M8 cumulative xG timeline` |
| 10.8 | `team_match_stats`, `player_match_stats`, `match_lineups`, `match_timeline` | Granularidades | Soma dos jogadores = time; contrato de camadas; revisão `data:validate-data` | `feat(analytics): add team/player stats, lineups and timeline views` |

---

## Passo 11 — Streamlit básico

1. **Objetivo:** página "Partida" com seletor, placar, escalações e tabela de finalizações.
2. **Pré-requisitos:** 10.8 commitado.
3. **Arquivos:**
   - `src/oddvision/app_queries.py` (consulta apenas `analytics`).
   - `app/Home.py` (créditos ao StatsBomb).
   - `app/pages/1_Partida.py`
   - `tests/integration/test_app_queries.py`
   - Opcional e fora do Git: `.claude/launch.json`.
4. **Comandos:** `pytest`; `.venv\Scripts\python.exe -m streamlit run app/Home.py`; preview no navegador interno.
5. **Implementação:**
   - `st.cache_data`.
   - Placar com a disputa separada.
   - Escalações.
   - Tabela de finalizações.
   - Rótulo "OddVision v1".
   - Documentação do Streamlit via Context7.
6. **Aprendizado:** separar consulta e apresentação; cache; o app não toca no `core`.
7. **Validação:**
   - Final: 3–3 (disputa 4–2); Messi 2, Di María 1, Mbappé 3; 11 titulares por lado.
   - As sentinelas abrem sem erro.
   - O app só consulta `analytics.`.
8. **Problemas:** porta 8501 ocupada; cache desatualizado; pasta `pages/` com nome errado.
9. **Commit:** validação visual + testes.
10. **Mensagem:** `feat(app): add match page with score, lineups and shots table`

---

## Passo 12 — Mapas e timeline

1. **Objetivo:** mapa de finalizações, mapa de passes, timeline de incidentes e gráfico da M8.
2. **Pré-requisitos:** Passo 11 commitado.
3. **Arquivos:**
   - `src/oddvision/viz/pitch.py` (`flip_for_display` pura + figuras).
   - `app/pages/1_Partida.py` (alterado).
   - `tests/unit/test_viz.py`
4. **Comandos:** `pytest`; `streamlit run`; preview. Documentação do `mplsoccer` via Context7.
5. **Implementação:**
   - Espelhamento do visitante (`120 − x`, `80 − y`) **na apresentação**; `analytics` mantém a perspectiva da fonte.
   - Filtros do mapa de passes.
   - Timeline de gols, cartões e substituições.
6. **Aprendizado:** sistemas de coordenadas; a transformação visual fica fora do `analytics`; codificação visual.
7. **Validação:**
   - Finalizações do mandante em `x ≥ 60` e do visitante em `x ≤ 60` após o espelhamento (teste numérico).
   - Último ponto = `xg`.
   - Degraus da final aos 23', 80' e 118'.
   - Sem sobreposição de períodos.
8. **Problemas:** eixo y invertido; figuras do matplotlib não fechadas.
9. **Commit:** validação visual + testes.
10. **Mensagem:** `feat(app): add shot map, pass map and xG timeline`

---

## Passo 13 — Escala para as 64 partidas + documentação final

1. **Objetivo:** pipeline completo nas 64 partidas, reprodutível do zero.
2. **Pré-requisitos:** Passo 12 commitado.
3. **Arquivos:**
   - `config/selection.toml` (todas as partidas).
   - Otimização COPY **somente se** a medição justificar.
   - `README.md` final.
   - `docs/metrics.md` (histórico) e `docs/decisions.md`.
4. **Comandos:**
   - `… -m oddvision.pipeline all`, cronometrado com `Measure-Command`.
   - Segunda execução para provar a idempotência (*snapshot* das contagens).
   - Pipeline em um banco vazio `oddvision_verify`, **criado pelo autor**.
   - `pytest`.
5. **Implementação:** carga das 64 partidas; README com arquitetura, execução, métricas, limitações, viés da amostra e créditos.
6. **Aprendizado:** medir antes de otimizar; reprodutibilidade; documentação como produto.
7. **Validação (= critérios de sucesso da spec, seção 15):**
   - 64 partidas; eventos = commit fixado.
   - Checks de erro verdes.
   - 2ª execução idêntica.
   - `oddvision_verify` = `oddvision`.
   - Testes verdes.
   - O app funciona em qualquer partida.
8. **Problemas:** partida isolada falhando (só ela é revertida; o log mostra o `match_id`); lentidão; valores novos de domínio (investigar e documentar).
9. **Commits:** dois. Primeiro a escala validada, depois a documentação.
10. **Mensagens:** `feat(pipeline): load all 64 World Cup 2022 matches` e `docs: finalize README and project documentation`

---

## Dependências entre etapas

| Etapa | Depende de |
|---|---|
| 1, 2, 3 | Passo 0. **Não dependem do PostgreSQL** |
| 3 | Passo 2 (commit fixado, sentinelas) |
| 4 | Portão do PostgreSQL + Passo 3 |
| 5 → 6 → 7 → 8 | Sequência estrita (FKs) |
| 9 | Passo 8 |
| 10.x | Passo 9 e o subpasso anterior |
| 11 | 10.8 |
| 12 | Passo 11 e 10.7 |
| 13 | Passo 12 (pode vir antes dos Passos 11 e 12) |

## Obrigatório vs adiável

- **Obrigatórias para o MVP:** todas as etapas, de 0 a 13 (incluindo 10.1–10.8).
- **Podem ser adiadas sem bloquear:**
  - Ordem dos Passos 11–12 em relação ao 13.
  - Avisos C09–C11.
  - Otimização com COPY.
  - `.claude/launch.json`.
  - Inspeção visual por amostragem da M5 e M6.
  - Acabamento do notebook.
- **Não adiáveis:** confirmação dos 7 ⚠️; checks C01–C08; contrato de camadas; testes de fronteira.

## Sequência de commits

| # | Passo | Mensagem |
|---|---|---|
| 1 | 0 | `docs: add MVP spec, metrics, data dictionary, decisions and implementation plan` |
| 2 | 1 | `build: add project skeleton, pinned dependencies and smoke test` |
| 3 | 2 | `docs: explore StatsBomb WC2022 data, pin source commit and confirm JSON paths` |
| 4 | 3 | `feat(ingest): download pinned StatsBomb WC2022 raw files with manifest` |
| 5 | 4 | `feat(db): create core and analytics schemas with core tables` |
| 6 | 5 | `feat(core): load competitions, teams, matches and ingestion log` |
| 7 | 6 | `feat(core): load players and lineups per match in a transaction` |
| 8 | 7 | `feat(core): load match events with typed columns and extra jsonb` |
| 9 | 8 | `feat(core): load shots, passes, carries, cards and substitutions` |
| 10 | 9 | `feat(quality): add data quality checks, runner and layer contract test` |
| 11–18 | 10.1–10.8 | Mensagens da tabela do Passo 10 |
| 19 | 11 | `feat(app): add match page with score, lineups and shots table` |
| 20 | 12 | `feat(app): add shot map, pass map and xG timeline` |
| 21 | 13 | `feat(pipeline): load all 64 World Cup 2022 matches` |
| 22 | 13 | `docs: finalize README and project documentation` |

## Pontos de atenção transversais

| Situação | Onde é testada |
|---|---|
| Recarga após falha no meio da carga: nenhuma partida fica pela metade | Passo 6 |
| Time sem eventos de um tipo: contagem 0 e taxa `NULL` | Fixtures do 10.x |
| Nomes acentuados do JSON até a tela | Passos 6 e 11 |
| Disputa de pênaltis e gol contra | Sentinelas, Passos 6–10 |
| 1º tempo com acréscimo longo | 10.7 e Passo 12 |

## Desvios em relação à spec

- `pyproject.toml` (D19, Passo 1).
- 3 partidas-sentinela antes das 64.
- `docs/data_notes.md` e JSON de referência (Passo 2).
- Espelhamento de coordenadas na apresentação.
- Validação "do zero" no banco separado `oddvision_verify`.
