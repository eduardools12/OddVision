# OddVision

Projeto de portfólio e estudo em **Engenharia de Dados e Análise de Dados aplicada ao futebol**.

O OddVision transforma os dados brutos de eventos do **StatsBomb Open Data** (Copa do Mundo 2022, 64 partidas) em métricas documentadas, por meio de um pipeline reprodutível, e as mostra em uma aplicação Streamlit:

```text
JSON bruto (imutável) → core (PostgreSQL, tipado) → analytics (views SQL) → Streamlit
```

> **Status:** MVP concluído (Passos 1 a 13): as 64 partidas carregadas, 8 métricas em SQL e a página da partida.
> Uma validação ainda depende do autor: rodar o pipeline em um banco vazio (`oddvision_verify`) e comparar com o principal (veja [Reprodutibilidade](#reprodutibilidade)).

## O que a aplicação mostra

Página **Partida** (placar oficial com a disputa de pênaltis à parte, comparativo das métricas dos dois times, xG acumulado, linha do tempo de gols, cartões e substituições, mapa de finalizações, mapa de passes com filtros e escalações) para qualquer uma das 64 partidas.

## As 8 métricas

| | Métrica | Observação |
|---|---|---|
| M1 | Placar e gols | Reconstruído pelos eventos e conferido com o placar oficial nas 64 partidas |
| M2 | Finalizações e finalizações no alvo | "No alvo" = gol, defendida ou defendida na trave (convenção do OddVision) |
| M3 | xG, npxG e npxG por finalização | O xG vem do modelo da StatsBomb; o OddVision **não** calcula xG |
| M4 | Passes e percentual de acerto | Sem laterais; sem resultados "Unknown" e "Injury Clearance" |
| M5 | Passes progressivos | **Convenção OddVision v1** |
| M6 | Conduções progressivas | **Convenção OddVision v1** |
| M7 | Passes para a área | Convenção geométrica |
| M8 | xG acumulado ao longo da partida | Eixo de tempo real, com os acréscimos |

A disputa de pênaltis fica fora de todas as métricas. As fórmulas, o que entra e o que não entra, os valores ausentes, as limitações e o critério de validação de cada métrica estão em [`docs/metrics.md`](docs/metrics.md).

## Arquitetura

| Camada | O que guarda | Regra |
|---|---|---|
| **raw** | JSONs da fonte em `data/raw/` com o `manifest` (sha256) | Imutável, fora do Git, de um commit fixado do repositório `hudl/open-data` |
| **core** | Eventos e tabelas especializadas (finalizações, passes, conduções, cartões, substituições), tipadas, com chaves e restrições | Dados da fonte e derivações estruturais. Chaves da fonte não modeladas ficam em uma coluna `extra JSONB` |
| **analytics** | 11 views SQL (`sql/analytics/`) | Todas as métricas e convenções. **Nunca lê `JSONB`** (um teste confere) |
| **app** | Streamlit (`app/`) | Só consulta `analytics`. Um teste confere |

Python normaliza o JSON com Pandas (funções puras, testadas sem banco); o PostgreSQL guarda e calcula. O código fica em `src/oddvision/`: `ingest.py`, `transform/`, `load.py`, `checks.py`, `pipeline.py` (a linha de comando), `app_queries.py` (as consultas da aplicação), `presentation.py` (formatação) e `viz/` (mapas e gráficos).

Todas as decisões, com alternativas e consequências, estão em [`docs/decisions.md`](docs/decisions.md).

## Como executar

**Requisitos:** Windows, Python **3.13** (launcher `py`), Git e **PostgreSQL 18** com uma role sem privilégio de superusuário que seja dona de dois bancos: o principal e o dos testes. Como superusuário, uma vez:

```sql
CREATE ROLE oddvision_app LOGIN PASSWORD 'troque-esta-senha';
CREATE DATABASE oddvision OWNER oddvision_app;
CREATE DATABASE oddvision_test OWNER oddvision_app;
```

Depois, no PowerShell, dentro da pasta do projeto:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item config\database.example.toml config\database.toml    # ajuste a porta e a senha; o arquivo não é versionado
.\.venv\Scripts\python.exe -m oddvision.pipeline all           # ingest + init-db + load + check
.\.venv\Scripts\python.exe -m streamlit run app/Home.py
```

Os comandos chamam o Python do `.venv` diretamente, sem ativar o ambiente, o que evita o bloqueio da política de execução de scripts do PowerShell. Cada passo também roda sozinho:

| Comando | O que faz |
|---|---|
| `python -m oddvision.pipeline ingest` | Baixa os 130 JSONs do commit fixado, confere o sha256 e grava o `manifest`. Repetível: o que já existe não é baixado de novo |
| `... init-db` | Cria o schema `core` (nunca apaga dados) e recria as views de `analytics` |
| `... load` | Carrega as partidas de `config/selection.toml`, uma transação por partida. Repetível |
| `... check` | Executa 11 checks de qualidade; termina com código 1 se algum de nível erro falhar |

A carga completa leva cerca de 90 a 120 segundos (234.637 eventos). Os testes levam cerca de 3 minutos (`.\.venv\Scripts\python.exe -m pytest`); os de integração são pulados se `config/database.toml` não existir.

## Validação

- **Três camadas de prova por métrica**: fronteiras exatas com dados sintéticos (por exemplo, ganho de distância de 9,99 e 10,00 jardas), os valores de referência da final calculados por um notebook independente do pipeline (`notebooks/`, `tests/fixtures/reference_final_3869685.json`) e invariantes em todas as partidas (a soma dos jogadores é o time, o último ponto do xG acumulado é o xG do time).
- **Testes de mutação manuais**: cada regra de cada métrica foi alterada de propósito para provar que os testes falham.
- **Fatos públicos**: 172 gols, 5 disputas de pênaltis, 228 cartões e o placar de cada partida reproduzido pelos eventos.
- **Qualidade dos dados**: 11 checks (`sql/checks/`), com 0 erros e 1 aviso conhecido (variações de nome de 4 jogadores nos arquivos de escalação).

## Reprodutibilidade

A carga é idempotente: duas execuções seguidas deixam o banco idêntico (contagens e hashes conferidos). Para provar que o pipeline funciona do zero, o autor cria um banco vazio e roda:

```sql
CREATE DATABASE oddvision_verify OWNER oddvision_app;
```

```powershell
.\.venv\Scripts\python.exe -m oddvision.pipeline --database oddvision_verify all
```

A opção `--database` só aceita o banco principal ou um nome terminado em `_verify` (D40).

## Limitações e viés da amostra

- **Uma competição só**: 64 partidas de seleções, masculinas, de um torneio curto. Cada seleção jogou de 3 a 7 partidas, e as que avançaram jogam contra adversários diferentes de quem caiu na primeira fase. Os números por partida não representam o futebol de clubes nem uma temporada.
- **xG é do StatsBomb**: o OddVision só o soma. Todo pênalti tem xG de 0,7835 nessa fonte.
- **Passes e conduções progressivas são uma convenção** (início a partir de 40% do campo e ganho de pelo menos 10 jardas em direção ao gol, ou entrada na área). Não são comparáveis com as definições de outros provedores, e o StatsBomb fragmenta algumas arrancadas em várias conduções.
- **"No alvo" e "passe de jogo corrido"** também são escolhas documentadas, e não definições universais.
- **Gol contra**: o evento é do time beneficiado e a fonte não informa o autor nele.
- **Sem dados 360, sem pressão e sem posição dos adversários**: as métricas não medem o contexto da jogada.
- **O espelhamento do visitante** nos mapas é só de apresentação; o `analytics` guarda as coordenadas como a fonte entrega.

## Documentação

| Documento | Conteúdo |
|---|---|
| [Especificação do MVP](docs/specs/2026-09-29-oddvision-mvp-design.md) | Objetivo, arquitetura, camadas, escopo, riscos |
| [Plano de implementação](docs/plans/2026-09-29-oddvision-mvp-plan.md) | Etapas, validações e commits |
| [Métricas](docs/metrics.md) | Metodologia das 8 métricas e a origem de cada uma (fonte vs OddVision) |
| [Dicionário de dados](docs/data_dictionary.md) | Tabelas, colunas e origem no JSON, e as views de `analytics` |
| [Notas dos dados](docs/data_notes.md) | O que a exploração dos dados reais encontrou |
| [Decisões](docs/decisions.md) | Registro das decisões arquiteturais e metodológicas (D01 a D40) |

## Créditos dos dados

Os dados são do [StatsBomb Open Data](https://github.com/hudl/open-data) (o repositório foi transferido de `statsbomb/open-data`; o commit usado está fixado em `config/selection.toml`). O uso segue os termos publicados nesse repositório, que pedem atribuição ao StatsBomb em trabalhos que usam os dados.

- Os valores de xG (`statsbomb_xg`) são produzidos pelo modelo do StatsBomb.
- As métricas marcadas como **"OddVision v1"** são convenções deste projeto e **não** são comparáveis com as de outros provedores (veja [`docs/metrics.md`](docs/metrics.md)).
