"""Unit tests para el parser de REPUVE.

Tests puros: HTML del modal de respuesta → `RepuveResult`. Sin red ni
Playwright. La invocación real va en `tests/test_repuve_live.py`,
saltada por default.
"""

import pytest

from app.scrapers.repuve import (
    _is_valid_plate,
    _is_valid_vin,
    _normalize_plate,
    _normalize_vin,
    parse_response,
)


# ---------------------------------------------------------------------------
# parse_response — los 3 caminos


def test_parse_response_sin_reportes() -> None:
    html = """
    <div class="modal-body">
      <h4>Vehículo</h4>
      <p>Marca: HONDA</p>
      <p>Año: 2018</p>
      <p>Sin reportes de robo</p>
      <p>Situación legal: regular</p>
    </div>
    """
    result = parse_response(html, plate="ABC123D")
    assert result.queried is True
    assert result.plate == "ABC123D"
    assert result.is_stolen is False
    assert result.has_legal_status is True
    assert result.raw_status == "sin_reportes"
    assert result.error is None


def test_parse_response_robado() -> None:
    html = """
    <div class="modal-body alert-danger">
      <h4>¡Atención!</h4>
      <p>Este vehículo presenta reporte de robo activo.</p>
      <p>Vehículo robado el 2024-03-15</p>
    </div>
    """
    result = parse_response(html, plate="XYZ789A")
    assert result.queried is True
    assert result.is_stolen is True
    assert result.raw_status == "robado"


def test_parse_response_no_encontrado() -> None:
    html = """
    <div class="modal-body">
      <p>No se encontró información para los datos proporcionados.</p>
    </div>
    """
    result = parse_response(html, plate="WWW000W")
    assert result.queried is False
    assert result.is_stolen is None
    assert result.raw_status == "no_encontrado"
    assert result.error is not None and "no encontrado" in result.error.lower()


def test_parse_response_empty_html() -> None:
    result = parse_response("", plate="ABC123")
    assert result.queried is False
    assert result.error == "REPUVE no respondió"


def test_parse_response_propaga_vin() -> None:
    result = parse_response(
        "<p>Sin reportes de robo</p>", vin="1HGBH41JXMN109186"
    )
    assert result.vin == "1HGBH41JXMN109186"
    assert result.is_stolen is False


def test_parse_response_situacion_legal_irregular() -> None:
    html = "<p>Sin reportes de robo. Situación legal: irregular.</p>"
    result = parse_response(html, plate="ABC123D")
    assert result.is_stolen is False
    assert result.has_legal_status is False


# ---------------------------------------------------------------------------
# Normalization + validation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("abc-123-d", "ABC123D"),
        ("  ABC 123 D ", "ABC123D"),
        ("xyz789a", "XYZ789A"),
        ("123-ABC", "123ABC"),
    ],
)
def test_normalize_plate(raw: str, expected: str) -> None:
    assert _normalize_plate(raw) == expected


@pytest.mark.parametrize(
    ("plate", "expected"),
    [
        ("ABC123D", True),     # 7 char, normalizada
        ("ABC12", True),       # 5 char (mín)
        ("ABC1", False),       # 4 char (corta)
        ("ABCDEFGH", False),   # 8 char (larga)
        ("ABC-123", False),    # tiene guión
        ("", False),
    ],
)
def test_is_valid_plate(plate: str, expected: bool) -> None:
    assert _is_valid_plate(plate) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1hgbh41jxmn109186", "1HGBH41JXMN109186"),
        ("1HG-BH41-JXMN-109186", "1HGBH41JXMN109186"),
    ],
)
def test_normalize_vin(raw: str, expected: str) -> None:
    assert _normalize_vin(raw) == expected


@pytest.mark.parametrize(
    ("vin", "expected"),
    [
        ("1HGBH41JXMN109186", True),  # 17 char OK
        ("1HGBH41JXMN10918", False),  # 16 char
        ("1HGBH41JXMN1091867", False),  # 18 char
        ("", False),
    ],
)
def test_is_valid_vin(vin: str, expected: bool) -> None:
    assert _is_valid_vin(vin) is expected
