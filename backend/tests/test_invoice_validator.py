"""Tests del invoice_validator. Pure helpers."""

from __future__ import annotations

from app.analyzers.invoice_validator import (
    _coerce_year,
    validate_invoice_against_listing,
)


def test_empty_extra_returns_empty() -> None:
    assert validate_invoice_against_listing({}) == []
    assert validate_invoice_against_listing(None) == []


def test_matching_data_no_findings() -> None:
    extra = {
        "marca": "Honda", "modelo": "Civic", "año": 2018,
        "niv": "19XFC2F58JE000001",
    }
    findings = validate_invoice_against_listing(
        extra,
        listing_make="Honda", listing_model="Civic", listing_year=2018,
        scanned_vin="19XFC2F58JE000001",
    )
    assert findings == []


def test_make_mismatch_high() -> None:
    extra = {"marca": "Toyota"}
    findings = validate_invoice_against_listing(
        extra, listing_make="Honda", listing_model="Civic",
    )
    assert any(f.severity == "high" and "marca" in f.message for f in findings)


def test_make_substring_match_no_alert() -> None:
    """'Honda Motor Co.' vs 'Honda' debería pasar — tolera substring."""
    extra = {"marca": "Honda Motor Co"}
    findings = validate_invoice_against_listing(
        extra, listing_make="Honda",
    )
    assert not any("marca" in f.message for f in findings)


def test_model_mismatch_high() -> None:
    extra = {"modelo": "Accord"}
    findings = validate_invoice_against_listing(
        extra, listing_make="Honda", listing_model="Civic",
    )
    assert any(f.severity == "high" and "modelo" in f.message.lower() for f in findings)


def test_year_within_tolerance_no_alert() -> None:
    """±1 año = tolerable (modelo año vs fabricación)."""
    extra = {"año": 2017}
    findings = validate_invoice_against_listing(
        extra, listing_year=2018,
    )
    assert findings == []


def test_year_diff_2_3_medium() -> None:
    extra = {"año": 2015}
    findings = validate_invoice_against_listing(
        extra, listing_year=2018,
    )
    assert any(f.severity == "medium" and "2015" in f.message for f in findings)


def test_year_diff_more_than_3_high() -> None:
    extra = {"año": 2010}
    findings = validate_invoice_against_listing(
        extra, listing_year=2018,
    )
    assert any(f.severity == "high" for f in findings)


def test_vin_mismatch_high() -> None:
    extra = {"niv": "JTDEPRAE9LJ000001"}
    findings = validate_invoice_against_listing(
        extra, scanned_vin="19XFC2F58JE000001",
    )
    assert any(
        f.severity == "high" and "PLACA CLONADA" in f.message
        for f in findings
    )


def test_vin_with_dashes_normalized_match() -> None:
    extra = {"niv": "19X-FC2F-58JE-000001"}
    findings = validate_invoice_against_listing(
        extra, scanned_vin="19XFC2F58JE000001",
    )
    assert findings == []


def test_coerce_year_int() -> None:
    assert _coerce_year(2018) == 2018


def test_coerce_year_string() -> None:
    assert _coerce_year("2018") == 2018


def test_coerce_year_invalid() -> None:
    assert _coerce_year("two thousand") is None
    assert _coerce_year(None) is None
    assert _coerce_year(1850) is None  # fuera de rango
    assert _coerce_year(2200) is None
