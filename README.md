# OddVision

Projeto de portfólio e estudo em **Engenharia de Dados e Análise de Dados aplicada ao futebol**.

O OddVision transforma os dados brutos de eventos do **StatsBomb Open Data** (Copa do Mundo 2022) em métricas documentadas, por meio de um pipeline reprodutível:

```text
JSON bruto (imutável) → core (PostgreSQL, tipado) → analytics (views SQL) → Streamlit
```

> **Status:** em construção. Passo 1 de 13 (esqueleto e dependências).
> O pipeline, o banco e o app ainda não existem.

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

## Créditos dos dados

Os dados são do [StatsBomb Open Data](https://github.com/statsbomb/open-data). Seu uso segue os termos publicados nesse repositório, que pedem atribuição ao StatsBomb em trabalhos que usam os dados.

- Os valores de xG (`statsbomb_xg`) são produzidos pelo modelo do StatsBomb.
- As métricas marcadas como **"OddVision v1"** são convenções deste projeto e **não** são comparáveis com as de outros provedores (veja [`docs/metrics.md`](docs/metrics.md)).
