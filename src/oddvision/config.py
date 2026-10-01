"""Configuração do projeto: leitura e validação de config/selection.toml (D11).

TOML é lido com `tomllib`, da biblioteca padrão: nenhuma dependência extra.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# src/oddvision/config.py -> raiz do projeto (a pasta que contém src/, config/, data/).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class ConfigError(ValueError):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class Selection:
    """O que ingerir e de qual versão da fonte."""

    source_repo: str  # "dono/repositório" no GitHub
    source_commit: str  # SHA completo (40 hex): fixa o conteúdo dos arquivos
    competition_id: int
    season_id: int
    load_match_ids: tuple[int, ...]  # partidas carregadas no core (subconjunto das ingeridas)

    @property
    def base_url(self) -> str:
        """Raiz dos arquivos da fonte, fixada no commit."""
        return f"https://raw.githubusercontent.com/{self.source_repo}/{self.source_commit}/data/"


def selection_path(root: Path) -> Path:
    return root / "config" / "selection.toml"


def raw_dir(root: Path) -> Path:
    """Pasta dos JSONs brutos: imutáveis e fora do Git (D04)."""
    return root / "data" / "raw" / "statsbomb"


def manifest_path(root: Path) -> Path:
    """Manifest da ingestão. Fica fora de raw/ para que raw/ tenha só arquivos da fonte."""
    return root / "data" / "manifests" / "statsbomb_manifest.csv"


def database_config_path(root: Path) -> Path:
    """Credenciais do PostgreSQL. NÃO é versionado (.gitignore); o modelo é database.example.toml."""
    return root / "config" / "database.toml"


def ddl_dir(root: Path) -> Path:
    """Pasta dos arquivos de DDL (001_*.sql, 002_*.sql…), aplicados em ordem pelo `init-db`."""
    return root / "sql" / "ddl"


def analytics_dir(root: Path) -> Path:
    """Pasta das views de métricas (10_*.sql, 20_*.sql…), aplicadas em ordem pelo `init-db`. Só views (D05)."""
    return root / "sql" / "analytics"


def checks_dir(root: Path) -> Path:
    """Pasta dos checks de qualidade (C01_*.sql…), executados por `check`."""
    return root / "sql" / "checks"


def read_toml(path: Path) -> dict:
    try:
        # utf-8-sig: aceita arquivos com BOM (editores do Windows e o PowerShell 5.1 os gravam assim).
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ConfigError(f"arquivo de configuração não encontrado: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML inválido em {path}: {exc}") from exc


def require(table: dict, section: str, key: str, expected_type: type):
    """Devolve table[section][key], exigindo que exista e tenha o tipo esperado."""
    try:
        value = table[section][key]
    except (KeyError, TypeError):
        raise ConfigError(f"chave obrigatória ausente: {section}.{key}") from None
    if not isinstance(value, expected_type) or isinstance(value, bool):
        raise ConfigError(f"{section}.{key} deve ser {expected_type.__name__}, recebido {value!r}")
    return value


def load_selection(path: Path) -> Selection:
    data = read_toml(path)

    repo = require(data, "source", "repo", str)
    if not _REPO_PATTERN.fullmatch(repo):
        raise ConfigError(f"source.repo deve ter o formato 'dono/repositorio', recebido {repo!r}")

    commit = require(data, "source", "commit", str)
    if not _COMMIT_PATTERN.fullmatch(commit):
        raise ConfigError(
            "source.commit deve ser o SHA completo do commit (40 caracteres hexadecimais "
            f"minúsculos); um nome de branch não fixa a versão. Recebido {commit!r}"
        )

    match_ids = require(data, "load", "match_ids", list)
    if not all(isinstance(m, int) and not isinstance(m, bool) for m in match_ids):
        raise ConfigError(f"load.match_ids deve ser uma lista de inteiros, recebido {match_ids!r}")
    repeated = sorted({m for m in match_ids if match_ids.count(m) > 1})
    if repeated:
        raise ConfigError(f"load.match_ids tem valores repetidos: {repeated}")

    return Selection(
        source_repo=repo,
        source_commit=commit,
        competition_id=require(data, "competition", "competition_id", int),
        season_id=require(data, "competition", "season_id", int),
        load_match_ids=tuple(match_ids),
    )
