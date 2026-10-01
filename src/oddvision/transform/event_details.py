"""P5: os objetos específicos dos eventos -> core.shots, passes, carries, cards e substitutions.

Cada tabela é 1:1 com os eventos do seu tipo (a chave é o `event_id` do evento, já em core.events). O que a
fonte traz dentro do objeto e o modelo não usa vai para o `extra` da tabela (shots e passes, D07). As tabelas
`carries`, `cards` e `substitutions` NÃO têm `extra`: se a fonte trouxer uma chave que elas não modelam, a
transformação FALHA em vez de perder o dado em silêncio. Funções puras, como o resto de `transform/`.

Duas proteções contra perda silenciosa, porque `events.extra` já não guarda estes objetos (D25):
- um objeto `shot`/`pass`/`carry`/`substitution` em um evento de outro tipo é erro;
- um evento do tipo sem o seu objeto é erro.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence

import pandas as pd

from oddvision.transform.common import (
    MISSING,
    TransformError,
    extract_extra,
    float_value,
    get_path,
    int_field,
    object_frame,
    optional_float,
    optional_int,
    optional_text,
    parse_field,
    text_field,
)

SHOT_COLUMNS = (
    "event_id", "statsbomb_xg", "end_x", "end_y", "end_z", "outcome", "shot_type", "body_part", "technique",
    "key_pass_id", "extra",
)
PASS_COLUMNS = (
    "event_id", "recipient_id", "end_x", "end_y", "length", "angle", "height", "pass_type", "body_part", "outcome",
    "is_complete", "is_cross", "is_switch", "is_through_ball", "is_shot_assist", "is_goal_assist", "extra",
)
CARRY_COLUMNS = ("event_id", "end_x", "end_y")
CARD_COLUMNS = ("event_id", "card_type")
SUBSTITUTION_COLUMNS = ("event_id", "player_on_id", "reason")

# O que vira coluna (ou já está numa dimensão: recipient.name, em core.players). O resto fica no `extra`.
# Ficam, entre outros: os ids de domínio (type.id, outcome.id, height.id, body_part.id, technique.id…), o
# objeto `technique` inteiro nos passes, freeze_frame, first_time, assisted_shot_id, aerial_won, deflected…
SHOT_MAPPED_PATHS = [
    ("statsbomb_xg",), ("end_location",), ("key_pass_id",),
    ("outcome", "name"), ("type", "name"), ("body_part", "name"), ("technique", "name"),
]
PASS_MAPPED_PATHS = [
    ("end_location",), ("length",), ("angle",), ("cross",), ("switch",), ("through_ball",), ("shot_assist",),
    ("goal_assist",), ("recipient", "id"), ("recipient", "name"),
    ("height", "name"), ("type", "name"), ("body_part", "name"), ("outcome", "name"),
]
PITCH_X, PITCH_Y = 120.0, 80.0
CARD_PARENTS = ("foul_committed", "bad_behaviour")
_OBJECT_TYPES = {"shot": "Shot", "pass": "Pass", "carry": "Carry", "substitution": "Substitution"}


# ----------------------------------------------------------------------------- utilitários

def _context(match_id: int, event: dict, position: int) -> str:
    event_id = get_path(event, "id")
    return f"partida {match_id}, evento {event_id if event_id is not MISSING else f'(posição {position})'}"


def _event_id(event: dict, context: str) -> uuid.UUID:
    return parse_field(text_field(event, ("id",), context), uuid.UUID, "id", context)


def _sorted_by_index(events: Sequence[dict]) -> list[tuple[int, dict]]:
    """(posição, evento), na ordem de `index` (a mesma ordem das linhas de core.events)."""
    indexed = list(enumerate(events))
    indexed.sort(key=lambda item: get_path(item[1], "index") if isinstance(get_path(item[1], "index"), int) else 0)
    return indexed


def _typed_events(match_id: int, events: Sequence[dict], key: str) -> list[tuple[int, dict, str]]:
    """Os eventos do tipo dono de `key`, com o contexto de erro. Confere as duas proteções contra perda silenciosa."""
    owner, selected = _OBJECT_TYPES[key], []
    for position, event in _sorted_by_index(events):
        context = _context(match_id, event, position)
        type_name = get_path(event, "type", "name")
        has_object = get_path(event, key) is not MISSING
        if has_object and type_name != owner:
            raise TransformError(f"{context}: o objeto '{key}' só pode aparecer em eventos {owner}, mas está em {type_name!r}")
        if type_name == owner:
            if not has_object:
                raise TransformError(f"{context}: evento {owner} sem o objeto '{key}'")
            selected.append((position, event, context))
    return selected


def _end_location(obj: dict, context: str, *, lengths: Iterable[int], bounded: bool) -> tuple[float, float, float | None]:
    value = get_path(obj, "end_location")
    if not isinstance(value, list) or len(value) not in tuple(lengths):
        raise TransformError(f"{context}: end_location deve ter {' ou '.join(map(str, lengths))} números, recebido {value!r}")
    numbers = [float_value(v, "end_location", context) for v in value]
    x, y = numbers[0], numbers[1]
    if bounded and not (0 <= x <= PITCH_X and 0 <= y <= PITCH_Y):
        raise TransformError(f"{context}: end_location fora do campo (0-{PITCH_X:g}, 0-{PITCH_Y:g}): {value!r}")
    return x, y, numbers[2] if len(numbers) == 3 else None


def _flag(obj: dict, key: str, context: str) -> bool:
    """A fonte só traz a chave quando é verdadeira: ausente = False."""
    value = get_path(obj, key)
    if value is MISSING:
        return False
    if not isinstance(value, bool):
        raise TransformError(f"{context}: {key} deve ser bool, recebido {value!r}")
    return value


def _only_keys(obj: dict, allowed: set[str], where: str, context: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise TransformError(
            f"{context}: {where} tem chaves que o modelo não guarda (a tabela não tem extra): {unknown}"
        )


def _frame(rows: list[dict], columns: Iterable[str]) -> pd.DataFrame:
    return object_frame(rows, columns)


# ----------------------------------------------------------------------------- shots

def shots_frame(match_id: int, events: Sequence[dict]) -> pd.DataFrame:
    """core.shots: uma linha por evento Shot. O xG é o do StatsBomb (o OddVision não calcula xG)."""
    ids_in_file = {str(get_path(e, "id")) for e in events}
    rows = []
    for _, event, context in _typed_events(match_id, events, "shot"):
        shot = event["shot"]
        xg = float_value(get_path(shot, "statsbomb_xg"), "statsbomb_xg", context)
        if not 0 <= xg <= 1:
            raise TransformError(f"{context}: statsbomb_xg deve estar entre 0 e 1, recebido {xg}")
        x, y, z = _end_location(shot, context, lengths=(2, 3), bounded=False)
        key_pass = optional_text(shot, ("key_pass_id",), context)
        if key_pass is not None and key_pass not in ids_in_file:
            raise TransformError(f"{context}: key_pass_id aponta para um evento que não está no arquivo: {key_pass}")
        rows.append({
            "event_id": _event_id(event, context),
            "statsbomb_xg": xg,
            "end_x": x,
            "end_y": y,
            "end_z": z,  # só existe quando o chute vai em direção ao gol (nulo em Blocked e Wayward)
            "outcome": text_field(shot, ("outcome", "name"), context),
            "shot_type": text_field(shot, ("type", "name"), context),
            "body_part": optional_text(shot, ("body_part", "name"), context),
            "technique": optional_text(shot, ("technique", "name"), context),
            "key_pass_id": None if key_pass is None else parse_field(key_pass, uuid.UUID, "key_pass_id", context),
            "extra": extract_extra(shot, SHOT_MAPPED_PATHS),
        })
    return _frame(rows, SHOT_COLUMNS)


# ----------------------------------------------------------------------------- passes

def passes_frame(match_id: int, events: Sequence[dict]) -> pd.DataFrame:
    """core.passes: uma linha por evento Pass. `outcome` ausente significa passe completo."""
    rows = []
    for _, event, context in _typed_events(match_id, events, "pass"):
        p = event["pass"]
        x, y, _ = _end_location(p, context, lengths=(2,), bounded=True)
        outcome = None if get_path(p, "outcome") is MISSING else text_field(p, ("outcome", "name"), context)
        rows.append({
            "event_id": _event_id(event, context),
            "recipient_id": optional_int(p, ("recipient", "id"), context),
            "end_x": x,
            "end_y": y,
            "length": optional_float(p, ("length",), context),
            "angle": optional_float(p, ("angle",), context),
            "height": optional_text(p, ("height", "name"), context),
            "pass_type": optional_text(p, ("type", "name"), context),  # nulo = passe regular
            "body_part": optional_text(p, ("body_part", "name"), context),
            "outcome": outcome,
            "is_complete": outcome is None,
            "is_cross": _flag(p, "cross", context),
            "is_switch": _flag(p, "switch", context),
            "is_through_ball": _flag(p, "through_ball", context),
            "is_shot_assist": _flag(p, "shot_assist", context),
            "is_goal_assist": _flag(p, "goal_assist", context),
            "extra": extract_extra(p, PASS_MAPPED_PATHS),
        })
    return _frame(rows, PASS_COLUMNS)


# ----------------------------------------------------------------------------- carries

def carries_frame(match_id: int, events: Sequence[dict]) -> pd.DataFrame:
    """core.carries: uma linha por evento Carry. O objeto carry da fonte só tem end_location."""
    rows = []
    for _, event, context in _typed_events(match_id, events, "carry"):
        carry = event["carry"]
        _only_keys(carry, {"end_location"}, "carry", context)
        x, y, _ = _end_location(carry, context, lengths=(2,), bounded=True)
        rows.append({"event_id": _event_id(event, context), "end_x": x, "end_y": y})
    return _frame(rows, CARRY_COLUMNS)


# ----------------------------------------------------------------------------- cards

def cards_frame(match_id: int, events: Sequence[dict]) -> pd.DataFrame:
    """core.cards: uma linha por cartão, em eventos Foul Committed ou Bad Behaviour (foul_committed.card / bad_behaviour.card)."""
    rows = []
    for position, event in _sorted_by_index(events):
        context = _context(match_id, event, position)
        cards = [(parent, get_path(event, parent, "card")) for parent in CARD_PARENTS]
        cards = [(parent, card) for parent, card in cards if card is not MISSING]
        if not cards:
            continue
        if len(cards) > 1:
            raise TransformError(f"{context}: o evento tem dois cartões ({', '.join(p for p, _ in cards)})")
        parent, card = cards[0]
        if not isinstance(card, dict):
            raise TransformError(f"{context}: {parent}.card deve ser um objeto, recebido {card!r}")
        _only_keys(card, {"id", "name"}, f"{parent}.card", context)  # card.id é derivável do nome
        rows.append({"event_id": _event_id(event, context), "card_type": text_field(card, ("name",), context)})
    return _frame(rows, CARD_COLUMNS)


# ----------------------------------------------------------------------------- substitutions

def substitutions_frame(match_id: int, events: Sequence[dict]) -> pd.DataFrame:
    """core.substitutions: quem ENTRA (replacement.id) e o motivo. Quem sai é events.player_id."""
    rows = []
    for _, event, context in _typed_events(match_id, events, "substitution"):
        sub = event["substitution"]
        _only_keys(sub, {"outcome", "replacement"}, "substitution", context)
        for part in ("outcome", "replacement"):
            if isinstance(sub.get(part), dict):  # ids e nomes de domínio, deriváveis de outras colunas
                _only_keys(sub[part], {"id", "name"}, f"substitution.{part}", context)
        rows.append({
            "event_id": _event_id(event, context),
            "player_on_id": int_field(sub, ("replacement", "id"), context),
            "reason": optional_text(sub, ("outcome", "name"), context),
        })
    return _frame(rows, SUBSTITUTION_COLUMNS)
