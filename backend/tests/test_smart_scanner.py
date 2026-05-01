"""Tests del smart_scanner.parse_scan_response — pure parser, no red."""

from __future__ import annotations

from app.services.smart_scanner import parse_scan_response


def test_parse_plate_basic() -> None:
    raw = '{"type":"plate","value":"ABC123D","confidence":"high","notes":"ok","extra":{}}'
    out = parse_scan_response(raw)
    assert out.type == "plate"
    assert out.value == "ABC123D"
    assert out.confidence == "high"


def test_parse_plate_strips_dashes() -> None:
    raw = '{"type":"plate","value":"ABC-123-D","confidence":"high","notes":"","extra":{}}'
    out = parse_scan_response(raw)
    assert out.value == "ABC123D"


def test_parse_plate_too_short_lowers_confidence() -> None:
    raw = '{"type":"plate","value":"AB","confidence":"high","notes":"","extra":{}}'
    out = parse_scan_response(raw)
    assert out.value == "AB"
    assert out.confidence == "low"
    assert "2 chars" in out.notes


def test_parse_vin_basic() -> None:
    raw = '{"type":"vin","value":"19XFC2F58JE000001","confidence":"high","notes":"sticker claro","extra":{}}'
    out = parse_scan_response(raw)
    assert out.type == "vin"
    assert out.value == "19XFC2F58JE000001"
    assert out.confidence == "high"


def test_parse_vin_wrong_length_lowers_confidence() -> None:
    raw = '{"type":"vin","value":"19XFC","confidence":"high","notes":"","extra":{}}'
    out = parse_scan_response(raw)
    assert out.confidence == "low"
    assert "5 chars" in out.notes


def test_parse_invoice_with_extra() -> None:
    raw = (
        '{"type":"invoice",'
        '"value":"ABCD1234-EF56-7890-ABCD-EF1234567890",'
        '"confidence":"high","notes":"CFDI claro",'
        '"extra":{'
        '"folio_fiscal_uuid":"ABCD1234-EF56-7890-ABCD-EF1234567890",'
        '"rfc_emisor":"AAA010101AAA",'
        '"rfc_receptor":"BBB020202BBB",'
        '"fecha":"2023-05-15",'
        '"total":250000,'
        '"marca":"Honda","modelo":"Civic","año":2018'
        '}}'
    )
    out = parse_scan_response(raw)
    assert out.type == "invoice"
    assert "EF1234567890" in out.value
    assert out.extra["rfc_emisor"] == "AAA010101AAA"
    assert out.extra["marca"] == "Honda"
    assert out.extra["año"] == 2018


def test_parse_unknown() -> None:
    raw = '{"type":"unknown","value":"","confidence":"low","notes":"foto borrosa","extra":{}}'
    out = parse_scan_response(raw)
    assert out.type == "unknown"
    assert out.value == ""


def test_parse_invalid_json_returns_unknown() -> None:
    out = parse_scan_response("garbage not json")
    assert out.type == "unknown"
    assert out.confidence == "low"
    assert "no-JSON" in out.notes


def test_parse_invalid_type_falls_back_to_unknown() -> None:
    raw = '{"type":"banana","value":"x","confidence":"high","notes":"","extra":{}}'
    out = parse_scan_response(raw)
    assert out.type == "unknown"


def test_parse_invalid_confidence_lowers_to_low() -> None:
    raw = '{"type":"plate","value":"ABC123D","confidence":"super","notes":"","extra":{}}'
    out = parse_scan_response(raw)
    assert out.confidence == "low"


def test_parse_extra_not_dict_becomes_empty() -> None:
    raw = '{"type":"invoice","value":"x","confidence":"high","notes":"","extra":"not a dict"}'
    out = parse_scan_response(raw)
    assert out.extra == {}
