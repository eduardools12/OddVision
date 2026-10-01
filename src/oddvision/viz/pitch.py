"""Mapas de campo e gráficos da partida.

As funções de transformação são puras e testadas sem desenhar nada. As figuras são criadas com `matplotlib.figure.Figure`
(sem o estado global do pyplot), então nenhuma fica aberta depois de usada.

Coordenadas: a fonte entrega as duas equipes atacando para x = 120 (campo de 120 x 80 jardas, y crescendo "para baixo").
`analytics` mantém essa perspectiva; só aqui, na apresentação, o visitante é espelhado (120 − x, 80 − y) para os dois
times dividirem um campo. O mplsoccer (`pitch_type='statsbomb'`) já inverte o eixo y ao desenhar, então as funções dele
recebem as coordenadas cruas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from mplsoccer import Pitch

PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0

HOME_COLOR = "#1f77b4"
AWAY_COLOR = "#d95f02"
NEUTRAL = "#7f7f7f"
GOLD = "#e6b800"
RED = "#c0392b"
LABEL_CLASH_MINUTES = 6.0   # rótulos de gols mais próximos que isto são escalonados na vertical
PITCH_STYLE = dict(pitch_type="statsbomb", pitch_color="#f4f6f0", line_color="#555555", linewidth=1)


# --------------------------------------------------------------------------- transformações puras

def flip_for_display(x: float, y: float, team_id: int, home_team_id: int) -> tuple[float, float]:
    """Mandante como veio; visitante espelhado nos dois eixos."""
    if team_id == home_team_id:
        return x, y
    return PITCH_LENGTH - x, PITCH_WIDTH - y


def flip_frame(frame: pd.DataFrame, home_team_id: int, pairs=(("x", "y"), ("end_x", "end_y")), team_col: str = "team_id") -> pd.DataFrame:
    """Cópia do DataFrame com o visitante espelhado nos pares de colunas que existirem. A entrada não é alterada."""
    flipped = frame.copy()
    away = flipped[team_col] != home_team_id
    for x_col, y_col in pairs:
        if x_col in flipped and y_col in flipped:
            flipped.loc[away, x_col] = PITCH_LENGTH - flipped.loc[away, x_col]
            flipped.loc[away, y_col] = PITCH_WIDTH - flipped.loc[away, y_col]
    return flipped


def shot_sizes(xg) -> np.ndarray:
    """Área do marcador proporcional ao xG, com um mínimo para a finalização de xG quase zero continuar visível."""
    return 40.0 + 1100.0 * np.asarray(xg, dtype=float)


def xg_series(frame: pd.DataFrame, team_id: int, end_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Pontos (minutos decorridos, xG acumulado) de um time para um gráfico em degraus ('post').

    Começa em (0, 0) e termina no tempo final da partida com o total do time. Time sem finalizações: linha em zero.
    """
    team = frame[frame["team_id"] == team_id].sort_values("tempo_decorrido_s")
    minutes = [0.0] + (team["tempo_decorrido_s"] / 60.0).tolist() + [end_s / 60.0]
    total = float(team["xg_acumulado"].iloc[-1]) if len(team) else 0.0
    values = [0.0] + team["xg_acumulado"].tolist() + [total]
    return np.array(minutes), np.array(values)


def period_boundaries(bounds: pd.DataFrame) -> list[float]:
    """Minutos decorridos em que começa cada período depois do primeiro (as linhas verticais dos gráficos)."""
    later = bounds[bounds["period"] > bounds["period"].min()].sort_values("period")
    return (later["start_s"] / 60.0).tolist()


def match_end_minutes(bounds: pd.DataFrame) -> float:
    return float(bounds["end_s"].max()) / 60.0 if len(bounds) else 90.0


# --------------------------------------------------------------------------- figuras

def _pitch_axes(figsize=(9, 6)):
    figure = Figure(figsize=figsize)
    ax = figure.subplots()
    Pitch(**PITCH_STYLE).draw(ax=ax)
    return figure, ax


def _team_color(team_id: int, home_team_id: int) -> str:
    return HOME_COLOR if team_id == home_team_id else AWAY_COLOR


def shot_map_figure(shots: pd.DataFrame, home_team_id: int, home_name: str, away_name: str) -> Figure:
    """Finalizações dos dois times no mesmo campo (visitante espelhado). Tamanho = xG; preenchido = gol; quadrado = pênalti."""
    figure, ax = _pitch_axes()
    valid = shots[~shots["is_shootout"]] if len(shots) else shots
    flipped = flip_frame(valid, home_team_id, pairs=(("x", "y"),))
    pitch = Pitch(**PITCH_STYLE)
    for is_goal in (False, True):
        for is_penalty in (False, True):
            part = flipped[(flipped["is_goal"] == is_goal) & (flipped["is_penalty"] == is_penalty)]
            if part.empty:
                continue
            colors = [_team_color(t, home_team_id) for t in part["team_id"]]
            pitch.scatter(part["x"], part["y"], ax=ax, s=shot_sizes(part["statsbomb_xg"]), marker="s" if is_penalty else "o",
                          facecolors=colors if is_goal else "none", edgecolors=colors, linewidths=2.2 if is_goal else 1.4,
                          alpha=0.95 if is_goal else 0.8, zorder=3)
    ax.legend(handles=[
        Line2D([], [], marker="o", color="none", markerfacecolor=HOME_COLOR, markeredgecolor=HOME_COLOR, markersize=9, label=f"{home_name} (ataca para a direita)"),
        Line2D([], [], marker="o", color="none", markerfacecolor=AWAY_COLOR, markeredgecolor=AWAY_COLOR, markersize=9, label=f"{away_name} (ataca para a esquerda)"),
        Line2D([], [], marker="o", color="none", markerfacecolor="black", markersize=9, label="Gol (preenchido)"),
        Line2D([], [], marker="o", color="none", markerfacecolor="none", markeredgecolor="black", markersize=9, label="Sem gol (vazado)"),
        Line2D([], [], marker="s", color="none", markerfacecolor="none", markeredgecolor="black", markersize=9, label="Pênalti (quadrado)"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=3, frameon=False, fontsize=8)
    ax.set_title("Mapa de finalizações · tamanho = xG (StatsBomb) · sem a disputa de pênaltis", fontsize=10)
    return figure


def pass_map_figure(passes: pd.DataFrame, team_name: str) -> Figure:
    """Passes de UM time (já filtrados) como setas na perspectiva dele, atacando para a direita. Cinza = incompleto."""
    figure, ax = _pitch_axes()
    pitch = Pitch(**PITCH_STYLE)
    done = passes[passes["is_complete"]]
    missed = passes[~passes["is_complete"]]
    if len(missed):
        pitch.arrows(missed["x"], missed["y"], missed["end_x"], missed["end_y"], ax=ax, color=NEUTRAL, alpha=0.5, width=1.5, headwidth=4, zorder=2)
    if len(done):
        pitch.arrows(done["x"], done["y"], done["end_x"], done["end_y"], ax=ax, color=HOME_COLOR, alpha=0.75, width=1.8, headwidth=4, zorder=3)
        pitch.scatter(done["x"], done["y"], ax=ax, s=14, color=HOME_COLOR, zorder=4)
    ax.set_title(f"Passes de {team_name} · {len(passes)} no filtro ({len(done)} completos) · ataca para a direita", fontsize=10)
    return figure


def _style_time_axis(ax, bounds: pd.DataFrame) -> None:
    end = match_end_minutes(bounds)
    for minute in period_boundaries(bounds):
        ax.axvline(minute, color="#999999", linestyle="--", linewidth=1)
    ax.set_xlim(0, end + 1)
    ax.set_xticks(np.arange(0, end + 1, 15))
    ax.set_xlabel("Tempo decorrido (min, tempo real; linhas tracejadas = início do período seguinte)")
    ax.spines[["top", "right"]].set_visible(False)


def xg_timeline_figure(xg: pd.DataFrame, bounds: pd.DataFrame, teams: list[tuple[int, str]]) -> Figure:
    """xG acumulado de cada time em degraus, no eixo de tempo real. Marcadores nos gols (quadrado = pênalti)."""
    figure = Figure(figsize=(10, 4))
    ax = figure.subplots()
    end_s = match_end_minutes(bounds) * 60.0
    for index, (team_id, name) in enumerate(teams):
        color = HOME_COLOR if index == 0 else AWAY_COLOR
        x, y = xg_series(xg, team_id, end_s)
        ax.step(x, y, where="post", color=color, linewidth=2, label=f"{name} · {y[-1]:.2f}".replace(".", ","))
        goals = xg[(xg["team_id"] == team_id) & xg["is_goal"]]
        previous: list[float] = []
        for _, shot in goals.iterrows():
            minute = shot["tempo_decorrido_s"] / 60.0
            ax.plot(minute, shot["xg_acumulado"], marker="s" if shot["is_penalty"] else "o",
                    color=color, markersize=7, markeredgecolor="black", zorder=3)
            near = sum(1 for earlier in previous if minute - earlier < LABEL_CLASH_MINUTES)
            previous.append(minute)
            ax.annotate(shot["rotulo"], (minute, shot["xg_acumulado"]), textcoords="offset points",
                        xytext=(-4 + 10 * near, 6 - 16 * near), fontsize=7, color=color)
    _style_time_axis(ax, bounds)
    ax.set_ylabel("xG acumulado")
    ax.set_title("xG acumulado ao longo da partida · marcador = gol (quadrado = pênalti)", fontsize=10)
    ax.legend(frameon=False, loc="upper left")
    return figure


def incident_timeline_figure(timeline: pd.DataFrame, home_team_id: int, home_name: str, away_name: str, bounds: pd.DataFrame) -> Figure:
    """Gols, cartões e substituições no tempo: mandante acima da linha, visitante abaixo; uma faixa por tipo de incidente."""
    figure = Figure(figsize=(10, 3.4))
    ax = figure.subplots()
    lanes = {"Goal": 3, "Own Goal": 3, "Card": 2, "Substitution": 1}
    labelled: dict[int, list[float]] = {1: [], -1: []}          # gols já rotulados por lado, para escalonar rótulos vizinhos
    for _, row in timeline.iterrows():
        side = 1 if row["team_id"] == home_team_id else -1
        color = HOME_COLOR if side == 1 else AWAY_COLOR
        x, y = row["tempo_decorrido_s"] / 60.0, side * lanes[row["incident_type"]]
        if row["incident_type"] == "Goal":
            ax.scatter(x, y, s=140, marker="o", color=color, edgecolors="black", zorder=3)
        elif row["incident_type"] == "Own Goal":
            ax.scatter(x, y, s=140, marker="o", facecolors="none", edgecolors=color, linewidths=2.2, zorder=3)
        elif row["incident_type"] == "Card":
            card_color = RED if row["detail"] == "Red Card" else GOLD
            ax.scatter(x, y, s=90, marker="s", color=card_color, edgecolors=RED if row["detail"] == "Second Yellow" else "black", linewidths=1.6, zorder=3)
        else:
            ax.scatter(x, y, s=70, marker="^", color=NEUTRAL, edgecolors="black", zorder=3)
        if row["incident_type"] in ("Goal", "Own Goal"):
            near = sum(1 for earlier in labelled[side] if x - earlier < LABEL_CLASH_MINUTES)
            labelled[side].append(x)
            ax.annotate(row["rotulo"], (x, y), textcoords="offset points", xytext=(0, (9 + 11 * near) * side), ha="center", fontsize=7)
    ax.axhline(0, color="#444444", linewidth=1)
    ax.set_ylim(-4, 4)
    ax.set_yticks([3.0, -3.0])
    ax.set_yticklabels([home_name, away_name])
    ax.legend(handles=[
        Line2D([], [], marker="o", color="none", markerfacecolor="gray", markeredgecolor="black", markersize=8, label="Gol"),
        Line2D([], [], marker="o", color="none", markerfacecolor="none", markeredgecolor="gray", markersize=8, label="Gol contra (a favor)"),
        Line2D([], [], marker="s", color="none", markerfacecolor=GOLD, markeredgecolor="black", markersize=8, label="Amarelo"),
        Line2D([], [], marker="s", color="none", markerfacecolor=RED, markeredgecolor="black", markersize=8, label="Vermelho"),
        Line2D([], [], marker="^", color="none", markerfacecolor=NEUTRAL, markeredgecolor="black", markersize=8, label="Substituição"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=5, frameon=False, fontsize=8)
    _style_time_axis(ax, bounds)
    ax.set_title("Linha do tempo da partida", fontsize=10)
    return figure
