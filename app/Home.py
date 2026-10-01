"""OddVision: página inicial."""

import sys
from pathlib import Path

import streamlit as st

# Funciona sem instalar o pacote (por exemplo no Streamlit Community Cloud): `src/` entra no caminho de importação.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oddvision.app_support import safe_query

st.set_page_config(page_title="OddVision", page_icon="⚽", layout="wide")

st.title("OddVision")
st.caption("Análise de dados de futebol · Copa do Mundo 2022 · OddVision v1")

st.markdown(
    "Projeto de estudo e portfólio em Engenharia de Dados e análise de futebol. Os eventos da fonte são normalizados em "
    "PostgreSQL e as métricas são calculadas em SQL; esta aplicação só lê a camada `analytics`."
)

matches = safe_query("list_matches")
loaded = int(matches["has_events"].sum())
col_total, col_loaded = st.columns(2)
col_total.metric("Partidas da Copa", len(matches))
col_loaded.metric("Com eventos carregados", loaded)
if loaded < len(matches):
    st.info("Só as partidas com eventos carregados têm estatísticas, finalizações e escalações completas.")

st.page_link("pages/1_Partida.py", label="Abrir a página da partida", icon="📊")

st.subheader("Métricas do MVP")
st.markdown(
    "- **M1** Placar e gols · **M2** Finalizações e no alvo · **M3** xG (do StatsBomb), npxG e npxG por finalização\n"
    "- **M4** Passes e % de acerto · **M7** Passes para a área\n"
    "- **M5** Passes progressivos e **M6** Conduções progressivas: **convenção OddVision v1**, não uma definição universal\n"
    "- **M8** xG acumulado ao longo da partida\n\n"
    "As fórmulas e as limitações de cada métrica estão em `docs/metrics.md`."
)

st.divider()
st.caption(
    "Dados: [StatsBomb Open Data](https://github.com/hudl/open-data), fornecidos pela StatsBomb. "
    "O xG vem do modelo da StatsBomb; o OddVision não o calcula."
)
