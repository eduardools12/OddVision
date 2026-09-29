"""OddVision: pipeline e análise de partidas de futebol com StatsBomb Open Data.

Camadas (docs/specs/2026-09-29-oddvision-mvp-design.md, seção 4):
raw (JSON imutável) -> core (PostgreSQL, tipado) -> analytics (views SQL) -> Streamlit.
"""
