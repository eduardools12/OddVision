"""Testes de transform/common.py: a regra do `extra JSONB` (D07).

Regra: extra = objeto de origem MENOS os caminhos mapeados para colunas tipadas.
O que não foi mapeado é preservado; nada da fonte se perde e nada é inventado.
"""

import copy

from oddvision.transform.common import MISSING, extract_extra, get_path

SOURCE = {
    "match_id": 1,
    "competition": {"competition_id": 43, "competition_name": "WC"},
    "home_team": {
        "home_team_id": 779,
        "home_team_group": None,
        "country": {"id": 11, "name": "Argentina"},
        "managers": [{"id": 5, "name": "Scaloni"}],
    },
    "last_updated_360": "2026-01-01T00:00:00",
}
MAPPED = [
    ("match_id",),
    ("competition", "competition_id"),
    ("competition", "competition_name"),
    ("home_team", "home_team_id"),
    ("home_team", "country", "name"),
]


def leaf_paths(node, prefix=()):
    """Caminhos de todas as folhas. Listas e dicionários vazios contam como folha."""
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from leaf_paths(value, prefix + (key,))
    else:
        yield prefix


# --------------------------------------------------------------------------- get_path

def test_get_path_follows_nested_keys():
    assert get_path(SOURCE, "home_team", "country", "name") == "Argentina"


def test_get_path_returns_missing_when_a_key_is_absent():
    assert get_path(SOURCE, "referee", "name") is MISSING
    assert get_path(SOURCE, "home_team", "nao_existe") is MISSING


def test_get_path_tells_an_absent_key_from_a_null_value():
    assert get_path(SOURCE, "home_team", "home_team_group") is None  # chave existe, valor nulo
    assert get_path(SOURCE, "home_team", "outra") is MISSING  # chave não existe


def test_get_path_does_not_walk_through_non_dicts():
    assert get_path(SOURCE, "match_id", "x") is MISSING
    assert get_path(SOURCE, "home_team", "managers", "name") is MISSING


# --------------------------------------------------------------------------- extract_extra

def test_removes_the_mapped_leaves_and_keeps_everything_else():
    assert extract_extra(SOURCE, MAPPED) == {
        "home_team": {
            "home_team_group": None,
            "country": {"id": 11},
            "managers": [{"id": 5, "name": "Scaloni"}],
        },
        "last_updated_360": "2026-01-01T00:00:00",
    }


def test_prunes_parents_that_become_empty():
    extra = extract_extra(SOURCE, MAPPED)
    assert "competition" not in extra  # todas as chaves de competition foram mapeadas
    assert "match_id" not in extra


def test_keeps_parents_that_still_have_content():
    assert extract_extra(SOURCE, MAPPED)["home_team"]["country"] == {"id": 11}


def test_keeps_null_values_that_were_not_mapped():
    assert extract_extra(SOURCE, MAPPED)["home_team"]["home_team_group"] is None


def test_lists_are_kept_whole():
    assert extract_extra(SOURCE, MAPPED)["home_team"]["managers"] == SOURCE["home_team"]["managers"]


def test_empty_dicts_that_were_not_on_a_mapped_path_are_kept():
    assert extract_extra({"a": 1, "vazio": {}}, [("a",)]) == {"vazio": {}}


def test_ignores_mapped_paths_that_are_not_present():
    # ex.: a chave `referee` não existe em uma partida da Copa (achado A3)
    assert extract_extra({"a": 1}, [("a",), ("referee", "name")]) == {}


def test_ignores_mapped_paths_that_cross_a_non_dict():
    source = {"a": [1, 2], "b": "texto"}
    assert extract_extra(source, [("a", "x"), ("b", "y", "z")]) == source


def test_does_not_modify_the_source():
    before = copy.deepcopy(SOURCE)
    extract_extra(SOURCE, MAPPED)
    assert SOURCE == before


def test_result_does_not_share_objects_with_the_source():
    extra = extract_extra(SOURCE, MAPPED)
    extra["home_team"]["managers"][0]["name"] = "alterado"
    assert SOURCE["home_team"]["managers"][0]["name"] == "Scaloni"


def test_nothing_is_lost_and_nothing_is_invented():
    extra = extract_extra(SOURCE, MAPPED)
    source_leaves = set(leaf_paths(SOURCE))
    extra_leaves = set(leaf_paths(extra))

    assert extra_leaves <= source_leaves  # nada inventado
    assert source_leaves == extra_leaves | set(MAPPED)  # tudo o que sumiu estava mapeado
    assert not extra_leaves & set(MAPPED)  # nada mapeado sobrou no extra
