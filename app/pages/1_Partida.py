"""OddVision: página da partida (placar, estatísticas, xG acumulado, linha do tempo, mapas, escalações)."""

import sys
from pathlib import Path

import streamlit as st

# Funciona sem instalar o pacote (por exemplo no Streamlit Community Cloud): `src/` entra no caminho de importação.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddvision import presentation as p
from oddvision.app_support import safe_query
from oddvision.viz import pitch as viz

FINAL_MATCH_ID = 3869685  # abre a final da Copa 2022 quando ela estiver carregada
ALL_PLAYERS = "Todos os jogadores"

st.set_page_config(page_title="Partida · OddVision", page_icon="⚽", layout="wide")

matches = safe_query("list_matches")
if matches.empty:
    st.warning("Nenhuma partida no banco. Rode `python -m oddvision.pipeline load`.")
    st.stop()

rows = {int(r["match_id"]): r for _, r in matches.iterrows()}
ids = list(rows)
loaded_ids = [i for i in ids if rows[i]["has_events"]]
default_id = FINAL_MATCH_ID if FINAL_MATCH_ID in loaded_ids else (loaded_ids[0] if loaded_ids else ids[0])

match_id = st.sidebar.selectbox("Partida", ids, index=ids.index(default_id), format_func=lambda i: p.match_label(rows[i]))
st.sidebar.caption("OddVision v1")

header = safe_query("match_header", match_id)
home_id, home_name = header["home_team_id"], header["home_team_name"]
away_id, away_name = header["away_team_id"], header["away_team_name"]

st.title(f"{home_name} {p.score_text(header)} {away_name}")
st.caption(f"{header['competition_stage']} · {header['match_date']:%d/%m/%Y} · placar oficial, sem a disputa de pênaltis")
shootout = p.shootout_text(header)
if shootout:
    st.subheader(shootout)

if not header["has_events"]:
    st.info("Os eventos desta partida ainda não foram carregados: sem estatísticas, mapas nem finalizações.")
elif header["score_matches_events"] is False:
    st.warning(f"O placar reconstruído pelos eventos ({header['home_goals']} – {header['away_goals']}) difere do oficial.")


def show(figure):
    st.pyplot(figure)  # a figura é um matplotlib.figure.Figure solto (sem pyplot): nada fica aberto


lineups = safe_query("lineups", match_id)

if header["has_events"]:
    stats_tab, xg_tab, timeline_tab, shots_tab, passes_tab, lineups_tab = st.tabs(
        ["Estatísticas", "xG acumulado", "Linha do tempo", "Finalizações", "Passes", "Escalações"])
    bounds = safe_query("period_bounds", match_id)

    with stats_tab:
        st.dataframe(p.comparison_table(safe_query("team_stats", match_id)))
        st.caption(
            "Passes e conduções progressivas são a **convenção OddVision v1** (início a partir de 40% do campo e ganho de pelo "
            "menos 10 jardas em direção ao gol, ou entrada na área). xG vem da StatsBomb. Fórmulas em `docs/metrics.md`."
        )

    with xg_tab:
        show(viz.xg_timeline_figure(safe_query("xg_timeline", match_id), bounds, [(home_id, home_name), (away_id, away_name)]))
        st.caption("Cada degrau é uma finalização (a disputa de pênaltis fica de fora). O pênalti em jogo entra como um degrau de ~0,78.")

    with timeline_tab:
        incidents = safe_query("match_timeline", match_id)
        show(viz.incident_timeline_figure(incidents, home_id, home_name, away_name, bounds))
        with st.expander("Lista de incidentes"):
            st.dataframe(p.incident_table(incidents), hide_index=True)

    with shots_tab:
        shots = safe_query("shots", match_id)
        show(viz.shot_map_figure(shots, home_id, home_name, away_name))
        st.caption("O visitante é espelhado só na apresentação, para os dois times dividirem o campo.")
        teams = sorted(shots["team_name"].unique())
        chosen = st.multiselect("Times", teams, default=teams)
        st.dataframe(p.shot_table(shots[shots["team_name"].isin(chosen)]), hide_index=True,
                     column_config={"xG": st.column_config.NumberColumn("xG", format="%.2f")})
        st.caption("A disputa de pênaltis aparece como 'Disputa' na tabela e não entra em nenhuma métrica.")

    with passes_tab:
        passes = safe_query("passes", match_id)
        team_choice = st.radio("Time", [home_name, away_name], horizontal=True)
        team_id = home_id if team_choice == home_name else away_id
        team_passes = passes[passes["team_id"] == team_id]
        players = team_passes.drop_duplicates("player_id").sort_values("player_name")
        player_choice = st.selectbox("Jogador", [ALL_PLAYERS] + players["player_name"].tolist())
        kind = st.selectbox("Tipo de passe", list(p.PASS_KINDS), format_func=p.PASS_KINDS.get)
        player_id = None if player_choice == ALL_PLAYERS else int(players[players["player_name"] == player_choice]["player_id"].iloc[0])
        chosen_passes = p.filter_passes(passes, team_id, player_id, kind)
        show(viz.pass_map_figure(chosen_passes, team_choice))
        st.caption("Passes tentados (M4: sem laterais). Seta cinza = incompleto. 'Progressivos' é a convenção OddVision v1.")
else:
    lineups_tab = st.container()

with lineups_tab:
    if lineups.empty:
        st.info("Sem escalação carregada para esta partida.")
    else:
        left, right = st.columns(2)
        for column, team_id, team_name in ((left, home_id, home_name), (right, away_id, away_name)):
            column.subheader(team_name)
            column.dataframe(p.lineup_table(lineups, team_id), hide_index=True)

st.divider()
st.caption("Dados: StatsBomb Open Data · OddVision v1")
