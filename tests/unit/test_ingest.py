"""Testes de src/oddvision/ingest.py (P1: ingestão bruta).

Contratos do plano (Passo 3): arquivos idênticos aos da fonte, manifest correto, 2ª execução
sem baixar nada, e imutabilidade (arquivo alterado = erro). Tudo sem rede: a função de
download é injetada (`fake_source.download`).
"""

import csv
import hashlib
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from oddvision.ingest import (
    MANIFEST_COLUMNS,
    DownloadError,
    IntegrityError,
    InvalidContentError,
    http_download,
    read_manifest,
    run_ingest,
)

EXPECTED_RECORD_COUNTS = {
    "competitions.json": 2,
    "matches/43/106.json": 2,
    "events/101.json": 3,
    "events/102.json": 2,
    "lineups/101.json": 2,
    "lineups/102.json": 2,
}
TOTAL = len(EXPECTED_RECORD_COUNTS)


def fixed_now(year=2026):
    return lambda: datetime(year, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "raw", tmp_path / "manifests" / "manifest.csv"


def ingest(fake_source, dirs, **kwargs):
    raw, manifest = dirs
    kwargs.setdefault("download", fake_source.download)
    kwargs.setdefault("now", fixed_now())
    return run_ingest(kwargs.pop("selection", fake_source.selection), raw, manifest, **kwargs)


# --------------------------------------------------------------------------- primeira execução

def test_first_run_downloads_every_file_unmodified(fake_source, dirs):
    result = ingest(fake_source, dirs)

    assert (result.downloaded, result.existing, result.total) == (TOTAL, 0, TOTAL)
    raw, _ = dirs
    for rel_path in EXPECTED_RECORD_COUNTS:
        assert (raw / rel_path).read_bytes() == fake_source.files[fake_source.url(rel_path)]
    assert list(raw.rglob("*.part")) == []


def test_manifest_describes_every_file(fake_source, dirs):
    ingest(fake_source, dirs)
    _, manifest = dirs

    with manifest.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == list(MANIFEST_COLUMNS)

    entries = read_manifest(manifest)
    assert set(entries) == set(EXPECTED_RECORD_COUNTS)  # caminhos relativos, com "/"
    for rel_path, entry in entries.items():
        content = fake_source.files[fake_source.url(rel_path)]
        assert entry.sha256 == hashlib.sha256(content).hexdigest()
        assert entry.size_bytes == len(content)
        assert entry.record_count == EXPECTED_RECORD_COUNTS[rel_path]
        assert entry.source_url == fake_source.url(rel_path)
        assert entry.source_commit == fake_source.selection.source_commit
        assert entry.downloaded_at == "2026-01-01T00:00:00+00:00"


# --------------------------------------------------------------------------- idempotência

def test_second_run_downloads_nothing(fake_source, dirs):
    ingest(fake_source, dirs)
    _, manifest = dirs
    manifest_before = manifest.read_text(encoding="utf-8")
    calls_before = len(fake_source.calls)

    result = ingest(fake_source, dirs, now=fixed_now(2027))

    assert (result.downloaded, result.existing) == (0, TOTAL)
    assert len(fake_source.calls) == calls_before  # nenhuma requisição nova
    assert manifest.read_text(encoding="utf-8") == manifest_before  # downloaded_at preservado


def test_deleted_file_is_downloaded_again_and_matches_the_manifest(fake_source, dirs):
    ingest(fake_source, dirs)
    raw, _ = dirs
    original = (raw / "lineups/101.json").read_bytes()
    (raw / "lineups/101.json").unlink()

    result = ingest(fake_source, dirs)

    assert (result.downloaded, result.existing) == (1, TOTAL - 1)
    assert (raw / "lineups/101.json").read_bytes() == original


# --------------------------------------------------------------------------- imutabilidade

def test_modified_raw_file_is_an_integrity_error(fake_source, dirs):
    ingest(fake_source, dirs)
    raw, _ = dirs
    (raw / "events/101.json").write_bytes(b"[]")

    with pytest.raises(IntegrityError, match=r"events/101\.json"):
        ingest(fake_source, dirs)


def test_file_missing_from_the_manifest_is_an_integrity_error(fake_source, dirs):
    ingest(fake_source, dirs)
    _, manifest = dirs
    manifest.unlink()

    with pytest.raises(IntegrityError, match="manifest"):
        ingest(fake_source, dirs)


def test_changing_the_pinned_commit_is_an_integrity_error(fake_source, dirs):
    ingest(fake_source, dirs)
    other_commit = replace(fake_source.selection, source_commit="cd" * 20)

    with pytest.raises(IntegrityError, match="commit"):
        ingest(fake_source, dirs, selection=other_commit)


def test_redownload_with_different_content_is_an_integrity_error(fake_source, dirs):
    ingest(fake_source, dirs)
    raw, _ = dirs
    (raw / "events/101.json").unlink()
    fake_source.files[fake_source.url("events/101.json")] = b'[{"id": "outro"}]'

    with pytest.raises(IntegrityError, match=r"events/101\.json"):
        ingest(fake_source, dirs)
    assert not (raw / "events/101.json").exists()  # o conteúdo diferente não foi gravado


# --------------------------------------------------------------------------- conteúdo inválido

def test_invalid_json_is_never_saved(fake_source, dirs):
    fake_source.files[fake_source.url("events/101.json")] = b"isto nao e json"

    with pytest.raises(InvalidContentError, match=r"events/101\.json"):
        ingest(fake_source, dirs)

    raw, _ = dirs
    assert not (raw / "events/101.json").exists()
    assert list(raw.rglob("*.part")) == []


def test_non_array_json_is_rejected(fake_source, dirs):
    fake_source.files[fake_source.url("events/101.json")] = b'{"id": "a"}'

    with pytest.raises(InvalidContentError, match="array"):
        ingest(fake_source, dirs)


def test_duplicate_match_ids_in_the_matches_file_are_rejected(fake_source, dirs):
    fake_source.files[fake_source.url("matches/43/106.json")] = b'[{"match_id": 101}, {"match_id": 101}]'

    with pytest.raises(InvalidContentError, match="101"):
        ingest(fake_source, dirs)


def test_sentinel_match_missing_from_the_matches_file_is_rejected(fake_source, dirs):
    selection = replace(fake_source.selection, load_match_ids=(101, 999))

    with pytest.raises(InvalidContentError, match="999"):
        ingest(fake_source, dirs, selection=selection)


# --------------------------------------------------------------------------- interrupção

def test_interrupted_run_resumes_where_it_stopped(fake_source, dirs):
    _, manifest = dirs
    fake_source.fail_on = {fake_source.url("events/102.json")}

    with pytest.raises(DownloadError):
        ingest(fake_source, dirs)
    # o manifest é gravado a cada arquivo: os 4 primeiros já constam
    assert len(read_manifest(manifest)) == 4

    fake_source.fail_on = set()
    result = ingest(fake_source, dirs)

    assert (result.downloaded, result.existing) == (2, 4)
    assert len(read_manifest(manifest)) == TOTAL


def test_leftover_part_file_is_replaced(fake_source, dirs):
    raw, _ = dirs
    (raw / "events").mkdir(parents=True)
    (raw / "events" / "101.json.part").write_bytes(b"lixo de uma execucao interrompida")

    ingest(fake_source, dirs)

    assert list(raw.rglob("*.part")) == []
    assert (raw / "events/101.json").read_bytes() == fake_source.files[fake_source.url("events/101.json")]


def test_on_file_reports_downloads_and_existing_files(fake_source, dirs):
    events = []
    ingest(fake_source, dirs, on_file=lambda action, path: events.append((action, path)))
    assert [a for a, _ in events] == ["baixado"] * TOTAL

    events.clear()
    ingest(fake_source, dirs, on_file=lambda action, path: events.append((action, path)))
    assert [a for a, _ in events] == ["existente"] * TOTAL


# --------------------------------------------------------------------------- http_download

class FakeResponse:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


@pytest.fixture
def fake_urlopen(monkeypatch):
    """Substitui urllib.request.urlopen por uma sequência de respostas ou exceções."""
    outcomes, calls = [], []

    def urlopen(url, timeout=None):
        calls.append(url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return outcomes, calls


def test_http_download_returns_the_bytes(fake_urlopen):
    outcomes, calls = fake_urlopen
    outcomes.append(b"conteudo")
    assert http_download("http://x/a") == b"conteudo"
    assert calls == ["http://x/a"]


def test_http_download_retries_transient_failures(fake_urlopen):
    outcomes, calls = fake_urlopen
    outcomes += [urllib.error.URLError("rede"), TimeoutError(), b"ok"]
    sleeps = []

    assert http_download("http://x/a", sleep=sleeps.append) == b"ok"
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]  # espera crescente entre as tentativas


def test_http_download_retries_server_errors(fake_urlopen):
    outcomes, calls = fake_urlopen
    outcomes += [urllib.error.HTTPError("http://x/a", 503, "Service Unavailable", None, None), b"ok"]
    assert http_download("http://x/a", sleep=lambda s: None) == b"ok"
    assert len(calls) == 2


def test_http_download_gives_up_after_three_attempts(fake_urlopen):
    outcomes, calls = fake_urlopen
    outcomes += [urllib.error.URLError("rede")] * 3

    with pytest.raises(DownloadError, match="3 tentativas"):
        http_download("http://x/a", sleep=lambda s: None)
    assert len(calls) == 3


def test_http_download_does_not_retry_a_404(fake_urlopen):
    outcomes, calls = fake_urlopen
    outcomes.append(urllib.error.HTTPError("http://x/a", 404, "Not Found", None, None))

    with pytest.raises(DownloadError, match="404"):
        http_download("http://x/a", sleep=lambda s: None)
    assert len(calls) == 1
