"""Teste smoke do Passo 1: o ambiente está montado como a spec exige?

Não testa lógica do OddVision (ainda não existe). Verifica três contratos:
1. o interpretador é Python 3.13 (D03);
2. o pacote `oddvision` é importável e vem de src/ via instalação editável (D19);
3. as dependências diretas de execução estão instaladas nas versões fixadas.
"""

import importlib
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Mesmos valores de requirements.txt. Se um mudar lá, este teste obriga a mudar aqui.
PINNED_RUNTIME = {
    "pandas": "3.0.6",
    "psycopg": "3.3.6",
    "SQLAlchemy": "2.0.54",
    "streamlit": "1.64.0",
    "mplsoccer": "1.8.1",
}


def test_python_is_3_13():
    assert sys.version_info[:2] == (3, 13)


def test_oddvision_is_imported_from_src():
    import oddvision

    package_dir = Path(oddvision.__file__).resolve().parent
    assert package_dir == PROJECT_ROOT / "src" / "oddvision"


@pytest.mark.parametrize("distribution, expected", PINNED_RUNTIME.items())
def test_runtime_dependency_pinned_version(distribution, expected):
    assert version(distribution) == expected


@pytest.mark.parametrize(
    "module", ["pandas", "psycopg", "sqlalchemy", "streamlit", "mplsoccer"]
)
def test_runtime_dependency_imports(module):
    importlib.import_module(module)
