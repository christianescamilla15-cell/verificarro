"""docs/reglas.md es la compuerta «una prueba por regla»: esta prueba evita
que la tabla mienta. Cada `archivo.py::prueba` citado debe existir como
función de prueba en backend/tests/, y cada regla debe citar al menos una.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
DOC = TESTS.parent.parent / "docs" / "reglas.md"

_REF = re.compile(r"`(test_[a-z0-9_]+\.py)::(test_[A-Za-z0-9_]+)`")
_FILA_REGLA = re.compile(r"^\|\s*([A-Z]\d+)\s*\|")


def _referencias() -> list[tuple[str, str]]:
    return _REF.findall(DOC.read_text(encoding="utf-8"))


def test_reglas_doc_cites_tests() -> None:
    assert len(_referencias()) >= 80, "la tabla perdió referencias"


def test_every_cited_test_exists() -> None:
    faltantes = []
    for archivo, prueba in _referencias():
        ruta = TESTS / archivo
        texto = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
        if not re.search(rf"^(async )?def {prueba}\(", texto, re.MULTILINE):
            faltantes.append(f"{archivo}::{prueba}")
    assert faltantes == []


def test_every_rule_row_cites_at_least_one_test() -> None:
    sin_prueba = []
    for linea in DOC.read_text(encoding="utf-8").splitlines():
        fila = _FILA_REGLA.match(linea)
        if fila and not _REF.search(linea):
            sin_prueba.append(fila.group(1))
    assert sin_prueba == []
