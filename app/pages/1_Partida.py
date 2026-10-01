"""OddVision: página da partida (placar, estatísticas, escalações e finalizações)."""

import streamlit as st

from oddvision import presentation as p
from oddvision.app_support import safe_query

FINAL_MATCH_ID = 3869685  # abre a final da Copa 2022 quando ela estiver carregada

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

st.title(f"{header['home_team_name']} {p.score_text(header)} {header['away_team_name']}")
st.caption(f"{header['competition_stage']} · {header['match_date']:%d/%m/%Y} · placar oficial, sem a disputa de pênaltis")
shootout = p.shootout_text(header)
if shootout:
    st.subheader(shootout)

if not header["has_events"]:
    st.info("Os eventos desta partida ainda não foram carregados: sem estatísticas nem finalizações.")
elif header["score_matches_events"] is False:
    st.warning(f"O placar reconstruído pelos eventos ({header['home_goals']} – {header['away_goals']}) difere do oficial.")

lineups = safe_query("lineups", match_id)

if header["has_events"]:
    stats_tab, lineups_tab, shots_tab = st.tabs(["Estatísticas", "Escalações", "Finalizações"])

    with stats_tab:
        st.dataframe(p.comparison_table(safe_query("team_stats", match_id)))
        st.caption(
            "Passes e conduções progressivas são a **convenção OddVision v1** (início a partir de 40% do campo e ganho de pelo "
            "menos 10 jardas em direção ao gol, ou entrada na área). xG vem da StatsBomb. Fórmulas em `docs/metrics.md`."
        )

    with shots_tab:
        shots = safe_query("shots", match_id)
        teams = sorted(shots["team_name"].unique())
        chosen = st.multiselect("Times", teams, default=teams)
        table = p.shot_table(shots[shots["team_name"].isin(chosen)])
        st.dataframe(table, hide_index=True, column_config={"xG": st.column_config.NumberColumn("xG", format="%.2f")})
        st.caption("A disputa de pênaltis aparece como 'Disputa' e não entra em nenhuma métrica.")
else:
    lineups_tab = st.container()

with lineups_tab:
    if lineups.empty:
        st.info("Sem escalação carregada para esta partida.")
    else:
        left, right = st.columns(2)
        for column, team_id, team_name in ((left, header["home_team_id"], header["home_team_name"]),
                                           (right, header["away_team_id"], header["away_team_name"])):
            column.subheader(team_name)
            column.dataframe(p.lineup_table(lineups, team_id), hide_index=True)

st.divider()
st.caption("Dados: StatsBomb Open Data · OddVision v1")
