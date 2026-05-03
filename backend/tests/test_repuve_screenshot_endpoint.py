"""Tests del endpoint POST /api/repuve/screenshot.

Mockeamos `scan_repuve_screenshot` para no invocar Claude — verificamos
el contrato del endpoint, las validaciones y el routing entre los
casos (modal no detectado, OCR irrelevante, parse exitoso).
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.repuve_screenshot_ocr import RepuveScreenshotResult


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)


def _fake_image_b64(size_chars: int = 200) -> str:
    raw = b"\xff\xd8\xff\xe0" + b"X" * (size_chars - 4)
    return base64.b64encode(raw).decode()


def _patch_ocr(result: RepuveScreenshotResult):
    return patch(
        "app.api.repuve_screenshot.scan_repuve_screenshot",
        return_value=result,
    )


def test_screenshot_requires_plate_or_vin(client: TestClient) -> None:
    res = client.post(
        "/api/repuve/screenshot",
        json={"image_base64": _fake_image_b64()},
    )
    assert res.status_code == 400
    assert "placa" in res.json()["detail"].lower()


def test_screenshot_validates_image_size_limit(client: TestClient) -> None:
    huge = "A" * 2_000_001
    res = client.post(
        "/api/repuve/screenshot",
        json={"plate": "ABC1234", "image_base64": huge},
    )
    assert res.status_code == 413


def test_screenshot_no_modal_returns_clear_error(client: TestClient) -> None:
    fake = RepuveScreenshotResult(
        text="",
        found_modal=False,
        confidence="high",
        notes="captura de Google",
    )
    with _patch_ocr(fake):
        res = client.post(
            "/api/repuve/screenshot",
            json={"plate": "ABC1234", "image_base64": _fake_image_b64()},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["queried"] is False
    assert body["raw_status"] == "screenshot_no_modal"
    assert "modal" in body["error"].lower()


def test_screenshot_text_not_repuve_returns_specific_error(
    client: TestClient,
) -> None:
    fake = RepuveScreenshotResult(
        text="Bienvenido al portal de servicios SAT",
        found_modal=True,
        confidence="high",
        notes="parece SAT no REPUVE",
    )
    with _patch_ocr(fake):
        res = client.post(
            "/api/repuve/screenshot",
            json={"plate": "ABC1234", "image_base64": _fake_image_b64()},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["queried"] is False
    assert body["raw_status"] == "screenshot_not_repuve"


def test_screenshot_sin_reportes_parsed_via_canonical_parser(
    client: TestClient,
) -> None:
    fake = RepuveScreenshotResult(
        text="Sin reportes de robo. Situación legal: Regular.",
        found_modal=True,
        confidence="high",
        notes="modal claro",
    )
    with _patch_ocr(fake):
        res = client.post(
            "/api/repuve/screenshot",
            json={"plate": "ABC1234", "image_base64": _fake_image_b64()},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["queried"] is True
    assert body["is_stolen"] is False
    assert body["raw_status"] == "sin_reportes"
    assert body["has_legal_status"] is True
    assert body["plate"] == "ABC1234"
    assert body["ocr_confidence"] == "high"


def test_screenshot_robado_parsed_via_canonical_parser(
    client: TestClient,
) -> None:
    fake = RepuveScreenshotResult(
        text="Presenta reporte de robo activo. Vehículo robado.",
        found_modal=True,
        confidence="medium",
        notes="",
    )
    with _patch_ocr(fake):
        res = client.post(
            "/api/repuve/screenshot",
            json={"plate": "ABC1234", "image_base64": _fake_image_b64()},
        )
    body = res.json()
    assert body["queried"] is True
    assert body["is_stolen"] is True
    assert body["raw_status"] == "robado"


def test_screenshot_no_encontrado_returns_queried_false(
    client: TestClient,
) -> None:
    fake = RepuveScreenshotResult(
        text="No se encontró registro del vehículo en REPUVE.",
        found_modal=True,
        confidence="high",
        notes="",
    )
    with _patch_ocr(fake):
        res = client.post(
            "/api/repuve/screenshot",
            json={"plate": "ZZZ9999", "image_base64": _fake_image_b64()},
        )
    body = res.json()
    assert body["queried"] is False
    assert body["raw_status"] == "no_encontrado"


def test_screenshot_ocr_runtime_error_returns_503(client: TestClient) -> None:
    """Si Claude esta caido o falta API key, devolvemos 503 explicito."""
    with patch(
        "app.api.repuve_screenshot.scan_repuve_screenshot",
        side_effect=RuntimeError("ANTHROPIC_API_KEY no configurada"),
    ):
        res = client.post(
            "/api/repuve/screenshot",
            json={"plate": "ABC1234", "image_base64": _fake_image_b64()},
        )
    assert res.status_code == 503


def test_screenshot_accepts_vin_only(client: TestClient) -> None:
    fake = RepuveScreenshotResult(
        text="Sin reportes de robo",
        found_modal=True,
        confidence="high",
        notes="",
    )
    with _patch_ocr(fake):
        res = client.post(
            "/api/repuve/screenshot",
            json={
                "vin": "1HGBH41JXMN109186",
                "image_base64": _fake_image_b64(),
            },
        )
    assert res.status_code == 200
    assert res.json()["vin"] == "1HGBH41JXMN109186"


def test_screenshot_passes_through_ocr_metadata(client: TestClient) -> None:
    fake = RepuveScreenshotResult(
        text="Sin reportes de robo",
        found_modal=True,
        confidence="medium",
        notes="captura algo borrosa pero legible",
    )
    with _patch_ocr(fake):
        res = client.post(
            "/api/repuve/screenshot",
            json={"plate": "ABC1234", "image_base64": _fake_image_b64()},
        )
    body = res.json()
    assert body["ocr_confidence"] == "medium"
    assert "borrosa" in body["ocr_notes"]
