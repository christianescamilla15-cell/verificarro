"""Tests del parser puro de `photo_analyzer.parse_findings`.

Sin red, sin mock de Anthropic — solo validamos que JSON crudo de Claude
se mapea correctamente a `PhotoFinding[]`. La integración con la API
vive en `smoke_photo.py` (live, opt-in).
"""

import pytest

from app.analyzers.photo_analyzer import parse_findings


def test_parse_findings_clean_photo() -> None:
    findings = parse_findings('{"issues": []}', photo_index=0)
    assert findings == []


def test_parse_findings_one_issue() -> None:
    raw = (
        '{"issues": [{"issue": "rust", "severity": "medium", '
        '"note": "óxido visible en cofre"}]}'
    )
    findings = parse_findings(raw, photo_index=2)
    assert len(findings) == 1
    f = findings[0]
    assert f.photo_index == 2
    assert f.issue == "rust"
    assert f.severity == "medium"
    assert "óxido" in f.note


def test_parse_findings_multiple_issues() -> None:
    raw = """{
        "issues": [
            {"issue": "paint_mismatch", "severity": "low", "note": "tono distinto en puerta"},
            {"issue": "panel_gap", "severity": "medium", "note": "cofre desalineado"}
        ]
    }"""
    findings = parse_findings(raw, photo_index=1)
    assert len(findings) == 2
    assert {f.issue for f in findings} == {"paint_mismatch", "panel_gap"}
    assert all(f.photo_index == 1 for f in findings)


def test_parse_findings_invalid_enum_dropped() -> None:
    """Items con `issue` fuera del Literal de Pydantic se descartan."""
    raw = (
        '{"issues": ['
        '{"issue": "fake_type", "severity": "high", "note": "x"},'
        '{"issue": "rust", "severity": "low", "note": "óxido leve"}'
        ']}'
    )
    findings = parse_findings(raw, photo_index=0)
    assert len(findings) == 1
    assert findings[0].issue == "rust"


def test_parse_findings_invalid_severity_dropped() -> None:
    raw = '{"issues": [{"issue": "rust", "severity": "critical", "note": "x"}]}'
    findings = parse_findings(raw, photo_index=0)
    assert findings == []


def test_parse_findings_missing_field_dropped() -> None:
    raw = '{"issues": [{"issue": "rust", "note": "falta severity"}]}'
    findings = parse_findings(raw, photo_index=0)
    assert findings == []


def test_parse_findings_truncates_long_note() -> None:
    long = "x" * 500
    raw = f'{{"issues": [{{"issue": "rust", "severity": "low", "note": "{long}"}}]}}'
    findings = parse_findings(raw, photo_index=0)
    assert len(findings) == 1
    assert len(findings[0].note) <= 200


def test_parse_findings_strips_note_whitespace() -> None:
    raw = (
        '{"issues": [{"issue": "rust", "severity": "low", '
        '"note": "  óxido  \\n"}]}'
    )
    findings = parse_findings(raw, photo_index=0)
    assert findings[0].note == "óxido"


def test_parse_findings_bad_json_returns_empty() -> None:
    assert parse_findings("not json{", photo_index=0) == []
    assert parse_findings("", photo_index=0) == []
    assert parse_findings("null", photo_index=0) == []


def test_parse_findings_unexpected_shape_returns_empty() -> None:
    # `issues` no es lista
    assert parse_findings('{"issues": "rust"}', photo_index=0) == []
    # raíz no es objeto
    assert parse_findings('["rust"]', photo_index=0) == []
    # falta el campo `issues`
    assert parse_findings('{"otra": []}', photo_index=0) == []


@pytest.mark.parametrize(
    "issue_type",
    [
        "paint_mismatch",
        "panel_gap",
        "rust",
        "prior_repair",
        "low_quality",
        "watermark_or_stock",
        "other",
    ],
)
def test_parse_findings_accepts_all_valid_enums(issue_type: str) -> None:
    raw = (
        f'{{"issues": [{{"issue": "{issue_type}", "severity": "medium", '
        f'"note": "test"}}]}}'
    )
    findings = parse_findings(raw, photo_index=0)
    assert len(findings) == 1
    assert findings[0].issue == issue_type
