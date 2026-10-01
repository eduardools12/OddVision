# OddVision

Projeto de portfólio e estudo em **Engenharia de Dados e Análise de Dados aplicada ao futebol**.

O OddVision transforma os dados brutos de eventos do **StatsBomb Open Data** (Copa do Mundo 2022) em métricas documentadas, por meio de um pipeline reprodutível:

```text
JSON bruto (imutável) → core (PostgreSQL, tipado) → analytics (views SQL) → Streamlit
```

> **Status:** em construção. Passo 11 de 13 concluído: pipeline, banco, as 8 métricas em SQL e a página básica da partida.
> Faltam os mapas e gráficos (Passo 12) e a carga das 64 partidas (Passo 13): por enquanto só 3 partidas têm eventos carregados.

## Documentação

| Documento | Conteúdo |
|---|---|
| [Especificação do MVP](docs/specs/2026-09-29-oddvision-mvp-design.md) | Objetivo, arquitetura, camadas, escopo, riscos |
| [Plano de implementação](docs/plans/2026-09-29-oddvision-mvp-plan.md) | Etapas, validações e commits |
| [Métricas](docs/metrics.md) | Metodologia das 8 métricas e a origem de cada uma (fonte vs OddVision) |
| [Dicionário de dados](docs/data_dictionary.md) | Tabelas, colunas e origem no JSON |
| [Decisões](docs/decisions.md) | Registro das decisões arquiteturais e metodológicas |

## Ambiente de desenvolvimento

**Requisitos:** Windows, Python **3.13** (disponível no *launcher* `py`) e Git. O PostgreSQL 18 só será necessário a partir do Passo 4.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pytest
```

Os comandos chamam o Python do `.venv` diretamente, sem ativar o ambiente. Isso evita o bloqueio da política de execução de scripts do PowerShell.

## Pipeline e aplicação

Com o PostgreSQL 18 no ar e `config/database.toml` criado a partir de `config/database.example.toml` (o arquivo real não é versionado):

```powershell
.\.venv\Scripts\python.exe -m oddvision.pipeline ingest    # baixa os JSONs brutos (imutáveis, fora do Git)
.\.venv\Scripts\python.exe -m oddvision.pipeline init-db   # cria o schema core e recria as views de analytics
.\.venv\Scripts\python.exe -m oddvision.pipeline load      # carrega as partidas selecionadas em config/selection.toml
.\.venv\Scripts\python.exe -m oddvision.pipeline check     # confere a qualidade dos dados carregados
.\.venv\Scripts\python.exe -m streamlit run app/Home.py    # abre a aplicação
```

A aplicação só lê o schema `analytics`.

## Créditos dos dados

Os dados são do [StatsBomb Open Data](https://github.com/statsbomb/open-data). Seu uso segue os termos publicados nesse repositório, que pedem atribuição ao StatsBomb em trabalhos que usam os dados.

- Os valores de xG (`statsbomb_xg`) são produzidos pelo modelo do StatsBomb.
- As métricas marcadas como **"OddVision v1"** são convenções deste projeto e **não** são comparáveis com as de outros provedores (veja [`docs/metrics.md`](docs/metrics.md)).
