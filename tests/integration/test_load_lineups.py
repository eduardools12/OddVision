"""Testes da carga P3 (Passo 6): players e lineups das partidas-sentinela.

Tudo é montado SEM rede: a ingestão roda com um downloader falso que serve as amostras de tests/fixtures/
(objetos reais da final, copiados sem alteração). A sentinela é a partida 3869685; as outras duas partidas
da amostra só existem para provar que o nome dos jogadores é decidido olhando TODOS os arquivos.
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from oddvision.config import Selection
from oddvision.ingest import IntegrityError, run_ingest
from oddvision.load import LoadError, load_matches, load_p2
from oddvision.pipeline import main
from oddvision.transform.lineups import LINEUP_COLUMNS, PLAYER_COLUMNS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COMMIT = "ab" * 20
SELECTION = Selection("owner/repo", COMMIT, 43, 106, (3869685,))
FINAL, ARG_AUS, NO_REFEREE = 3869685, 3869151, 3857291
MESSI = 5503
T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Fatos conhecidos dos 7 jogadores da amostra: player_id -> (team_id, camisa, titular, entrou, 1ª posição)
EXPECTED = {
    3009: (771, 10, True, True, "Left Wing"),
    2972: (771, 26, False, True, "Center Forward"),
    3379: (771, 23, False, False, None),
    5503: (779, 10, True, True, "Right Wing"),
    19597: (779, 8, False, True, "Left Wing"),
    6909: (779, 23, True, True, "Goalkeeper"),
    6312: (779, 1, False, False, None),
    2995: (779, 11, True, True, "Left Wing"),
    3090: (779, 19, True, True, "Left Center Back"),
}


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def stage(tmp_path, lineups=None):
    """Ingestão (sem rede). `lineups`: {match_id: JSON} substitui a escalação padrão de uma partida."""
    matches = fixture("matches_sample.json")
    by_match = {m["match_id"]: fixture("lineups_sample.json") for m in matches}
    by_match.update(lineups or {})
    files = {"competitions.json": dump(fixture("competitions_sample.json")), "matches/43/106.json": dump(matches)}
    for match_id, teams in by_match.items():
        files[f"events/{match_id}.json"] = dump(fixture("events_sample.json"))
        files[f"lineups/{match_id}.json"] = dump(teams)
    served = {SELECTION.base_url + rel: data for rel, data in files.items()}
    raw, manifest = tmp_path / "raw", tmp_path / "manifests" / "manifest.csv"
    run_ingest(SELECTION, raw, manifest, download=served.__getitem__)
    return raw, manifest, served


def prepare(tmp_path, engine, lineups=None):
    """Ingestão + P2 (as partidas precisam existir em core.matches antes das escalações)."""
    raw, manifest, _ = stage(tmp_path, lineups)
    load_p2(engine, SELECTION, raw, manifest, now=lambda: T1)
    return raw, manifest


def scalar(engine, sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar_one()


def rows(engine, sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).all()


def snapshot(engine):
    return {"players": rows(engine, "SELECT * FROM core.players ORDER BY 1"),
            "lineups": rows(engine, "SELECT * FROM core.lineups ORDER BY 1, 3")}


def renamed_messi(name):
    teams = fixture("lineups_sample.json")
    next(p for t in teams for p in t["lineup"] if p["player_id"] == MESSI)["player_name"] = name
    return teams


# --------------------------------------------------------------------------- carga

def test_load_writes_players_and_lineups_of_the_sentinel(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)

    result = load_matches(fresh_schemas, SELECTION, raw, manifest, now=lambda: T1)

    assert [(m.match_id, m.players, m.starters, m.played) for m in result.matches] == [(FINAL, 9, 5, 7)]
    assert result.players == 9
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.lineups") == 9
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.players") == 9


def test_the_lineup_rows_match_the_known_facts(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)

    found = {r.player_id: (r.team_id, r.jersey_number, r.is_starter, r.played, r.first_position)
             for r in rows(fresh_schemas, "SELECT * FROM core.lineups WHERE match_id = :m", m=FINAL)}
    assert found == EXPECTED


def test_players_keep_their_accents(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)

    r = rows(fresh_schemas, "SELECT * FROM core.players WHERE player_id = :p", p=MESSI)[0]
    assert (r.player_name, r.player_nickname, r.country_name) == ("Lionel Andrés Messi Cuccittini", "Lionel Messi", "Argentina")
    assert scalar(fresh_schemas, "SELECT player_name FROM core.players WHERE player_id = 6909") == "Damián Emiliano Martínez"


def test_extra_keeps_positions_in_the_source_order_and_the_cards(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)
    teams = fixture("lineups_sample.json")
    source = {p["player_id"]: p for t in teams for p in t["lineup"]}

    messi = scalar(fresh_schemas, "SELECT extra FROM core.lineups WHERE match_id = :m AND player_id = :p", m=FINAL, p=MESSI)
    assert messi["positions"] == source[MESSI]["positions"]  # inclusive a ordem original, fora de ordem
    assert [p["from_period"] for p in messi["positions"]] == [1, 4, 1]
    thuram = scalar(fresh_schemas, "SELECT extra FROM core.lineups WHERE match_id = :m AND player_id = 2972", m=FINAL)
    assert thuram["cards"] == source[2972]["cards"] and thuram["country"] == {"id": 78}


def test_loading_twice_changes_nothing(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)
    first = snapshot(fresh_schemas)

    load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert snapshot(fresh_schemas) == first


def test_reloading_replaces_the_match_lineups_and_leaves_other_matches_alone(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    load_matches(fresh_schemas, SELECTION, raw, manifest)
    with fresh_schemas.begin() as c:  # uma linha velha na partida recarregada e uma linha em OUTRA partida
        c.execute(text("INSERT INTO core.players (player_id, player_name) VALUES (99999, 'Ex-jogador')"))
        c.execute(text("INSERT INTO core.lineups (match_id, team_id, player_id, is_starter, played) "
                       "VALUES (:a, 779, 99999, false, false), (:b, 779, :p, false, false)"), {"a": FINAL, "b": NO_REFEREE, "p": MESSI})

    load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert rows(fresh_schemas, "SELECT 1 FROM core.lineups WHERE match_id = :m AND player_id = 99999", m=FINAL) == []
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.lineups WHERE match_id = :m", m=FINAL) == 9
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.lineups WHERE match_id = :m", m=NO_REFEREE) == 1  # intacta


def test_the_ingestion_log_marks_only_the_lineups_that_were_loaded(fresh_schemas, tmp_path):
    raw, manifest = prepare(tmp_path, fresh_schemas)
    t2 = datetime(2026, 2, 2, tzinfo=timezone.utc)
    load_matches(fresh_schemas, SELECTION, raw, manifest, now=lambda: t2)

    loaded = {r.file_path: r.loaded_at for r in rows(fresh_schemas, "SELECT file_path, loaded_at FROM core.ingestion_log")}
    assert loaded["lineups/3869685.json"] == t2
    assert loaded["lineups/3869151.json"] is None and loaded["lineups/3857291.json"] is None
    assert loaded["competitions.json"] == T1  # a carga das escalações não mexe nos arquivos do P2


# --------------------------------------------------------------------------- nomes (decisão: o mais frequente)

def test_the_name_is_chosen_looking_at_all_the_files_not_only_the_loaded_ones(fresh_schemas, tmp_path):
    # A sentinela diz "Messi A"; as outras duas partidas, que NÃO são carregadas, dizem "Messi B".
    lineups = {FINAL: renamed_messi("Messi A"), ARG_AUS: renamed_messi("Messi B"), NO_REFEREE: renamed_messi("Messi B")}
    raw, manifest = prepare(tmp_path, fresh_schemas, lineups)

    result = load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert scalar(fresh_schemas, "SELECT player_name FROM core.players WHERE player_id = :p", p=MESSI) == "Messi B"
    assert [(c.player_id, c.attribute, c.counts, c.chosen) for c in result.conflicts] == [
        (MESSI, "player_name", {"Messi A": 1, "Messi B": 2}, "Messi B")]


def test_only_the_players_of_the_loaded_matches_are_written(fresh_schemas, tmp_path):
    other = fixture("lineups_sample.json")
    extra_player = copy.deepcopy(other[0]["lineup"][0])
    extra_player.update(player_id=888, player_name="Jogador de outra partida")
    other[0]["lineup"].append(extra_player)
    raw, manifest = prepare(tmp_path, fresh_schemas, {ARG_AUS: other})

    load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert scalar(fresh_schemas, "SELECT count(*) FROM core.players WHERE player_id = 888") == 0
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.players") == 9


# --------------------------------------------------------------------------- atomicidade e integridade

def test_a_lineup_with_a_team_that_is_not_in_the_match_writes_nothing(fresh_schemas, tmp_path):
    teams = fixture("lineups_sample.json")
    teams[0]["team_id"] = 792  # a Austrália existe em core.teams, mas não joga a final
    raw, manifest = prepare(tmp_path, fresh_schemas, {FINAL: teams})

    with pytest.raises(LoadError, match="792"):
        load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert (scalar(fresh_schemas, "SELECT count(*) FROM core.players"), scalar(fresh_schemas, "SELECT count(*) FROM core.lineups")) == (0, 0)


def test_a_failure_after_writing_rolls_the_whole_match_back(fresh_schemas, tmp_path):
    teams = fixture("lineups_sample.json")
    teams[0]["lineup"][0]["jersey_number"] = 40000  # passa pela transformação; estoura o SMALLINT no INSERT
    raw, manifest = prepare(tmp_path, fresh_schemas, {FINAL: teams})

    with pytest.raises(DBAPIError):
        load_matches(fresh_schemas, SELECTION, raw, manifest)

    # os players e o DELETE já tinham sido executados quando o INSERT das escalações falhou
    assert (scalar(fresh_schemas, "SELECT count(*) FROM core.players"), scalar(fresh_schemas, "SELECT count(*) FROM core.lineups")) == (0, 0)
    assert scalar(fresh_schemas, "SELECT loaded_at FROM core.ingestion_log WHERE file_path = 'lineups/3869685.json'") is None


def test_a_match_missing_from_core_matches_is_reported(fresh_schemas, tmp_path):
    raw, manifest, _ = stage(tmp_path)  # sem load_p2: core.matches está vazia

    with pytest.raises(LoadError, match="core.matches"):
        load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert scalar(fresh_schemas, "SELECT count(*) FROM core.players") == 0


def test_a_tampered_file_of_another_match_still_aborts_everything(fresh_schemas, tmp_path):
    # A decisão dos nomes lê TODOS os arquivos de escalação: um arquivo adulterado, mesmo de uma partida
    # que não seria carregada, precisa ser notado antes de qualquer gravação.
    raw, manifest = prepare(tmp_path, fresh_schemas)
    (raw / "lineups" / f"{NO_REFEREE}.json").write_bytes(b"[]")

    with pytest.raises(IntegrityError, match=rf"lineups/{NO_REFEREE}\.json"):
        load_matches(fresh_schemas, SELECTION, raw, manifest)

    assert scalar(fresh_schemas, "SELECT count(*) FROM core.players") == 0


# --------------------------------------------------------------------------- colunas e CLI

@pytest.mark.parametrize("table, columns", [("lineups", LINEUP_COLUMNS), ("players", PLAYER_COLUMNS)])
def test_frame_columns_follow_the_table_column_order(schemas, table, columns):
    in_database = [r.column_name for r in rows(
        schemas, "SELECT column_name FROM information_schema.columns "
                 "WHERE table_schema = 'core' AND table_name = :t ORDER BY ordinal_position", t=table)]
    assert list(columns) == in_database


def test_load_command_loads_lineups_and_warns_about_conflicting_names(fresh_schemas, db_config, tmp_path, capsys):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "selection.toml").write_text(
        f'[source]\nrepo = "owner/repo"\ncommit = "{COMMIT}"\n\n[competition]\ncompetition_id = 43\n'
        "season_id = 106\n\n[load]\nmatch_ids = [3869685]\n", encoding="utf-8")
    (tmp_path / "config" / "database.toml").write_text(
        f"[connection]\nhost = {json.dumps(db_config.host)}\nport = {db_config.port}\n"
        f"user = {json.dumps(db_config.user)}\npassword = {json.dumps(db_config.password)}\n\n"
        f"[databases]\nmain = {json.dumps(db_config.test_db)}\ntest = {json.dumps(db_config.test_db)}\n", encoding="utf-8")
    _, _, served = stage(tmp_path / "unused", {FINAL: renamed_messi("Messi A"), ARG_AUS: renamed_messi("Messi B"),
                                               NO_REFEREE: renamed_messi("Messi B")})
    assert main(["ingest"], root=tmp_path, download=served.__getitem__) == 0
    capsys.readouterr()

    for _ in range(2):
        assert main(["load"], root=tmp_path) == 0
        captured = capsys.readouterr()
        assert "lineups: partida 3869685: 9 jogadores (5 titulares, 7 entraram em campo)" in captured.out
        assert "players: 9" in captured.out
        assert "aviso" in captured.err and str(MESSI) in captured.err and "Messi B" in captured.err
        assert db_config.password not in captured.out + captured.err
    assert scalar(fresh_schemas, "SELECT count(*) FROM core.lineups") == 9
