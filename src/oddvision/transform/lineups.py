"""P3: lineups/{match_id}.json -> core.lineups e core.players.

`lineups_frame` transforma UMA partida. `resolve_players` olha TODOS os arquivos de escalação para
decidir, uma vez só, os atributos de cada jogador (a fonte às vezes grafa o mesmo jogador de formas
diferentes em partidas diferentes). Funções puras, como o resto de `transform/`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from oddvision.transform.common import (
    TransformError,
    extract_extra,
    get_path,
    int_field,
    object_frame,
    optional_int,
    optional_text,
    parse_field,
    text_field,
)

LINEUP_COLUMNS = (
    "match_id", "team_id", "player_id", "jersey_number", "is_starter", "played", "first_position", "extra",
)
PLAYER_COLUMNS = ("player_id", "player_name", "player_nickname", "country_name")

# Caminhos do jogador que viram colunas (de lineups ou de players). `positions` NÃO sai do extra: é a
# fonte de `played`, `is_starter` e `first_position`, mas fica inteira (com os intervalos), na ordem original.
LINEUP_MAPPED_PATHS = [
    ("player_id",), ("jersey_number",), ("player_name",), ("player_nickname",), ("country", "name"),
]
STARTING_XI = "Starting XI"
PLAYER_ATTRIBUTES = ("player_name", "player_nickname", "country_name")


# ----------------------------------------------------------------------------- uma partida

def _clock_seconds(value: str) -> int:
    """'MM:SS' -> segundos. Os minutos passam de 99 na prorrogação ('120:48')."""
    minutes, seconds = value.split(":")
    return int(minutes) * 60 + int(seconds)


def _sorted_positions(player: Mapping, context: str) -> list[dict]:
    """As posições do jogador em ordem cronológica: (período, relógio). A fonte nem sempre as ordena (A1).

    A ordenação é estável: posições empatadas ficam na ordem em que a fonte as listou.
    """
    positions = get_path(player, "positions")
    if not isinstance(positions, list):
        raise TransformError(f"{context}: positions deve ser uma lista")
    keyed = []
    for position in positions:
        period = int_field(position, ("from_period",), context)
        seconds = parse_field(text_field(position, ("from",), context), _clock_seconds, "from", context)
        keyed.append(((period, seconds), position))
    keyed.sort(key=lambda item: item[0])
    return [position for _, position in keyed]


def lineups_frame(match_id: int, teams: Sequence[dict]) -> pd.DataFrame:
    """Uma linha por jogador relacionado (inclusive quem não entrou), ordenada por (time, jogador).

    `match_id` vem do NOME do arquivo: o JSON de escalações não o contém.
    """
    context = f"partida {match_id}"
    if not isinstance(teams, list) or len(teams) != 2:
        size = len(teams) if isinstance(teams, list) else type(teams).__name__
        raise TransformError(f"{context}: a escalação deve ter exatamente 2 times, tem {size}")

    rows, team_ids, seen_players = [], set(), set()
    for team in teams:
        team_id = int_field(team, ("team_id",), context)
        if team_id in team_ids:
            raise TransformError(f"{context}: time repetido na escalação: {team_id}")
        team_ids.add(team_id)
        lineup = get_path(team, "lineup")
        if not isinstance(lineup, list):
            raise TransformError(f"{context}, time {team_id}: lineup deve ser uma lista")

        for player in lineup:
            player_id = int_field(player, ("player_id",), f"{context}, time {team_id}")
            player_context = f"{context}, jogador {player_id}"
            if player_id in seen_players:
                raise TransformError(f"{player_context}: o jogador aparece mais de uma vez na escalação")
            seen_players.add(player_id)

            positions = _sorted_positions(player, player_context)
            first = positions[0] if positions else None
            rows.append({
                "match_id": match_id,
                "team_id": team_id,
                "player_id": player_id,
                "jersey_number": optional_int(player, ("jersey_number",), player_context),
                # Titular: a primeira posição CRONOLÓGICA começou como 'Starting XI' (confirmado no Passo 2).
                "is_starter": first is not None and get_path(first, "start_reason") == STARTING_XI,
                "played": first is not None,
                "first_position": None if first is None else optional_text(first, ("position",), player_context),
                "extra": extract_extra(player, LINEUP_MAPPED_PATHS),
            })
    rows.sort(key=lambda r: (r["team_id"], r["player_id"]))
    return object_frame(rows, LINEUP_COLUMNS)


# ----------------------------------------------------------------------------- jogadores (todos os arquivos)

@dataclass(frozen=True)
class AttributeConflict:
    """Um atributo de um jogador que aparece com valores diferentes entre arquivos."""

    player_id: int
    attribute: str
    counts: dict  # valor -> nº de arquivos em que apareceu (None = o arquivo não informa o atributo)
    chosen: Any  # o valor gravado em core.players


def _choose(counts: Counter) -> Any:
    """O valor mais frequente. Nulo não compete com um valor real; empate fica com a ordem alfabética."""
    candidates = {value: n for value, n in counts.items() if value is not None}
    if not candidates:
        return None
    best = max(candidates.values())
    return min(value for value, n in candidates.items() if n == best)


def resolve_players(lineups_by_match: Mapping[int, Sequence[dict]]) -> tuple[pd.DataFrame, list[AttributeConflict]]:
    """Uma linha por jogador de TODAS as escalações, e os conflitos encontrados.

    Regra (decidida pelo autor): para cada atributo, vale o valor mais frequente entre os arquivos.
    Olhar todos os arquivos, e não só as partidas carregadas, mantém o resultado estável quando mais
    partidas forem carregadas. O resultado não depende da ordem dos arquivos.
    """
    observed: dict[int, dict[str, Counter]] = defaultdict(lambda: {a: Counter() for a in PLAYER_ATTRIBUTES})
    for match_id in sorted(lineups_by_match):
        context = f"partida {match_id}"
        teams = lineups_by_match[match_id]
        if not isinstance(teams, list):
            raise TransformError(f"{context}: a escalação deve ser uma lista de times")
        for team in teams:
            lineup = get_path(team, "lineup")
            if not isinstance(lineup, list):
                raise TransformError(f"{context}: lineup deve ser uma lista")
            for player in lineup:
                player_id = int_field(player, ("player_id",), context)
                player_context = f"{context}, jogador {player_id}"
                counts = observed[player_id]
                counts["player_name"][text_field(player, ("player_name",), player_context)] += 1
                counts["player_nickname"][optional_text(player, ("player_nickname",), player_context)] += 1
                counts["country_name"][optional_text(player, ("country", "name"), player_context)] += 1

    rows, conflicts = [], []
    for player_id in sorted(observed):
        chosen = {}
        for attribute in PLAYER_ATTRIBUTES:
            counts = observed[player_id][attribute]
            chosen[attribute] = _choose(counts)
            if len(counts) > 1:
                conflicts.append(AttributeConflict(player_id, attribute, dict(counts), chosen[attribute]))
        rows.append({"player_id": player_id, **chosen})
    conflicts.sort(key=lambda c: (c.player_id, c.attribute))
    return object_frame(rows, PLAYER_COLUMNS), conflicts
