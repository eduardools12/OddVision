"""Fixtures compartilhadas dos testes unitários.

`fake_source` é uma "fonte StatsBomb" em memória: 1 competições, 1 arquivo de partidas
(101 e 102), e events + lineups de cada partida. Assim a ingestão é testada sem rede.
"""

import json
from dataclasses import dataclass, field

import pytest

from oddvision.config import Selection
from oddvision.ingest import DownloadError

COMMIT = "ab" * 20  # 40 caracteres hexadecimais, como um SHA de commit


@dataclass
class FakeSource:
    selection: Selection
    files: dict[str, bytes]  # url -> conteúdo
    calls: list[str] = field(default_factory=list)
    fail_on: set[str] = field(default_factory=set)

    def url(self, rel_path: str) -> str:
        return self.selection.base_url + rel_path

    def download(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self.fail_on:
            raise DownloadError(f"falha simulada em {url}")
        if url not in self.files:
            raise DownloadError(f"HTTP 404 ao baixar {url}")
        return self.files[url]


def _dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


@pytest.fixture
def fake_source() -> FakeSource:
    selection = Selection(
        source_repo="owner/repo",
        source_commit=COMMIT,
        competition_id=43,
        season_id=106,
        load_match_ids=(101,),
    )
    base = selection.base_url
    files = {
        base + "competitions.json": _dump(
            [{"competition_id": 43, "season_id": 106}, {"competition_id": 11, "season_id": 90}]
        ),
        base + "matches/43/106.json": _dump([{"match_id": 101}, {"match_id": 102}]),
        base + "events/101.json": _dump(
            [{"id": "a", "index": 1}, {"id": "b", "index": 2}, {"id": "c", "index": 3}]
        ),
        base + "events/102.json": _dump([{"id": "d", "index": 1}, {"id": "e", "index": 2}]),
        # Acentos de propósito: os bytes gravados precisam ser exatamente os recebidos.
        base + "lineups/101.json": _dump(
            [{"team_id": 1, "team_name": "Seleção Ávila"}, {"team_id": 2, "team_name": "B"}]
        ),
        base + "lineups/102.json": _dump(
            [{"team_id": 3, "team_name": "C"}, {"team_id": 4, "team_name": "D"}]
        ),
    }
    return FakeSource(selection=selection, files=files)
