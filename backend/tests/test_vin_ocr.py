"""Tests del parser de respuestas OCR de Claude.

Pure-function tests sin mock de Claude. La invocación real está en
`smoke_vin_ocr.py` (futuro) cuando haya API key + foto de prueba.
"""

import pytest

from app.services.vin_ocr import VinScanResult, parse_scan_response


def test_parse_clean_response() -> None:
    raw = '{"vin": "2HGFC2F65JH500001", "confidence": "high", "notes": "VIN claro en tablero"}'
    r = parse_scan_response(raw)
    assert r.vin == "2HGFC2F65JH500001"
    assert r.confidence == "high"
    assert "claro" in r.notes


def test_parse_normalizes_vin_lowercase_and_dashes() -> None:
    """OCR puede devolver lowercase / con guiones — sanitizamos."""
    raw = '{"vin": "2hgfc-2f65-jh500001", "confidence": "high", "notes": ""}'
    r = parse_scan_response(raw)
    assert r.vin == "2HGFC2F65JH500001"


def test_parse_empty_vin_when_unreadable() -> None:
    raw = '{"vin": "", "confidence": "low", "notes": "foto borrosa"}'
    r = parse_scan_response(raw)
    assert r.vin == ""
    assert r.confidence == "low"


def test_parse_vin_with_prohibited_char_lowers_confidence() -> None:
    """Si Claude alucinó un I/O/Q, bajamos confidence + agregamos warning."""
    raw = '{"vin": "2HGFC2F65JH50OO01", "confidence": "high", "notes": "ok"}'
    r = parse_scan_response(raw)
    assert r.confidence == "low"
    assert "I/O/Q" in r.notes


def test_parse_vin_wrong_length_warns() -> None:
    raw = '{"vin": "2HGFC2F65JH50001", "confidence": "high", "notes": ""}'  # 16 chars
    r = parse_scan_response(raw)
    assert r.confidence == "low"
    assert "16 caracteres" in r.notes


def test_parse_invalid_json_returns_empty_low() -> None:
    r = parse_scan_response("not json")
    assert r.vin == ""
    assert r.confidence == "low"


def test_parse_invalid_confidence_falls_back_to_low() -> None:
    raw = '{"vin": "2HGFC2F65JH500001", "confidence": "very_high", "notes": ""}'
    r = parse_scan_response(raw)
    assert r.confidence == "low"


@pytest.mark.parametrize(
    "good_vin",
    [
        "2HGFC2F65JH500001",  # Honda Civic 2018
        "5YFEPRAE0LP000001",  # Toyota Corolla 2020
        "5YJ3E1EA0NF000001",  # Tesla Model 3 2022
    ],
)
def test_parse_real_vins_pass_clean(good_vin: str) -> None:
    raw = f'{{"vin": "{good_vin}", "confidence": "high", "notes": "ok"}}'
    r = parse_scan_response(raw)
    assert r.vin == good_vin
    assert r.confidence == "high"
