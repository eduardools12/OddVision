"""P4: events/{match_id}.json -> core.events (o núcleo do modelo).

Cada evento vira uma linha com as colunas comuns tipadas (UUID, INTERVAL, x/y em DOUBLE PRECISION…) e o
`extra JSONB` com o que a fonte traz e o modelo ainda não usa (D07). Os objetos `shot`, `pass`, `carry` e
`substitution`, e os cartões, saem do `extra`: vão para as tabelas próprias no Passo 8.
Função pura, como o resto de `transform/`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import timedelta

import pandas as pd

from oddvision.transform.common import (
    MISSING,
    TransformError,
    extract_extra,
    float_value,
    get_path,
    int_field,
    object_frame,
    optional_int,
    optional_text,
    parse_field,
    text_field,
)

EVENT_COLUMNS = (
    "event_id", "match_id", "idx", "period", "ts_in_period", "minute", "second", "type_name", "team_id",
    "player_id", "position_name", "possession", "possession_team_id", "play_pattern", "x", "y", "duration",
    "under_pressure", "extra",
)

# O que sai do `extra`. Uma chave sai por um destes motivos:
#  - virou coluna de core.events;
#  - o nome já está na dimensão que a FK representa (team, player, possession_team: core.teams e core.players);
#  - é o objeto de uma tabela própria (Passo 8) ou o cartão dentro de foul_committed / bad_behaviour.
# Ficam no extra, entre outros: type.id, position.id, play_pattern.id (ids de domínio), related_events, tactics,
# counterpress, off_camera, out e os objetos dos tipos sem tabela (duel, goalkeeper, clearance, dribble…).
EVENT_MAPPED_PATHS = [
    ("id",), ("index",), ("period",), ("timestamp",), ("minute",), ("second",), ("possession",), ("location",),
    ("duration",), ("under_pressure",),
    ("type", "name"), ("position", "name"), ("play_pattern", "name"),
    ("team", "id"), ("team", "name"), ("player", "id"), ("player", "name"),
    ("possession_team", "id"), ("possession_team", "name"),
    ("shot",), ("pass",), ("carry",), ("substitution",),
    ("foul_committed", "card"), ("bad_behaviour", "card"),
]

_TIMESTAMP = re.compile(r"(\d{2,}):([0-5]\d):([0-5]\d)(?:\.(\d{1,6}))?")
PITCH_X, PITCH_Y = 120.0, 80.0  # o campo do StatsBomb


def _interval(value: str) -> timedelta:
    """'HH:MM:SS.mmm' -> timedelta, sem passar por ponto flutuante (a fração são dígitos inteiros)."""
    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError("esperado HH:MM:SS ou HH:MM:SS.mmm")
    hours, minutes, seconds, fraction = match.groups()
    microseconds = int(fraction.ljust(6, "0")) if fraction else 0
    return timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds), microseconds=microseconds)


def _location(event, context: str) -> tuple[float | None, float | None]:
    value = get_path(event, "location")
    if value is MISSING:
        return None, None
    if not isinstance(value, list) or len(value) != 2:
        raise TransformError(f"{context}: location deve ser [x, y], recebido {value!r}")
    x, y = (float_value(v, "location", context) for v in value)
    if not (0 <= x <= PITCH_X and 0 <= y <= PITCH_Y):
        raise TransformError(f"{context}: location fora do campo (0-{PITCH_X:g}, 0-{PITCH_Y:g}): {value!r}")
    return x, y


def _bounded(value: int, low: int, high: int, field: str, context: str) -> int:
    if not low <= value <= high:
        raise TransformError(f"{context}: {field} deve estar entre {low} e {high}, recebido {value}")
    return value


def events_frame(match_id: int, events: Sequence[dict]) -> pd.DataFrame:
    """Um evento por linha, ordenado por `idx`. `match_id` vem do NOME do arquivo (o JSON não o contém).

    Faixas que o banco também recusa (period, second, x, y) são conferidas aqui, com o id do evento:
    um erro em 234 mil eventos precisa dizer QUAL evento.
    """
    if not isinstance(events, list):
        raise TransformError(f"partida {match_id}: o arquivo de eventos deve ser uma lista")
    if not events:
        raise TransformError(f"partida {match_id}: nenhum evento no arquivo")

    rows, seen_ids, seen_indexes = [], set(), set()
    for position, event in enumerate(events):
        raw_id = get_path(event, "id")
        context = f"partida {match_id}, evento {raw_id if raw_id is not MISSING else f'(posição {position})'}"
        event_id = parse_field(text_field(event, ("id",), context), uuid.UUID, "id", context)
        if event_id in seen_ids:
            raise TransformError(f"partida {match_id}: id repetido: {event_id}")
        seen_ids.add(event_id)

        idx = int_field(event, ("index",), context)
        if idx in seen_indexes:
            raise TransformError(f"partida {match_id}: index repetido: {idx}")
        seen_indexes.add(idx)

        x, y = _location(event, context)
        duration = get_path(event, "duration")
        under_pressure = get_path(event, "under_pressure")
        if under_pressure is not MISSING and not isinstance(under_pressure, bool):
            raise TransformError(f"{context}: under_pressure deve ser bool, recebido {under_pressure!r}")

        rows.append({
            "event_id": event_id,
            "match_id": match_id,
            "idx": idx,
            "period": _bounded(int_field(event, ("period",), context), 1, 5, "period", context),
            "ts_in_period": parse_field(text_field(event, ("timestamp",), context), _interval, "timestamp", context),
            "minute": int_field(event, ("minute",), context),
            "second": _bounded(int_field(event, ("second",), context), 0, 59, "second", context),
            "type_name": text_field(event, ("type", "name"), context),
            "team_id": int_field(event, ("team", "id"), context),
            "player_id": optional_int(event, ("player", "id"), context),
            "position_name": optional_text(event, ("position", "name"), context),
            "possession": int_field(event, ("possession",), context),
            "possession_team_id": int_field(event, ("possession_team", "id"), context),
            "play_pattern": text_field(event, ("play_pattern", "name"), context),
            "x": x,
            "y": y,
            "duration": None if duration is MISSING else float_value(duration, "duration", context),
            "under_pressure": under_pressure is True,  # a fonte só traz a chave quando é verdadeira
            "extra": extract_extra(event, EVENT_MAPPED_PATHS),
        })
    rows.sort(key=lambda r: r["idx"])
    return object_frame(rows, EVENT_COLUMNS)
