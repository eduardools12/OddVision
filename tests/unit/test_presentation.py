"""Funções puras de apresentação da página da partida (sem banco e sem Streamlit)."""

import datetime as dt

import pandas as pd
import pytest

from oddvision import presentation as p


def header(**overrides):
    row = dict(match_id=1, match_date=dt.date(2022, 12, 18), competition_stage="Final", home_team_id=779, home_team_name="Argentina",
               away_team_id=771, away_team_name="France", home_score=3, away_score=3, has_events=True, home_goals=3, away_goals=3,
               score_matches_events=True, home_penalties=4, away_penalties=2)
    row.update(overrides)
    return row


# --------------------------------------------------------------------------- rótulos e placar

def test_match_label_has_teams_stage_and_date():
    assert p.match_label(header()) == "Argentina x France — Final (18/12/2022)"


def test_match_label_flags_a_match_without_events():
    assert p.match_label(header(has_events=False)).endswith("· sem eventos carregados")


def test_score_text_uses_the_official_score_without_the_shootout():
    assert p.score_text(header()) == "3 – 3"


def test_shootout_text_is_separate_and_absent_when_there_was_no_shootout():
    assert p.shootout_text(header()) == "Disputa de pênaltis: Argentina 4 – 2 France"
    assert p.shootout_text(header(home_penalties=None, away_penalties=None)) is None


def test_a_match_without_events_has_no_shootout_text_even_if_the_columns_are_null():
    assert p.shootout_text(header(has_events=False, home_penalties=None, away_penalties=None)) is None


# --------------------------------------------------------------------------- formatação de valores

@pytest.mark.parametrize("value, kind, text", [
    (3, "int", "3"), (3.0, "int", "3"), (0, "int", "0"),
    (2.7583, "dec2", "2,76"), (0.1039, "dec3", "0,104"), (81.3923, "pct", "81,4"),
    (None, "int", "–"), (float("nan"), "dec2", "–"), (pd.NA, "pct", "–"),
])
def test_format_value(value, kind, text):
    assert p.format_value(value, kind) == text


# --------------------------------------------------------------------------- comparativo

def stats_frame():
    return pd.DataFrame([
        dict(team_name="Argentina", is_home=True, gols=3, finalizacoes=20, finalizacoes_no_alvo=10, xg=2.7583, npxg=1.9748,
             npxg_por_finalizacao_sem_penalti=0.1039, passes_tentados=661, passes_completos=538, pct_acerto_passes=81.39,
             passes_progressivos=56, conducoes_progressivas=30, passes_para_area=7),
        dict(team_name="France", is_home=False, gols=3, finalizacoes=10, finalizacoes_no_alvo=5, xg=2.2726, npxg=0.7056,
             npxg_por_finalizacao_sem_penalti=None, passes_tentados=544, passes_completos=414, pct_acerto_passes=76.1,
             passes_progressivos=39, conducoes_progressivas=31, passes_para_area=3)])


def test_comparison_table_has_one_row_per_metric_and_one_column_per_team_home_first():
    table = p.comparison_table(stats_frame().iloc[::-1])          # mesmo com a ordem de entrada trocada
    assert list(table.columns) == ["Argentina", "France"]
    assert table.loc["Gols"].tolist() == ["3", "3"]
    assert table.loc["xG"].tolist() == ["2,76", "2,27"]
    assert table.loc["Acerto de passes (%)"].tolist() == ["81,4", "76,1"]
    assert table.loc["npxG por finalização (sem pênaltis)"].tolist() == ["0,104", "–"]


def test_the_progressive_metrics_are_labelled_as_an_oddvision_convention():
    labels = list(p.comparison_table(stats_frame()).index)
    assert "Passes progressivos (OddVision v1)" in labels
    assert "Conduções progressivas (OddVision v1)" in labels


def test_comparison_table_covers_the_seven_metrics_of_the_team_stats():
    covered = {column for column, _, _ in p.STATS_ROWS}
    assert covered == {"gols", "finalizacoes", "finalizacoes_no_alvo", "xg", "npxg", "npxg_por_finalizacao_sem_penalti",
                       "passes_tentados", "passes_completos", "pct_acerto_passes", "passes_progressivos",
                       "conducoes_progressivas", "passes_para_area"}


# --------------------------------------------------------------------------- escalações

def lineup_frame():
    return pd.DataFrame([
        dict(team_id=1, player_name="Reserva Que Entrou", player_nickname=None, jersey_number=20, first_position="Left Wing", is_starter=False, played=True),
        dict(team_id=1, player_name="Goleiro Titular", player_nickname="Goleiro", jersey_number=1, first_position="Goalkeeper", is_starter=True, played=True),
        dict(team_id=1, player_name="Reserva Fora", player_nickname=None, jersey_number=22, first_position=None, is_starter=False, played=False),
        dict(team_id=1, player_name="Atacante Titular", player_nickname=None, jersey_number=9, first_position="Center Forward", is_starter=True, played=True),
        dict(team_id=2, player_name="De Outro Time", player_nickname=None, jersey_number=1, first_position="Goalkeeper", is_starter=True, played=True)])


def test_lineup_table_orders_starters_then_substitutes_who_played_then_the_unused():
    table = p.lineup_table(lineup_frame(), team_id=1)
    assert table["Jogador"].tolist() == ["Goleiro", "Atacante Titular", "Reserva Que Entrou", "Reserva Fora"]
    assert table["Situação"].tolist() == ["Titular", "Titular", "Entrou", "Não entrou"]
    assert table["Nº"].tolist() == [1, 9, 20, 22]
    assert "De Outro Time" not in table["Jogador"].tolist()


def test_lineup_table_shows_the_nickname_when_there_is_one():
    assert p.lineup_table(lineup_frame(), team_id=1)["Jogador"].iloc[0] == "Goleiro"


# --------------------------------------------------------------------------- incidentes

def incidents_frame():
    return pd.DataFrame([
        dict(period=2, idx=300, rotulo="50'", team_name="Fora", incident_type="Substitution", detail="Tactical", player_name="Sai", related_player_name="Entra"),
        dict(period=1, idx=20, rotulo="23'", team_name="Casa", incident_type="Goal", detail="Penalty", player_name="Artilheiro", related_player_name=None),
        dict(period=1, idx=30, rotulo="30'", team_name="Fora", incident_type="Card", detail="Second Yellow", player_name="Zagueiro", related_player_name=None),
        dict(period=1, idx=40, rotulo="31'", team_name="Casa", incident_type="Own Goal", detail=None, player_name=None, related_player_name=None),
        dict(period=1, idx=50, rotulo="40'", team_name="Casa", incident_type="Goal", detail=None, player_name="Outro", related_player_name=None)])


def test_incident_table_is_chronological_and_translated():
    table = p.incident_table(incidents_frame())
    assert table["Minuto"].tolist() == ["23'", "30'", "31'", "40'", "50'"]
    assert table["Incidente"].tolist() == ["Gol", "Segundo amarelo", "Gol contra (a favor)", "Gol", "Substituição"]
    assert table["Detalhe"].tolist() == ["Pênalti", "", "autor não informado pela fonte", "", "Entra Entra (tática)"]


def test_the_own_goal_has_no_player_and_the_substitution_shows_who_left():
    table = p.incident_table(incidents_frame())
    assert table["Jogador"].tolist() == ["Artilheiro", "Zagueiro", "–", "Outro", "Sai"]


def test_incident_table_of_an_empty_frame_has_the_columns_and_no_rows():
    table = p.incident_table(incidents_frame().iloc[0:0])
    assert list(table.columns) == p.INCIDENT_COLUMNS and len(table) == 0


# --------------------------------------------------------------------------- finalizações

def shots_frame():
    return pd.DataFrame([
        dict(rotulo="23'", team_name="Argentina", player_name="Messi", outcome="Goal", shot_type="Penalty", statsbomb_xg=0.7835, body_part="Right Foot", technique="Normal", is_shootout=False, period=1, idx=10),
        dict(rotulo=None, team_name="France", player_name="Mbappé", outcome="Saved", shot_type="Penalty", statsbomb_xg=0.7835, body_part="Right Foot", technique="Normal", is_shootout=True, period=5, idx=900),
        dict(rotulo="45+2'", team_name="France", player_name="Giroud", outcome="Off T", shot_type="Open Play", statsbomb_xg=0.0312, body_part="Head", technique="Normal", is_shootout=False, period=1, idx=5)])


def test_shot_table_is_chronological_translated_and_marks_the_shootout():
    table = p.shot_table(shots_frame())
    # ordem cronológica por (período, idx), não pelo texto do rótulo: o idx 5 vem antes do idx 10; a disputa fica por último
    assert table["Minuto"].tolist() == ["45+2'", "23'", "Disputa"]
    assert table["Jogador"].tolist() == ["Giroud", "Messi", "Mbappé"]
    assert table["Resultado"].tolist() == ["Para fora", "Gol", "Defendida"]
    assert table["Tipo"].tolist() == ["Jogo corrido", "Pênalti", "Pênalti"]


def test_shot_table_keeps_unknown_values_untranslated():
    frame = shots_frame()
    frame.loc[0, "outcome"] = "Something New"
    assert "Something New" in p.shot_table(frame)["Resultado"].tolist()


def test_shot_table_of_an_empty_frame_has_the_columns_and_no_rows():
    table = p.shot_table(shots_frame().iloc[0:0])
    assert len(table) == 0 and "Minuto" in table.columns
