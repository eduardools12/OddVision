"""Apresentação da página da partida: rótulos, formatação e tabelas em português.

Funções puras (recebem linhas/DataFrames já lidos de `analytics`, devolvem texto ou DataFrames para exibir). Não
conhecem banco nem Streamlit, e por isso são testadas sem nenhum dos dois.
"""

from __future__ import annotations

import pandas as pd

# (coluna de analytics.team_match_stats, rótulo, formato). As métricas progressivas levam o selo da convenção (D09).
STATS_ROWS: list[tuple[str, str, str]] = [
    ("gols", "Gols", "int"),
    ("finalizacoes", "Finalizações", "int"),
    ("finalizacoes_no_alvo", "Finalizações no alvo", "int"),
    ("xg", "xG", "dec2"),
    ("npxg", "npxG (sem pênaltis)", "dec2"),
    ("npxg_por_finalizacao_sem_penalti", "npxG por finalização (sem pênaltis)", "dec3"),
    ("passes_tentados", "Passes", "int"),
    ("passes_completos", "Passes completos", "int"),
    ("pct_acerto_passes", "Acerto de passes (%)", "pct"),
    ("passes_progressivos", "Passes progressivos (OddVision v1)", "int"),
    ("conducoes_progressivas", "Conduções progressivas (OddVision v1)", "int"),
    ("passes_para_area", "Passes para a área", "int"),
]

MISSING_TEXT = "–"

OUTCOMES = {
    "Goal": "Gol", "Saved": "Defendida", "Saved to Post": "Defendida na trave", "Post": "Trave",
    "Blocked": "Bloqueada", "Off T": "Para fora", "Wayward": "Muito desviada", "Saved Off Target": "Defendida (iria para fora)",
}
SHOT_TYPES = {"Open Play": "Jogo corrido", "Penalty": "Pênalti", "Free Kick": "Falta", "Corner": "Escanteio", "Kick Off": "Saída de bola"}
BODY_PARTS = {"Right Foot": "Pé direito", "Left Foot": "Pé esquerdo", "Head": "Cabeça", "Other": "Outra"}

SHOT_COLUMNS = ["Minuto", "Time", "Jogador", "Resultado", "xG", "Tipo", "Parte do corpo"]
LINEUP_COLUMNS = ["Nº", "Jogador", "Posição", "Situação"]


def _missing(value) -> bool:
    return value is None or bool(pd.isna(value))


def match_label(row) -> str:
    """'Argentina x France — Final (18/12/2022)', com aviso quando a partida ainda não tem eventos."""
    label = f"{row['home_team_name']} x {row['away_team_name']} — {row['competition_stage']} ({row['match_date']:%d/%m/%Y})"
    return label if row["has_events"] else f"{label} · sem eventos carregados"


def score_text(row) -> str:
    """O placar oficial da fonte, que NÃO inclui a disputa de pênaltis (D08)."""
    return f"{row['home_score']} – {row['away_score']}"


def shootout_text(row) -> str | None:
    if not row["has_events"] or _missing(row["home_penalties"]):
        return None
    return f"Disputa de pênaltis: {row['home_team_name']} {int(row['home_penalties'])} – {int(row['away_penalties'])} {row['away_team_name']}"


def format_value(value, kind: str) -> str:
    """Valores ausentes viram '–'; decimais usam vírgula."""
    if _missing(value):
        return MISSING_TEXT
    if kind == "int":
        return str(int(value))
    digits = {"dec2": 2, "dec3": 3, "pct": 1}[kind]
    return f"{float(value):.{digits}f}".replace(".", ",")


def comparison_table(stats: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por métrica, uma coluna por time (mandante primeiro), tudo já formatado como texto."""
    ordered = stats.sort_values("is_home", ascending=False)
    table = pd.DataFrame({
        team["team_name"]: [format_value(team[column], kind) for column, _, kind in STATS_ROWS]
        for _, team in ordered.iterrows()
    }, index=[label for _, label, _ in STATS_ROWS])
    return table


def lineup_table(lineups: pd.DataFrame, team_id: int) -> pd.DataFrame:
    """Titulares, depois reservas que entraram, depois quem não entrou; dentro de cada grupo, por número da camisa."""
    team = lineups[lineups["team_id"] == team_id].copy()
    team["_group"] = team.apply(lambda r: 0 if r["is_starter"] else (1 if r["played"] else 2), axis=1)
    team = team.sort_values(["_group", "jersey_number"], na_position="last")
    situation = {0: "Titular", 1: "Entrou", 2: "Não entrou"}
    return pd.DataFrame({
        "Nº": team["jersey_number"].tolist(),
        "Jogador": [r["player_nickname"] if not _missing(r["player_nickname"]) else r["player_name"] for _, r in team.iterrows()],
        "Posição": [MISSING_TEXT if _missing(v) else v for v in team["first_position"]],
        "Situação": [situation[g] for g in team["_group"]],
    }, columns=LINEUP_COLUMNS)


INCIDENT_COLUMNS = ["Minuto", "Time", "Incidente", "Jogador", "Detalhe"]
CARDS = {"Yellow Card": "Cartão amarelo", "Second Yellow": "Segundo amarelo", "Red Card": "Cartão vermelho"}
SUBSTITUTION_REASONS = {"Tactical": "tática", "Injury": "lesão"}


def incident_table(timeline: pd.DataFrame) -> pd.DataFrame:
    """Gols, cartões e substituições em ordem cronológica (período, idx), em português.

    Substituição: 'Jogador' é quem saiu e o detalhe diz quem entrou. Gol contra não tem jogador (a fonte não o informa).
    """
    ordered = timeline.sort_values(["period", "idx"])
    rows = []
    for _, r in ordered.iterrows():
        kind, detail = r["incident_type"], r["detail"]
        player = MISSING_TEXT if _missing(r["player_name"]) else r["player_name"]
        if kind == "Goal":
            label, text = "Gol", "Pênalti" if detail == "Penalty" else ""
        elif kind == "Own Goal":
            label, text = "Gol contra (a favor)", "autor não informado pela fonte"
        elif kind == "Card":
            label, text = CARDS.get(detail, detail), ""
        else:
            reason = "" if _missing(detail) else f" ({SUBSTITUTION_REASONS.get(detail, detail)})"
            label, text = "Substituição", f"Entra {r['related_player_name']}{reason}"
        rows.append((r["rotulo"], r["team_name"], label, player, text))
    return pd.DataFrame(rows, columns=INCIDENT_COLUMNS)


PASS_KINDS = {
    "tentados": "Todos os passes tentados",
    "completos": "Completos",
    "incompletos": "Incompletos",
    "progressivos": "Progressivos (OddVision v1)",
    "para_a_area": "Para a área",
}


def filter_passes(passes: pd.DataFrame, team_id: int, player_id: int | None = None, kind: str = "tentados") -> pd.DataFrame:
    """Passes tentados (M4) de um time, opcionalmente de um jogador, no recorte escolhido (chaves de PASS_KINDS)."""
    if kind not in PASS_KINDS:
        raise ValueError(f"tipo de passe desconhecido: {kind}")
    selected = passes[(passes["team_id"] == team_id) & passes["is_tentado"]]
    if player_id is not None:
        selected = selected[selected["player_id"] == player_id]
    column = {"completos": "is_complete", "progressivos": "is_progressivo", "para_a_area": "is_passe_para_area"}.get(kind)
    if column:
        selected = selected[selected[column]]
    elif kind == "incompletos":
        selected = selected[~selected["is_complete"]]
    return selected


def shot_table(shots: pd.DataFrame) -> pd.DataFrame:
    """Finalizações em ordem cronológica (período, idx), com a disputa de pênaltis por último e textos em português."""
    ordered = shots.sort_values(["period", "idx"])
    return pd.DataFrame({
        "Minuto": ["Disputa" if r["is_shootout"] else r["rotulo"] for _, r in ordered.iterrows()],
        "Time": ordered["team_name"].tolist(),
        "Jogador": ordered["player_name"].tolist(),
        "Resultado": [OUTCOMES.get(v, v) for v in ordered["outcome"]],
        "xG": ordered["statsbomb_xg"].tolist(),
        "Tipo": [SHOT_TYPES.get(v, v) for v in ordered["shot_type"]],
        "Parte do corpo": [MISSING_TEXT if _missing(v) else BODY_PARTS.get(v, v) for v in ordered["body_part"]],
    }, columns=SHOT_COLUMNS)
