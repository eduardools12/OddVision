"""Utilitários comuns das transformações: leitura de caminhos aninhados e a regra do `extra` (D07)."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any


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
