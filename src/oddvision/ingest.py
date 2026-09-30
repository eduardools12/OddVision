"""Ingestão bruta (P1): baixa os arquivos do StatsBomb Open Data para data/raw/ (D04).

Garantias:
- **Imutabilidade:** o conteúdo é gravado exatamente como recebido, e nunca é sobrescrito.
  Arquivo alterado em disco, ou conteúdo diferente ao baixar de novo = erro.
- **Idempotência:** o que já existe e confere com o manifest não é baixado de novo.
- **Atomicidade:** cada arquivo é gravado em `.part` e renomeado, então um download
  interrompido nunca deixa um arquivo pela metade com o nome final.
- **Retomada:** o manifest é regravado a cada arquivo, então uma execução interrompida
  continua de onde parou.
- **Só JSON válido entra:** o conteúdo é validado (array JSON) antes de ser gravado.

Só a biblioteca padrão é usada (urllib, hashlib, json, csv).
"""

from __future__ import annotations

import csv
import hashlib
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from oddvision.config import Selection

MANIFEST_COLUMNS = (
    "file_path",
    "source_url",
    "source_commit",
    "sha256",
    "size_bytes",
    "record_count",
    "downloaded_at",
)


class IngestError(Exception):
    """Falha da ingestão."""


class DownloadError(IngestError):
    """Não foi possível baixar um arquivo."""


class InvalidContentError(IngestError):
    """O conteúdo baixado não é o esperado."""


class IntegrityError(IngestError):
    """Violação da imutabilidade: disco, manifest e fonte não concordam."""


@dataclass(frozen=True)
class ManifestEntry:
    file_path: str  # relativo a data/raw/statsbomb/, com "/" (ex.: "events/3869685.json")
    source_url: str
    source_commit: str
    sha256: str
    size_bytes: int
    record_count: int  # nº de elementos do array JSON (eventos, partidas, times…)
    downloaded_at: str  # ISO 8601, UTC


@dataclass(frozen=True)
class IngestResult:
    downloaded: int
    existing: int

    @property
    def total(self) -> int:
        return self.downloaded + self.existing


# ----------------------------------------------------------------------------- download

def http_download(
    url: str,
    *,
    timeout: float = 120,
    attempts: int = 3,
    backoff: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """Baixa `url` e devolve os bytes. Repete falhas transitórias, com espera crescente."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            # 4xx (exceto 429) não melhora tentando de novo: falha na hora.
            if 400 <= exc.code < 500 and exc.code != 429:
                raise DownloadError(f"HTTP {exc.code} ao baixar {url}") from exc
            last_error = exc
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as exc:
            last_error = exc
        if attempt < attempts:
            sleep(backoff * attempt)
    raise DownloadError(f"falha ao baixar {url} após {attempts} tentativas: {last_error}") from last_error


# ----------------------------------------------------------------------------- manifest

def read_manifest(path: Path) -> dict[str, ManifestEntry]:
    """Lê o manifest (vazio se ainda não existe), indexado por `file_path`."""
    if not path.exists():
        return {}
    entries: dict[str, ManifestEntry] = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != MANIFEST_COLUMNS:
            raise IntegrityError(f"colunas inesperadas no manifest {path}: {reader.fieldnames}")
        for row in reader:
            entries[row["file_path"]] = ManifestEntry(
                file_path=row["file_path"],
                source_url=row["source_url"],
                source_commit=row["source_commit"],
                sha256=row["sha256"],
                size_bytes=int(row["size_bytes"]),
                record_count=int(row["record_count"]),
                downloaded_at=row["downloaded_at"],
            )
    return entries


def write_manifest(path: Path, entries: dict[str, ManifestEntry]) -> None:
    """Grava o manifest de forma atômica, ordenado por caminho (saída determinística)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(MANIFEST_COLUMNS)
        for key in sorted(entries):
            e = entries[key]
            writer.writerow(
                [e.file_path, e.source_url, e.source_commit, e.sha256, e.size_bytes,
                 e.record_count, e.downloaded_at]
            )
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- utilitários

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _count_json_records(data: bytes, rel_path: str) -> int:
    """Valida que `data` é um array JSON (UTF-8) e devolve o nº de elementos."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidContentError(f"{rel_path}: o conteúdo não é JSON válido ({exc})") from exc
    if not isinstance(payload, list):
        raise InvalidContentError(
            f"{rel_path}: esperado um array JSON, recebido {type(payload).__name__}"
        )
    return len(payload)


def _match_ids(matches_file: Path, rel_path: str) -> list[int]:
    """Lê os match_id do arquivo de partidas e garante que são inteiros e únicos."""
    matches = json.loads(matches_file.read_bytes().decode("utf-8"))
    try:
        ids = [m["match_id"] for m in matches]
    except (KeyError, TypeError) as exc:
        raise InvalidContentError(f"{rel_path}: partida sem 'match_id' ({exc!r})") from exc
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise InvalidContentError(f"{rel_path}: 'match_id' deve ser inteiro")
    repeated = sorted(i for i, n in Counter(ids).items() if n > 1)
    if repeated:
        raise InvalidContentError(f"{rel_path}: match_id repetido(s): {repeated}")
    return sorted(ids)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------- ingestão

def run_ingest(
    selection: Selection,
    raw_dir: Path,
    manifest_path: Path,
    *,
    download: Callable[[str], bytes] = http_download,
    now: Callable[[], datetime] = _utc_now,
    on_file: Callable[[str, str], None] | None = None,
) -> IngestResult:
    """Baixa competitions + partidas + events e lineups de cada partida.

    `download` e `now` são injetáveis para testar sem rede e sem depender do relógio.
    `on_file(ação, caminho)` recebe "baixado" ou "existente" para cada arquivo.
    """
    entries = read_manifest(manifest_path)
    counts = {"downloaded": 0, "existing": 0}

    def notify(action: str, rel_path: str) -> None:
        if on_file is not None:
            on_file(action, rel_path)

    def ensure(rel_path: str) -> None:
        path = raw_dir / rel_path
        url = selection.base_url + rel_path
        entry = entries.get(rel_path)

        if entry is not None and entry.source_commit != selection.source_commit:
            raise IntegrityError(
                f"{rel_path}: foi baixado do commit {entry.source_commit[:8]}, mas a configuração "
                f"fixa {selection.source_commit[:8]}. Trocar o commit da fonte é uma decisão explícita: "
                "use outra pasta de dados (nada foi alterado)."
            )

        if path.exists():
            if entry is None:
                raise IntegrityError(
                    f"{rel_path} existe em disco, mas não consta no manifest; não há como provar "
                    "que é o arquivo original (nada foi alterado)."
                )
            actual = sha256_file(path)
            if actual != entry.sha256:
                raise IntegrityError(
                    f"{rel_path} foi modificado (sha256 {actual[:12]}… ≠ manifest {entry.sha256[:12]}…). "
                    "Os dados brutos são imutáveis: restaure o original ou remova o arquivo "
                    "manualmente para baixá-lo de novo (nada foi alterado)."
                )
            counts["existing"] += 1
            notify("existente", rel_path)
            return

        data = download(url)
        record_count = _count_json_records(data, rel_path)
        sha = hashlib.sha256(data).hexdigest()
        if entry is not None and entry.sha256 != sha:
            raise IntegrityError(
                f"{rel_path}: a fonte devolveu conteúdo diferente do registrado no manifest "
                f"(sha256 {sha[:12]}… ≠ {entry.sha256[:12]}…). O arquivo novo não foi gravado."
            )
        _write_atomic(path, data)
        entries[rel_path] = ManifestEntry(
            file_path=rel_path,
            source_url=url,
            source_commit=selection.source_commit,
            sha256=sha,
            size_bytes=len(data),
            record_count=record_count,
            downloaded_at=now().isoformat(timespec="seconds"),
        )
        write_manifest(manifest_path, entries)  # a cada arquivo: permite retomar após interrupção
        counts["downloaded"] += 1
        notify("baixado", rel_path)

    matches_rel = f"matches/{selection.competition_id}/{selection.season_id}.json"
    ensure("competitions.json")
    ensure(matches_rel)

    match_ids = _match_ids(raw_dir / matches_rel, matches_rel)
    unknown = [m for m in selection.load_match_ids if m not in match_ids]
    if unknown:
        raise InvalidContentError(
            f"load.match_ids tem partida(s) que não existem em {matches_rel}: {unknown}"
        )

    for match_id in match_ids:
        ensure(f"events/{match_id}.json")
        ensure(f"lineups/{match_id}.json")

    return IngestResult(downloaded=counts["downloaded"], existing=counts["existing"])
