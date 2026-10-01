"""P6: checks de qualidade dos dados.

Cada check é um arquivo `sql/checks/CNN_nome.sql` com um cabeçalho (`-- level: error|warning`, `-- title: …`) e
UMA consulta que devolve as linhas problemáticas: nenhuma linha = check limpo. Um check de nível `error` com
linhas faz o comando `check` terminar com código 1; um `warning` só é reportado.

Os checks só LEEM (um teste confere), e podem ler colunas JSONB: não são o schema `analytics` (D05).
O C11 é feito em Python porque precisa dos arquivos brutos de escalação, que não estão no banco.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection

from oddvision.config import ConfigError
from oddvision.ingest import read_manifest
from oddvision.load import build_player_table

_FILE_NAME = re.compile(r"(C\d{2})_[A-Za-z0-9_]+\.sql")
_HEADER_LINE = re.compile(r"--\s*(level|title)\s*:\s*(.+?)\s*$")
LEVELS = ("error", "warning")


@dataclass(frozen=True)
class SqlCheck:
    check_id: str
    level: str  # "error" ou "warning"
    title: str
    sql: str
    path: Path


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    level: str
    title: str
    violations: int  # nº de linhas problemáticas
    columns: tuple[str, ...]
    sample: tuple[tuple, ...]  # as primeiras linhas, para o relatório


def load_sql_checks(directory: Path) -> list[SqlCheck]:
    """Lê os arquivos CNN_*.sql da pasta, em ordem de id. Arquivos que não são .sql são ignorados."""
    if not directory.is_dir():
        raise ConfigError(f"pasta de checks não encontrada: {directory}")
    checks: dict[str, SqlCheck] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_NAME.fullmatch(path.name)
        if match is None:
            raise ConfigError(f"nome de check inválido: {path.name} (esperado CNN_nome.sql, ex.: C01_eventos.sql)")
        text = path.read_text(encoding="utf-8")
        header = {m.group(1): m.group(2) for line in text.splitlines() if (m := _HEADER_LINE.match(line))}
        for key in ("level", "title"):
            if key not in header:
                raise ConfigError(f"{path.name}: falta o cabeçalho '-- {key}: …'")
        if header["level"] not in LEVELS:
            raise ConfigError(f"{path.name}: level deve ser 'error' ou 'warning', recebido {header['level']!r}")
        check_id = match.group(1)
        if check_id in checks:
            raise ConfigError(f"check {check_id} repetido: {checks[check_id].path.name} e {path.name}")
        checks[check_id] = SqlCheck(check_id, header["level"], header["title"], text, path)
    if not checks:
        raise ConfigError(f"nenhum arquivo de check (CNN_*.sql) em {directory}")
    return [checks[key] for key in sorted(checks)]


def _run_sql_check(conn: Connection, check: SqlCheck, sample_size: int) -> CheckResult:
    result = conn.exec_driver_sql(check.sql)
    columns = tuple(result.keys())
    rows = [tuple(row) for row in result.fetchall()]
    return CheckResult(check.check_id, check.level, check.title, len(rows), columns, tuple(rows[:sample_size]))


def player_name_conflicts_check(raw_dir: Path, manifest_path: Path, sample_size: int = 5) -> CheckResult:
    """C11 (aviso): o mesmo player_id com nomes diferentes em arquivos diferentes.

    Só o NOME (spec, seção 11). Apelido e país divergentes já saem como aviso na carga (D24).
    """
    _, conflicts = build_player_table(raw_dir, read_manifest(manifest_path))
    rows = []
    for conflict in (c for c in conflicts if c.attribute == "player_name"):
        seen = ", ".join(f"{value!r} em {n}" for value, n in sorted(conflict.counts.items(), key=lambda kv: (-kv[1], str(kv[0]))))
        rows.append((conflict.player_id, seen, conflict.chosen))
    return CheckResult(
        "C11", "warning", "O mesmo jogador com nomes diferentes em arquivos diferentes (vale o mais frequente)",
        len(rows), ("player_id", "names", "stored"), tuple(rows[:sample_size]),
    )


def run_checks(
    conn: Connection,
    directory: Path,
    *,
    raw_dir: Path | None = None,
    manifest_path: Path | None = None,
    sample_size: int = 5,
) -> list[CheckResult]:
    """Executa os checks SQL e, se `raw_dir` e `manifest_path` forem dados, o C11 (Python). Só lê."""
    results = [_run_sql_check(conn, check, sample_size) for check in load_sql_checks(directory)]
    if raw_dir is not None and manifest_path is not None:
        results.append(player_name_conflicts_check(raw_dir, manifest_path, sample_size))
    return results


def has_errors(results: Sequence[CheckResult]) -> bool:
    """Só um check de nível `error` com linhas derruba a execução; avisos nunca."""
    return any(r.level == "error" and r.violations for r in results)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def format_report(results: Sequence[CheckResult]) -> str:
    lines = []
    for r in results:
        if r.violations == 0:
            status, tail = "OK", ""
        else:
            status = "FALHA" if r.level == "error" else "AVISO"
            tail = f"  [{_plural(r.violations, 'linha')}]"
        lines.append(f"{r.check_id}  {status:<5}  {r.title}{tail}")
        for row in r.sample:
            lines.append("        " + ", ".join(f"{column}={value}" for column, value in zip(r.columns, row)))
        hidden = r.violations - len(r.sample)
        if hidden > 0:
            lines.append(f"        ... mais {hidden}")
    errors = sum(1 for r in results if r.level == "error" and r.violations)
    warnings = sum(1 for r in results if r.level == "warning" and r.violations)
    lines.append(f"resumo: {_plural(len(results), 'check')} | {_plural(errors, 'erro')} | {_plural(warnings, 'aviso')}")
    return "\n".join(lines)
