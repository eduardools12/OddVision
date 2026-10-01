"""Utilitários comuns das transformações: leitura de caminhos aninhados e a regra do `extra` (D07)."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import pandas as pd


class TransformError(ValueError):
    """O JSON da fonte não tem a forma esperada (campo obrigatório ausente, tipo errado…)."""


class _Missing:
    """Marca "a chave não existe", diferente de "a chave existe com valor null"."""

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


def get_path(obj: Any, *path: str) -> Any:
    """Devolve obj[p1][p2]…, ou MISSING se alguma chave não existir (ou se o caminho cruzar um não-dicionário)."""
    node = obj
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return MISSING
        node = node[key]
    return node


def object_frame(rows: Sequence[dict], columns: Iterable[str]) -> pd.DataFrame:
    """DataFrame com as colunas na ordem pedida. dtype `object`: guarda os objetos Python exatos
    (date, time, datetime, int, str, dict, None) que viram os tipos SQL, sem NaN no lugar de NULL."""
    return pd.DataFrame(list(rows), columns=list(columns), dtype=object)


def require(obj: Any, path: tuple[str, ...], context: str) -> Any:
    """Valor em `path`; erro (com o contexto, ex.: a partida) se a chave faltar ou for null."""
    value = get_path(obj, *path)
    if value is MISSING or value is None:
        raise TransformError(f"{context}: campo obrigatório ausente ou nulo: {'.'.join(path)}")
    return value


def optional(obj: Any, path: tuple[str, ...]) -> Any:
    """Valor em `path`, ou None se a chave não existir."""
    value = get_path(obj, *path)
    return None if value is MISSING else value


def check_type(value: Any, expected: type, field: str, context: str) -> Any:
    """Confere o tipo (um bool não é aceito como int). None passa: a obrigatoriedade é de `require`."""
    if value is None:
        return None
    if isinstance(value, bool) != (expected is bool) or not isinstance(value, expected):
        raise TransformError(f"{context}: {field} deve ser {expected.__name__}, recebido {value!r}")
    return value


def int_field(obj, path, context):
    return check_type(require(obj, path, context), int, ".".join(path), context)


def text_field(obj, path, context):
    return check_type(require(obj, path, context), str, ".".join(path), context)


def bool_field(obj, path, context):
    return check_type(require(obj, path, context), bool, ".".join(path), context)


def optional_int(obj, path, context):
    return check_type(optional(obj, path), int, ".".join(path), context)


def optional_text(obj, path, context):
    return check_type(optional(obj, path), str, ".".join(path), context)


def float_value(value: Any, field: str, context: str) -> float:
    """Um número (int ou float, nunca bool) como float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransformError(f"{context}: {field} deve ser numérico, recebido {value!r}")
    return float(value)


def optional_float(obj, path, context):
    value = optional(obj, path)
    return None if value is None else float_value(value, ".".join(path), context)


def parse_field(value: Any, parser: Callable[[str], Any], field: str, context: str) -> Any:
    """Aplica `parser` (ex.: date.fromisoformat); falha com o campo e o contexto."""
    try:
        return parser(value)
    except (TypeError, ValueError) as exc:
        raise TransformError(f"{context}: {field} inválido ({value!r}): {exc}") from exc


def _remove_path(root: dict, path: tuple[str, ...]) -> None:
    """Remove a folha de `path` e poda os pais que ficaram vazios por causa disso."""
    parents: list[tuple[dict, str]] = []
    node: Any = root
    for key in path[:-1]:
        if not isinstance(node, dict) or key not in node:
            return
        parents.append((node, key))
        node = node[key]
    if not isinstance(node, dict) or path[-1] not in node:
        return
    del node[path[-1]]
    for parent, key in reversed(parents):
        if parent[key] == {}:
            del parent[key]
        else:
            break


def extract_extra(source: Mapping[str, Any], mapped_paths: Iterable[tuple[str, ...]]) -> dict:
    """O `extra JSONB` de uma linha: o objeto de origem MENOS os caminhos mapeados para colunas (D07).

    - Nada da fonte se perde: o que não virou coluna fica aqui.
    - Nada é inventado nem duplicado: o que virou coluna sai daqui.
    - Pais que ficam vazios depois das remoções são podados; valores null não mapeados permanecem.
    - Caminhos ausentes são ignorados (ex.: a chave `referee` não existe em uma partida).
    - A origem não é modificada (trabalha em uma cópia profunda).
    """
    extra = copy.deepcopy(dict(source))
    for path in mapped_paths:
        _remove_path(extra, tuple(path))
    return extra
