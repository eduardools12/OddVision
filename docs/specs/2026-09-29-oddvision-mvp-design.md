# OddVision — Especificação do MVP (v1)

| Campo | Valor |
|---|---|
| Status | Aprovada em 2026-09-29 |
| Local do projeto | `C:\Users\Eduardo\Documentos\Projetos\oddvision` |
| Documentos relacionados | [`../metrics.md`](../metrics.md), [`../data_dictionary.md`](../data_dictionary.md), [`../decisions.md`](../decisions.md) |

---

## 1. Objetivo

O OddVision é um projeto de **portfólio e estudo** em Engenharia de Dados e Análise de Dados aplicada ao futebol.

O objetivo do MVP é construir um pipeline reprodutível que transforma os dados brutos de eventos do **StatsBomb Open Data** (Copa do Mundo 2022) em métricas documentadas e as apresenta em uma página de análise de partida.

O projeto prioriza:

1. **Engenharia de dados correta:** camadas separadas, idempotência, integridade, testes e rastreabilidade até a fonte.
2. **Raciocínio analítico explícito:** toda métrica tem metodologia escrita, e convenções próprias são identificadas como tal.
3. **Aprendizado:** cada etapa é implementada de forma didática, com entrada, saída e critério de validação definidos antes de começar.

A aparência do dashboard é secundária.

## 2. Problema que o projeto resolve

Os dados de eventos do StatsBomb são ricos, mas chegam como **JSON aninhado**: cerca de 3.700 eventos por partida, 33 tipos de evento e campos cuja *ausência* carrega significado. Do jeito que vêm, não servem para responder perguntas simples, como:

- Quem criou mais chances, e de que qualidade?
- Quantos passes de fato fizeram a bola avançar?
- Como a criação de chances evoluiu ao longo do jogo?

O OddVision resolve isso em quatro partes:

- Organiza os dados em um **modelo relacional tipado e validado** (PostgreSQL).
- Calcula **métricas com metodologia pública** em uma camada SQL separada.
- Separa com clareza **o que a fonte fornece** do **que o OddVision calcula ou convenciona**.
- Apresenta o resultado de forma visual e verificável.

## 3. Arquitetura

A arquitetura de transformação é **híbrida**:

```text
StatsBomb Open Data (GitHub, commit fixado)
        │  Python (stdlib urllib)
        ▼
[BRUTO]        data/raw/statsbomb/*.json          imutável, fora do Git
        │  Python + Pandas (normalização, tipagem)
        ▼
[TRANSFORMADO] PostgreSQL 18 · schema core         tipado, com PK/FK/CHECK
        │  SQL (views)
        ▼
[MÉTRICA]      PostgreSQL 18 · schema analytics    convenções explícitas
        │  SQLAlchemy Core + pandas
        ▼
[APRESENTAÇÃO] Streamlit                           somente leitura de analytics
```

**Divisão de responsabilidades:**
- O **Python** faz o que faz melhor: ler JSON aninhado e normalizá-lo.
- O **SQL** faz o que faz melhor: agregar dados e aplicar regras analíticas.
- A camada `analytics` pode ser migrada para dbt no futuro sem reescrita conceitual. Veja [D01](../decisions.md#d01--arquitetura-híbrida-python-normaliza-sql-calcula).

## 4. Camadas de dados

| Camada | Onde | Conteúdo | Regras |
|---|---|---|---|
| **Bruto** | `data/raw/statsbomb/` | Arquivos JSON exatamente como publicados pelo StatsBomb | Nunca editados. Baixados de um commit fixado. Fora do Git. Não dependem do banco |
| **Transformado** | schema `core` | A mesma informação, reorganizada, tipada e com integridade referencial | **Sem convenções analíticas.** Só derivações estruturais determinísticas (por exemplo, `is_complete = outcome ausente`). Campos não modelados vão para `extra JSONB` |
| **Métrica** | schema `analytics` | Views com as 8 métricas do MVP | Convenções e parâmetros explícitos. **Proibido ler JSONB.** Cada métrica corresponde a uma seção de `metrics.md` |
| **Apresentação** | Streamlit | Página de partida | Lê **somente** do schema `analytics` |

### 4.1 Origem de cada informação

Todo número exibido pertence a exatamente uma destas classes, e a classe é registrada em [`metrics.md`](../metrics.md):

| Classe | Exemplo | Onde é produzido |
|---|---|---|
| **Fornecido pelo StatsBomb** | `statsbomb_xg` de uma finalização; `home_score` de uma partida | Fonte (copiado para `core`) |
| **Derivação estrutural do OddVision** | `is_complete` (passe sem `outcome`); `is_starter` | `core` (determinística, sem julgamento) |
| **Cálculo do OddVision** | xG total (soma), `npxG`, `xg_acumulado` | `analytics` (aritmética sobre dados nativos) |
| **Convenção metodológica do OddVision** | `passes_progressivos`, `conducoes_progressivas`, "finalização no alvo", `passes_para_area` | `analytics` (envolve escolhas de limiar e exclusão) |

## 5. Fluxo do pipeline

A regra do projeto é que **nenhuma etapa começa sem entrada, saída e critério de validação definidos**.

| Etapa | Entrada | Processamento | Saída | Validação |
|---|---|---|---|---|
| **P1 Ingestão** | `config/selection.toml` (competição 43, temporada 106, commit da fonte) | Baixa os arquivos de URLs fixadas no commit; pula os que já existem; calcula SHA-256 | 130 arquivos em `data/raw/statsbomb/` + `data/manifests/statsbomb_manifest.csv` | Exatamente **130 arquivos** (1 competitions + 1 matches + 64 events + 64 lineups); todo JSON válido; 2ª execução baixa 0 arquivos; SHA-256 do disco = manifest |
| **P2 Partidas** | `competitions.json`, `matches/43/106.json` | Normalização e tipagem | `core.competitions`, `core.teams`, `core.matches` | 64 partidas; 32 seleções; placar não nulo; FKs válidas |
| **P3 Escalações** | `lineups/{match_id}.json` | Normalização; derivação de `is_starter` e `played` | `core.players`, `core.lineups` | 11 titulares por time e partida (128 combinações); `is_starter ⇒ played` |
| **P4 Eventos (núcleo)** | `events/{match_id}.json` | Colunas comuns tipadas + `extra JSONB` | `core.events` | Nº de eventos por partida = manifest; IDs únicos; `match_id` correto; contagem por tipo igual à do bruto; times do evento ∈ {mandante, visitante} |
| **P5 Eventos específicos** | `events/{match_id}.json` | Extração dos objetos `shot`, `pass`, `carry`, cartões e substituições | `core.shots`, `core.passes`, `core.carries`, `core.cards`, `core.substitutions` | Contagem = nº de eventos do tipo em `core.events`; relação 1:1; domínios conhecidos |
| **P6 Qualidade** | `core.*` | Execução de `sql/checks/*.sql` | Relatório de erros e avisos | 0 erros. Qualquer erro encerra o pipeline com código ≠ 0 |
| **P7 Métricas** | `core.*` | Views SQL | `analytics.*` | Valores de referência da final reproduzidos + invariantes (seção 10) |
| **P8 Apresentação** | `analytics.*` | Streamlit | Página "Partida" | Conferência visual com fatos públicos da partida |

**Idempotência:**
- **Dados por partida** (`events`, tabelas específicas, `lineups`): `DELETE` + `INSERT` da partida dentro de **uma única transação**. As tabelas específicas usam `ON DELETE CASCADE` a partir de `core.events`.
- **Dimensões compartilhadas** (`competitions`, `teams`, `players`): `INSERT … ON CONFLICT DO UPDATE`.

Detalhes em [D06](../decisions.md#d06--delete--insert-por-partida-dentro-de-transação).

**Interface planejada:** um CLI, `python -m oddvision.pipeline {ingest|load|check|all}`.

## 6. Estrutura de pastas (planejada)

```text
oddvision/
├── README.md                       # visão geral, como rodar, créditos ao StatsBomb
├── requirements.txt                # dependências de execução (versões fixadas)
├── requirements-dev.txt            # pytest, ipykernel
├── .gitignore                      # .venv/, data/, config/database.toml
├── config/
│   ├── selection.toml              # competição/temporada + commit fixado da fonte
│   ├── database.example.toml       # modelo de credenciais (versionado)
│   └── database.toml               # credenciais locais (NÃO versionado)
├── data/
│   ├── raw/statsbomb/              # competitions.json, matches/43/106.json, events/, lineups/
│   └── manifests/                  # statsbomb_manifest.csv (gerado pela ingestão)
├── sql/
│   ├── ddl/                        # 001_schemas.sql, 002_core_tables.sql, …
│   ├── analytics/                  # views de métricas
│   └── checks/                     # C01_*.sql … (consultas que devem retornar 0 linhas)
├── src/oddvision/
│   ├── config.py                   # lê TOML
│   ├── db.py                       # engine SQLAlchemy
│   ├── ingest.py                   # P1
│   ├── transform/                  # matches.py, lineups.py, events.py (P2–P5)
│   ├── load.py                     # gravação transacional no core
│   ├── checks.py                   # P6
│   └── pipeline.py                 # CLI
├── app/
│   ├── Home.py
│   └── pages/1_Partida.py
├── notebooks/01_exploracao.ipynb
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── docs/
    ├── specs/2026-09-29-oddvision-mvp-design.md
    ├── metrics.md
    ├── data_dictionary.md
    └── decisions.md
```

O manifest fica em `data/manifests/`, **fora** de `data/raw/`. Assim a pasta bruta contém somente arquivos da fonte.

## 7. Modelo conceitual do banco

O detalhamento completo (colunas, tipos, restrições e origem no JSON) está em [`data_dictionary.md`](../data_dictionary.md).

```text
competitions 1──N matches N──1 teams (mandante)
                     │   └──N──1 teams (visitante)
                     │
                     ├──1──N lineups N──1 players
                     │
                     └──1──N events N──1 teams / players
                                │
                                ├──1──0..1 shots
                                ├──1──0..1 passes
                                ├──1──0..1 carries
                                ├──1──0..1 cards
                                └──1──0..1 substitutions

ingestion_log (rastreabilidade de arquivos; sem FK)
```

**Princípios:**
1. Toda informação usada por uma métrica do MVP vira **coluna tipada e documentada**.
2. O `extra JSONB` só preserva campos da fonte **ainda não modelados**.
3. O que pode ser garantido pelo banco (PK, FK, UNIQUE, CHECK) vira constraint. O que não pode vira check em `sql/checks/`.
4. O schema `analytics` só contém views e **não pode ler JSONB**. Um teste automatizado garante isso.

## 8. Escopo do MVP

### 8.1 Dentro do escopo

**Dados:**
- Copa do Mundo 2022 (`competition_id = 43`, `season_id = 106`).
- 64 partidas: `competitions`, `matches`, `lineups`, `events`.
- Arquivos fixados em um commit do repositório `statsbomb/open-data`.

**Métricas (8, detalhadas em `metrics.md`):**
1. Placar e gols
2. Finalizações e finalizações no alvo
3. xG (e npxG)
4. Passes e percentual de acerto
5. Passes progressivos (convenção OddVision v1)
6. Conduções progressivas (convenção OddVision v1)
7. Passes para a área
8. xG acumulado ao longo da partida

**Página "Partida" (Streamlit):**
1. Seletor de partida.
2. Placar, com a disputa de pênaltis como informação complementar.
3. Escalações: titulares, reservas utilizados e não utilizados (sem minutos jogados).
4. Tabela de finalizações: tempo, jogador, tipo, resultado, xG.
5. Mapa de finalizações: tamanho proporcional ao xG, gols destacados.
6. Mapa de passes: filtro por time e jogador; completos vs incompletos; destaque para progressivos e passes para a área.
7. Timeline: gols, cartões, substituições e gráfico de xG acumulado.
8. Tabela por jogador com as métricas M1–M7 (contagens na partida, sem normalização).

**Engenharia:** pipeline idempotente via CLI, checks de qualidade, testes unitários e de integração, documentação.

### 8.2 Fora do escopo (versões posteriores)

- Field tilt
- Ações defensivas
- xA
- Minutos jogados
- Métricas por 90 minutos
- Comparação entre jogadores
- Scouting
- Machine Learning
- Dados 360
- Página de jogador
- Múltiplas competições
- Docker, dbt, Airflow, APIs, deploy

## 9. Roadmap

Cada passo termina com um commit **feito manualmente pelo autor**. Nenhum passo começa sem entrada, saída e validação definidos.

| # | Passo | Entrada | Saída | Validação |
|---|---|---|---|---|
| 0 | Ambiente | Esta spec | `git init` na pasta do projeto; venv Python 3.13; PostgreSQL 18 funcional; banco `oddvision` | `git rev-parse --show-toplevel` = pasta do projeto; `psql -c "select version()"` responde. **Antes de qualquer ação no PostgreSQL, inspecionar e relatar (seção 12.2)** |
| 1 | Esqueleto | Spec + docs | Pastas, `.gitignore`, `requirements*.txt`, `README.md` | `pip install` sem erro; `pytest` executa; `data/` ignorado pelo Git |
| 2 | Exploração guiada | JSON da final (`3869685`) | Notebook + notas | Reproduz: 4.407 eventos, 38 finalizações, 8 delas no período 5; confirma os campos marcados "a confirmar" no dicionário |
| 3 | Ingestão (P1) | `selection.toml` | `data/raw` + manifest | 130 arquivos; 2ª execução baixa 0; SHA-256 confere |
| 4 | DDL | `data_dictionary.md` | Schemas `core` e `analytics`; 12 tabelas | DDL reexecutável; constraints presentes |
| 5 | Partidas (P2) | matches, competitions | `core.competitions`, `teams`, `matches` | 64 partidas; 32 times; FKs válidas |
| 6 | Escalações (P3) | lineups | `core.players`, `lineups` | 11 titulares × 128 combinações de time e partida |
| 7 | Eventos núcleo (P4) | events | `core.events` | Contagens = manifest; tipos preservados |
| 8 | Eventos específicos (P5) | events | `shots`, `passes`, `carries`, `cards`, `substitutions` | Relação 1:1; domínios; cartões conciliados com as escalações |
| 9 | Checks (P6) | `core` | `sql/checks` + execução no CLI | Tudo verde nos dados reais; fixture corrompida de propósito **falha** |
| 10 | Métricas (P7) | `core` | Views `analytics`, **uma métrica por vez** | Valores de referência + invariantes; revisão metodológica |
| 11 | App v1 | `analytics` | Placar, escalações, finalizações | Final: 3–3; gols de Messi (2), Di María (1), Mbappé (3) |
| 12 | Mapas e timeline | `analytics` | Mapas de finalizações e passes, M8 | Finalizações no campo de ataque; último ponto de M8 = M3; sem sobreposição de períodos |
| 13 | Escala e documentação | 64 partidas | README final | Pipeline do zero passa em todos os checks; tempo de execução medido e registrado |

## 10. Testes

| Nível | Ferramenta | Escopo |
|---|---|---|
| **Unitário** | pytest (sem banco) | Transformações JSON → DataFrame: campos ausentes com significado (`outcome` → `is_complete`), booleanos ausentes → `false`, tipagem, conteúdo do `extra` |
| **Integração** | pytest + banco `oddvision_test` | Carrega a fixture (trecho real + eventos sintéticos de fronteira) e verifica `core` e `analytics` |
| **Referência** | pytest | A final (`3869685`) reproduz os valores de referência de `metrics.md`, que foram calculados por um script exploratório independente |
| **Contrato de camadas** | pytest | Nenhum operador JSON (`->`, `->>`, `#>`, `#>>`, `@>`, `?`) nem coluna `extra` em `sql/analytics/` |
| **Fronteira das convenções** | pytest (integração) | Casos sintéticos: Δd = 9,99 vs 10,00; `x_início` = 47,9 vs 48,0; pontos exatamente na linha da área |
| **Inspeção visual** | notebook/app | Amostras de 20 eventos marcados e 20 não marcados como progressivos, desenhados no campo |

## 11. Qualidade dos dados

**Checks em `sql/checks/`.** Um **erro** interrompe o pipeline; um **aviso** é reportado e não interrompe.

| ID | Nível | Regra |
|---|---|---|
| C01 | Erro | Nº de eventos por partida em `core.events` = `record_count` do manifest |
| C02 | Erro | Placar reconstruído (M1) = `matches.home_score` / `away_score` |
| C03 | Erro | Coordenadas fora de [0, 120] × [0, 80] (também é CHECK na tabela) |
| C04 | Erro | Valor fora do domínio conhecido em `shots.outcome`, `shots.shot_type`, `passes.outcome`, `passes.pass_type`, `cards.card_type` |
| C05 | Erro | Tabela específica com contagem ≠ nº de eventos do tipo em `core.events` |
| C06 | Erro | `statsbomb_xg` nulo ou fora de [0, 1] |
| C07 | Erro | Time e partida sem exatamente 11 titulares |
| C08 | Erro | Evento cujo `team_id` não é mandante nem visitante da partida (protege o `match_id` derivado do nome do arquivo) |
| C09 | Aviso | Cartões em `core.cards` ≠ cartões registrados nas escalações |
| C10 | Aviso | `statsbomb_xg` de pênalti ≠ 0,7835 |
| C11 | Aviso | O mesmo `player_id` aparece com nomes diferentes em arquivos diferentes |

**Constraints do banco (não viram checks):** PK, FK, `UNIQUE(match_id, idx)`, `CHECK period BETWEEN 1 AND 5`, `CHECK is_complete = (outcome IS NULL)`.

**Fatos observados em 2026-09-29** (perfil em memória das 64 partidas, branch `master` da fonte):

| Fato | Valor |
|---|---|
| Eventos | 234.637, 0 IDs duplicados, 33 tipos |
| Eventos por período | P1: 116.337 · P2: 112.708 · P3: 2.885 · P4: 2.601 · P5: 106 |
| Partidas com disputa de pênaltis | 5 |
| Minuto por período | P1 vai de 0 a **59** · P2 vai de **45** a 103. Ou seja, o minuto não é monotônico entre períodos |
| Coordenadas | x ∈ [0,1; 120,0]; y ∈ [0,1; 80,0]. O menor `x` de uma finalização (P1–P4) é 59,0 |
| `shot.outcome` | Blocked, Goal, Off T, Post, Saved, Saved Off Target, Saved to Post, Wayward |
| `shot.type` | Open Play, Free Kick, Penalty, Corner |
| `pass.outcome` | ausente (completo) 56.346 · Incomplete 10.393 · Out 1.116 · Unknown 394 · Pass Offside 224 · Injury Clearance 42 |
| `pass.type` | ausente 56.423 · Recovery 5.349 · Throw-in 2.617 · Free Kick 1.768 · Goal Kick 1.002 · Corner 569 · Interception 480 · Kick Off 307 |
| `end_location` ausente | 0 passes, 0 conduções |
| Passe completo sem recebedor | 0 |
| Gols contra | 3 (`Own Goal For` sem `player`) |
| xG de pênalti | 0,7835 em todos os 64 pênaltis |
| Reconciliação do placar | 0 divergências em 64 partidas |
| `match_id` | **Não existe dentro** dos JSONs de events e lineups; vem do nome do arquivo |

## 12. Riscos

### 12.1 Riscos técnicos e de dados

| Risco | Mitigação |
|---|---|
| Campo ausente com significado (`pass.outcome`, flags booleanas) confundido com dado faltante | Derivação explícita em `core` + testes unitários |
| Minuto não monotônico entre períodos | Ordenar por `(period, idx)`; eixo de tempo com a duração real de cada período (M8) |
| Disputa de pênaltis inflando métricas | Período 5 excluído de todas as métricas ([D08](../decisions.md#d08--exclusão-do-período-5-de-todas-as-métricas)) |
| Gol contra não é `Shot` | Regra da M1 + check C02 |
| `match_id` derivado do nome do arquivo | Check C08 + conferência com o manifest |
| Coordenadas relativas ao time que executa a ação | Espelhamento de um dos times no mapa + teste |
| Grafia literal dos valores da fonte (`Saved to Post`) | Check de domínio C04 |
| Atualizações da fonte | Commit fixado + SHA-256 no manifest |
| Encoding no Windows (acentos corrompidos no terminal) | UTF-8 forçado (`PYTHONUTF8=1`, `client_encoding=UTF8`) + teste com nomes acentuados |
| Convenções lidas como se fossem definições universais | Rótulo "OddVision v1" na UI e nos documentos; parâmetros nomeados |
| Viés da amostra do Open Data | README declara que as análises valem para a amostra |
| Licença e atribuição do StatsBomb | Seção de créditos no README e no app |
| Valores de referência calculados sobre `master`, não sobre o commit fixado | Recalcular e confirmar os valores de `metrics.md` no passo 3, com o commit fixado |

### 12.2 PostgreSQL já existente na máquina

Inspeção somente leitura feita em 2026-09-29:
- A pasta `C:\Program Files\PostgreSQL\18\` existe.
- Contém `data/` com arquivos de cluster (`PG_VERSION`, `base`, `current_logfiles`).
- `bin/` contém 46 arquivos, aparentemente bibliotecas de PostGIS/MobilityDB, **sem** `psql.exe` e sem `postgres.exe`.
- Nenhum serviço Windows do PostgreSQL foi encontrado.

**Regra:**
- No passo 0, o ambiente será **reinspecionado e relatado** antes de qualquer ação.
- **Nada será apagado, movido, formatado, sobrescrito ou reinstalado automaticamente.**
- A pasta `data/` pode conter dados de outros projetos. A decisão sobre ela é do autor.

## 13. Dependências previstas

Nada está instalado ainda. As versões serão fixadas no passo 1, após conferir a compatibilidade com o Python 3.13.

| Pacote | Uso | Justificativa |
|---|---|---|
| `pandas` | Normalização | Requisito do projeto |
| `psycopg[binary]` (3.x) | Driver do PostgreSQL | Driver atual e mantido |
| `SQLAlchemy` (Core, sem ORM) | Conexão para pandas e Streamlit | Interface oficialmente suportada por `pandas.read_sql` |
| `streamlit` | Apresentação | Requisito do projeto |
| `mplsoccer` (+ `matplotlib`) | Desenho do campo | Suporte nativo ao sistema de coordenadas do StatsBomb (`pitch_type='statsbomb'`) |
| `pytest` (dev) | Testes | Padrão de mercado |
| `ipykernel` (dev) | Notebook no VS Code | Necessário para executar o kernel |

**Biblioteca padrão:** `urllib`, `json`, `hashlib`, `tomllib`, `argparse`, `logging`, `pathlib`, `csv`.

**Explicitamente não usados no MVP:** `statsbombpy`, `requests`, `python-dotenv`, `plotly`, Docker, dbt, Airflow. Veja [D12](../decisions.md#d12--sem-statsbombpy-no-pipeline-principal) e [D13](../decisions.md#d13--sem-docker-dbt-e-airflow-no-mvp).

## 14. Ferramentas utilizadas

| Ferramenta | Origem | Uso |
|---|---|---|
| `superpowers` 6.4.1 (brainstorming, writing-plans, test-driven-development, verification-before-completion, systematic-debugging) | Plugin instalado (`claude-plugins-official`) | Desenho da spec, plano de implementação, TDD nos passos 5–10, verificação antes de concluir |
| `context7` | Plugin instalado | Documentação atualizada de pandas, psycopg, SQLAlchemy, Streamlit e mplsoccer |
| `data:explore-data` | Plugin `data` 1.1.0 (Anthropic, fornecido pelo app desktop) | Passos 2 e 7: perfilar o JSON e as tabelas do `core` |
| `data:sql-queries` | Plugin `data` (uso interno do assistente; `user-invocable: false`) | Passos 9–10: revisão do SQL |
| `data:validate-data` | Plugin `data` | Passos 10 e 12: revisão metodológica das métricas |
| Navegador interno do app | Claude desktop | Passos 11–12: preview do Streamlit |
| Git + VS Code | Local | Todos os passos (commits manuais) |
| PostgreSQL 18 | Local (situação a resolver no passo 0) | Passos 4–13 |

Os conectores declarados pelo plugin `data` (BigQuery, Hex etc.) **não serão usados**. Nenhum plugin ou skill novo será instalado sem aviso prévio.

## 15. Critérios de sucesso do MVP

1. Uma base vazia vira uma base com as 64 partidas com **um comando**, e **todos os checks de erro passam**.
2. Rodar o pipeline de novo **não altera nenhuma contagem** (idempotência).
3. A final (`3869685`) reproduz os **valores de referência** de `metrics.md`.
4. Todos os testes (unitários, integração, referência, contrato de camadas) passam.
5. A página "Partida" funciona para qualquer uma das 64 partidas, com todos os componentes da seção 8.1.
6. Toda métrica exibida tem seção em `metrics.md`, com a classe de origem. As convenções aparecem rotuladas como "OddVision v1" na interface.
7. Nenhuma view de `analytics` lê JSONB.
8. Uma pessoa de fora consegue reproduzir o projeto seguindo apenas o README.
