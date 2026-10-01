"""P2: competitions.json e matches/{competição}/{temporada}.json -> competitions, teams e matches.

Cada função devolve um DataFrame com as colunas NA ORDEM de core.* (docs/data_dictionary.md). As
colunas têm dtype `object` de propósito: guardam os objetos Python exatos (date, time, datetime,
int, str, dict, None) que viram os tipos SQL, sem a conversão de nulos para NaN do pandas.
Campos obrigatórios ausentes viram `TransformError` com a partida e o campo, antes de qualquer banco.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any

import pandas as pd

from oddvision.transform.common import (
    MISSING,
    TransformError,
    bool_field,
    extract_extra,
    get_path,
    int_field,
    object_frame,
    optional_int,
    optional_text,
    parse_field,
    text_field,
)

COMPETITION_COLUMNS = (
    "competition_id", "season_id", "competition_name", "season_name", "country_name",
    "competition_gender", "competition_youth", "competition_international", "extra",
)
TEAM_COLUMNS = ("team_id", "team_name", "team_gender", "country_name")
MATCH_COLUMNS = (
    "match_id", "competition_id", "season_id", "match_date", "kick_off", "home_team_id", "away_team_id",
    "home_score", "away_score", "match_week", "competition_stage", "stadium_name", "referee_name",
    "match_status", "data_version", "shot_fidelity_version", "xy_fidelity_version", "last_updated", "extra",
)

# Caminhos do JSON que viram colunas (de matches OU das tabelas que saem do mesmo objeto: competitions e
# teams). O que sobra vai para matches.extra: técnicos, grupos, ids de estádio/árbitro, campos de 360…
COMPETITION_MAPPED_PATHS = [
    (key,) for key in (
        "competition_id", "season_id", "competition_name", "season_name", "country_name",
        "competition_gender", "competition_youth", "competition_international",
    )
]
MATCH_MAPPED_PATHS = [
    ("match_id",), ("match_date",), ("kick_off",), ("home_score",), ("away_score",), ("match_week",),
    ("match_status",), ("last_updated",),
    ("competition", "competition_id"), ("competition", "competition_name"), ("competition", "country_name"),
    ("season", "season_id"), ("season", "season_name"),
    ("competition_stage", "name"), ("stadium", "name"), ("referee", "name"),
    ("metadata", "data_version"), ("metadata", "shot_fidelity_version"), ("metadata", "xy_fidelity_version"),
] + [
    (f"{side}_team", key)
    for side in ("home", "away")
    for key in (f"{side}_team_id", f"{side}_team_name", f"{side}_team_gender")
] + [(f"{side}_team", "country", "name") for side in ("home", "away")]


# ----------------------------------------------------------------------------- leitura com validação

def _naive_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("tem fuso horário; esperado timestamp sem fuso")
    return parsed


# ----------------------------------------------------------------------------- competitions

def competitions_frame(items: Sequence[dict], competition_id: int, season_id: int) -> pd.DataFrame:
    """A linha de core.competitions para o par (competição, temporada) pedido."""
    selected = [
        item for item in items
        if get_path(item, "competition_id") == competition_id and get_path(item, "season_id") == season_id
    ]
    if not selected:
        raise TransformError(f"competição ({competition_id}, {season_id}) não encontrada em competitions.json")
    if len(selected) > 1:
        raise TransformError(f"competição ({competition_id}, {season_id}) aparece mais de uma vez em competitions.json")

    item, context = selected[0], f"competição ({competition_id}, {season_id})"
    row = {
        "competition_id": competition_id,
        "season_id": season_id,
        "competition_name": text_field(item, ("competition_name",), context),
        "season_name": text_field(item, ("season_name",), context),
        "country_name": optional_text(item, ("country_name",), context),
        "competition_gender": text_field(item, ("competition_gender",), context),
        "competition_youth": bool_field(item, ("competition_youth",), context),
        "competition_international": bool_field(item, ("competition_international",), context),
        "extra": extract_extra(item, COMPETITION_MAPPED_PATHS),
    }
    return object_frame([row], COMPETITION_COLUMNS)


# ----------------------------------------------------------------------------- teams

def _match_context(match: Any, position: int) -> str:
    match_id = get_path(match, "match_id")
    return f"partida {match_id if match_id is not MISSING else f'(posição {position})'}"


def teams_frame(matches: Sequence[dict]) -> pd.DataFrame:
    """Um time por linha, a partir dos objetos home_team e away_team das partidas, ordenado por team_id.

    O mesmo team_id com atributos diferentes entre partidas é um erro (não escolhemos um em silêncio).
    """
    teams: dict[int, tuple] = {}
    for position, match in enumerate(matches):
        context = _match_context(match, position)
        for side in ("home", "away"):
            key = f"{side}_team"
            if not isinstance(get_path(match, key), dict):
                raise TransformError(f"{context}: campo obrigatório ausente ou nulo: {key}")
            team_id = int_field(match, (key, f"{key}_id"), context)
            attributes = (
                text_field(match, (key, f"{key}_name"), context),
                optional_text(match, (key, f"{key}_gender"), context),
                optional_text(match, (key, "country", "name"), context),
            )
            if teams.setdefault(team_id, attributes) != attributes:
                raise TransformError(
                    f"time {team_id}: atributos conflitantes entre partidas: {teams[team_id]} x {attributes}"
                )
    rows = [
        {"team_id": team_id, "team_name": name, "team_gender": gender, "country_name": country}
        for team_id, (name, gender, country) in sorted(teams.items())
    ]
    return object_frame(rows, TEAM_COLUMNS)


# ----------------------------------------------------------------------------- matches

def matches_frame(matches: Sequence[dict], competition_id: int, season_id: int) -> pd.DataFrame:
    """Uma partida por linha, ordenada por match_id. Todas devem pertencer a (competition_id, season_id)."""
    if not matches:
        raise TransformError("matches: nenhuma partida encontrada no arquivo")

    rows, seen = [], set()
    for position, match in enumerate(matches):
        context = _match_context(match, position)
        match_id = int_field(match, ("match_id",), context)
        if match_id in seen:
            raise TransformError(f"match_id repetido no arquivo de partidas: {match_id}")
        seen.add(match_id)

        found = (int_field(match, ("competition", "competition_id"), context), int_field(match, ("season", "season_id"), context))
        if found != (competition_id, season_id):
            raise TransformError(
                f"{context}: pertence à competição {found}, mas o esperado é ({competition_id}, {season_id})"
            )

        kick_off = optional_text(match, ("kick_off",), context)
        last_updated = optional_text(match, ("last_updated",), context)
        rows.append({
            "match_id": match_id,
            "competition_id": competition_id,
            "season_id": season_id,
            "match_date": parse_field(text_field(match, ("match_date",), context), date.fromisoformat, "match_date", context),
            "kick_off": None if kick_off is None else parse_field(kick_off, time.fromisoformat, "kick_off", context),
            "home_team_id": int_field(match, ("home_team", "home_team_id"), context),
            "away_team_id": int_field(match, ("away_team", "away_team_id"), context),
            "home_score": int_field(match, ("home_score",), context),
            "away_score": int_field(match, ("away_score",), context),
            "match_week": optional_int(match, ("match_week",), context),
            "competition_stage": optional_text(match, ("competition_stage", "name"), context),
            "stadium_name": optional_text(match, ("stadium", "name"), context),
            "referee_name": optional_text(match, ("referee", "name"), context),
            "match_status": optional_text(match, ("match_status",), context),
            "data_version": optional_text(match, ("metadata", "data_version"), context),
            "shot_fidelity_version": optional_text(match, ("metadata", "shot_fidelity_version"), context),
            "xy_fidelity_version": optional_text(match, ("metadata", "xy_fidelity_version"), context),
            "last_updated": (
                None if last_updated is None else parse_field(last_updated, _naive_datetime, "last_updated", context)
            ),
            "extra": extract_extra(match, MATCH_MAPPED_PATHS),
        })
    return object_frame(sorted(rows, key=lambda r: r["match_id"]), MATCH_COLUMNS)
