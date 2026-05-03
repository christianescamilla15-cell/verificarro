"""Pure-function tests del parser de OCR del modal REPUVE.

No invoca Claude — testea solo la sanitizacion del JSON crudo y la
heuristica `looks_like_repuve_text`. La invocacion real de Claude
queda para smoke tests con foto + API key disponibles.
"""

from __future__ import annotations

from app.services.repuve_screenshot_ocr import (
    RepuveScreenshotResult,
    looks_like_repuve_text,
    parse_screenshot_response,
)


def test_parse_clean_response_sin_reportes() -> None:
    raw = (
        '{"text": "Sin reportes de robo. Situacion legal: Regular.",'
        ' "found_modal": true, "confidence": "high",'
        ' "notes": "modal claro"}'
    )
    r = parse_screenshot_response(raw)
    assert r.text.startswith("Sin reportes")
    assert r.found_modal is True
    assert r.confidence == "high"


def test_parse_clean_response_robado() -> None:
    raw = (
        '{"text": "Vehiculo robado. Reporte de robo activo.",'
        ' "found_modal": true, "confidence": "medium", "notes": ""}'
    )
    r = parse_screenshot_response(raw)
    assert "robado" in r.text.lower()
    assert r.found_modal is True


def test_parse_no_modal_when_screenshot_irrelevant() -> None:
    raw = (
        '{"text": "", "found_modal": false, "confidence": "high",'
        ' "notes": "captura es de Google, no REPUVE"}'
    )
    r = parse_screenshot_response(raw)
    assert r.found_modal is False
    assert r.text == ""
    assert "Google" in r.notes


def test_parse_invalid_json_returns_safe_default() -> None:
    r = parse_screenshot_response("not json at all")
    assert r.found_modal is False
    assert r.text == ""
    assert r.confidence == "low"
    # Notes ahora incluye un sample del raw para debug
    assert "JSON" in r.notes
    assert "not json at all" in r.notes


def test_parse_extracts_json_from_markdown_fence() -> None:
    """Claude PDFs devuelven el JSON envuelto en ```json ... ```."""
    raw = (
        "Aqui esta el JSON solicitado:\n"
        "```json\n"
        '{"text": "Sin reportes", "found_modal": true, '
        '"confidence": "high", "notes": "PDF claro"}\n'
        "```"
    )
    r = parse_screenshot_response(raw)
    assert r.found_modal is True
    assert r.text == "Sin reportes"
    assert r.confidence == "high"


def test_parse_extracts_json_from_text_with_intro() -> None:
    """Claude a veces precede el JSON con texto, sin markdown fence."""
    raw = (
        "Despues de leer el documento, aqui esta el resultado:\n\n"
        '{"text": "Vehiculo robado", "found_modal": true, '
        '"confidence": "medium", "notes": ""}'
    )
    r = parse_screenshot_response(raw)
    assert r.found_modal is True
    assert "robado" in r.text.lower()


def test_parse_invalid_confidence_downgrades_to_low() -> None:
    raw = (
        '{"text": "Sin reportes", "found_modal": true,'
        ' "confidence": "ultra-high", "notes": ""}'
    )
    r = parse_screenshot_response(raw)
    assert r.confidence == "low"


def test_parse_found_modal_true_but_text_empty_is_treated_as_not_found() -> None:
    """Defensa: si Claude marca found_modal=true pero text vacio, lo
    tratamos como no encontrado para evitar pasar string vacio al parser
    canonico (que devolveria queried=False ambiguamente).
    """
    raw = (
        '{"text": "   ", "found_modal": true, "confidence": "high",'
        ' "notes": "creo que vi un modal"}'
    )
    r = parse_screenshot_response(raw)
    assert r.found_modal is False
    assert r.confidence == "low"
    assert "vacio" in r.notes


def test_parse_truncates_excessive_text() -> None:
    """Defensa: si Claude alucinó un texto enorme, lo cortamos a 4KB."""
    huge = "robo " * 5000  # 25KB
    raw = (
        '{"text": "'
        + huge.replace('"', "")
        + '", "found_modal": true, "confidence": "high", "notes": ""}'
    )
    r = parse_screenshot_response(raw)
    assert len(r.text.encode("utf-8")) <= 8_000


def test_parse_notes_truncated_to_500_chars() -> None:
    long_notes = "X" * 1000
    raw = (
        '{"text": "Sin reportes", "found_modal": true,'
        ' "confidence": "high", "notes": "' + long_notes + '"}'
    )
    r = parse_screenshot_response(raw)
    assert len(r.notes) <= 500


def test_dataclass_is_frozen() -> None:
    """RepuveScreenshotResult debe ser inmutable para evitar mutaciones
    accidentales corriente abajo."""
    import dataclasses

    r = RepuveScreenshotResult(
        text="x", found_modal=True, confidence="high", notes="",
    )
    try:
        r.text = "y"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("RepuveScreenshotResult debe ser frozen")


# -- looks_like_repuve_text ---------------------------------------------


def test_looks_like_accepts_sin_reportes() -> None:
    assert looks_like_repuve_text("Sin reportes de robo")


def test_looks_like_accepts_robado_acentuado() -> None:
    assert looks_like_repuve_text("Vehículo robado registrado")


def test_looks_like_accepts_no_encontrado() -> None:
    assert looks_like_repuve_text("No se encontro registro del vehiculo")


def test_looks_like_accepts_situacion_legal() -> None:
    assert looks_like_repuve_text("Situación legal: Regular")


def test_looks_like_rejects_empty() -> None:
    assert not looks_like_repuve_text("")


def test_looks_like_rejects_unrelated_text() -> None:
    assert not looks_like_repuve_text(
        "Bienvenido a Google. Buscar | Imagenes | Videos"
    )


def test_looks_like_accepts_repuve_brand_alone() -> None:
    """Aunque no haya marker de robo/legal, si la palabra REPUVE
    aparece, asumimos que estamos en el contexto correcto y dejamos al
    parser canonico decidir."""
    assert looks_like_repuve_text("REPUVE consulta ciudadana")
