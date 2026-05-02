"""Tests del scan-first flow: /api/scan/plate + checkout con report_id.

No hace red: mockea Claude OCR + REPUVE + MP. Usa SQLite in-memory.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, PaymentStatus, ReportRecord, ReportStatus
from app.db.session import get_async_session
from app.main import app
from app.models.report import RepuveResult
from app.services.mercadopago import CheckoutPreference
from app.services.plate_ocr import PlateScanResult
from app.services.smart_scanner import SmartScanResult


@pytest_asyncio.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def client(db_factory):
    async def override_session():
        async with db_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_async_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# parse_scan_response (plate OCR)


def test_parse_scan_response_strips_dashes_and_uppercases() -> None:
    from app.services.plate_ocr import parse_scan_response

    raw = '{"plate": "abc-123-d", "confidence": "high", "notes": "ok"}'
    out = parse_scan_response(raw)
    assert out.plate == "ABC123D"
    assert out.confidence == "high"


def test_parse_scan_response_too_long_drops_confidence() -> None:
    from app.services.plate_ocr import parse_scan_response

    raw = '{"plate": "ABCDEFGH", "confidence": "high", "notes": ""}'
    out = parse_scan_response(raw)
    assert out.plate == "ABCDEFGH"
    assert out.confidence == "low"
    assert "8 caracteres" in out.notes


def test_parse_scan_response_invalid_json_returns_low() -> None:
    from app.services.plate_ocr import parse_scan_response

    out = parse_scan_response("not json")
    assert out.plate == ""
    assert out.confidence == "low"


# ---------------------------------------------------------------------------
# POST /api/scan/plate


def _captcha_repuve(plate=None, vin=None) -> RepuveResult:
    return RepuveResult(
        queried=False,
        plate=plate,
        vin=vin,
        raw_status="captcha_required",
        error="REPUVE pidió reCaptcha.",
    )


def _clean_repuve(plate="ABC123D", vin=None) -> RepuveResult:
    return RepuveResult(
        queried=True,
        plate=plate,
        vin=vin,
        is_stolen=False,
        has_legal_status=True,
        raw_status="sin_reportes",
    )


def _stolen_repuve(plate="XYZ789Q", vin=None) -> RepuveResult:
    return RepuveResult(
        queried=True,
        plate=plate,
        vin=vin,
        is_stolen=True,
        has_legal_status=False,
        raw_status="robado",
    )


def test_scan_plate_manual_creates_preview_record(client, db_factory) -> None:
    with patch(
        "app.services.pipeline._run_repuve", return_value=_clean_repuve()
    ):
        res = client.post("/api/scan/plate", json={"manual_plate": "ABC123D"})
    assert res.status_code == 200, res.json()
    body = res.json()
    assert body["plate"] == "ABC123D"
    assert body["risk_level"] == "green"
    assert body["score"] >= 70
    assert "REPUVE no muestra reporte de robo" in body["summary"]
    assert body["report_id"]

    # DB tiene un ReportRecord status=preview
    import asyncio

    async def _check():
        async with db_factory() as s:
            r = await s.execute(select(ReportRecord))
            return r.scalar_one()

    rec = asyncio.get_event_loop().run_until_complete(_check())
    assert rec.status == ReportStatus.PREVIEW
    assert rec.plate == "ABC123D"


def test_scan_plate_stolen_returns_red(client) -> None:
    with patch(
        "app.services.pipeline._run_repuve",
        return_value=_stolen_repuve(),
    ):
        res = client.post("/api/scan/plate", json={"manual_plate": "XYZ789Q"})
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "red"
    assert "ROBADO" in body["summary"]


def test_scan_plate_captcha_returns_yellow_capped_preview(client) -> None:
    """Sin signal de REPUVE no podemos llamar verde a algo.

    El scoring estándar daría 100/green (sin penalty); el preview
    pipeline lo capa a 50/yellow para no inducir falsa confianza.
    """
    with patch(
        "app.services.pipeline._run_repuve",
        return_value=_captcha_repuve(plate="ABC123D"),
    ):
        res = client.post("/api/scan/plate", json={"manual_plate": "ABC123D"})
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "yellow"
    assert body["score"] == 50
    assert "no se pudo consultar" in body["summary"]
    assert body["report_id"]


def test_scan_plate_invalid_short_plate_returns_400(client) -> None:
    res = client.post("/api/scan/plate", json={"manual_plate": "AB"})
    assert res.status_code == 400


def test_scan_plate_no_input_returns_400(client) -> None:
    res = client.post("/api/scan/plate", json={})
    assert res.status_code == 400


def test_scan_plate_image_uses_smart_scanner_plate(client) -> None:
    """Smart scanner detecta placa en la foto → flow normal de scan."""
    fake_scan = SmartScanResult(
        type="plate", value="ABC123D",
        confidence="high", notes="placa clara",
    )
    with patch(
        "app.api.scan.smart_scan", return_value=fake_scan
    ) as mock_scan, patch(
        "app.services.pipeline._run_repuve", return_value=_clean_repuve()
    ):
        res = client.post(
            "/api/scan/plate",
            json={"image_base64": "x" * 200, "media_type": "image/jpeg"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["plate"] == "ABC123D"
    assert body["detected_type"] == "plate"
    assert body["ocr_confidence"] == "high"
    assert mock_scan.called


def test_scan_plate_image_smart_scanner_detects_vin(client) -> None:
    """Smart scanner detecta VIN → vin populated, no plate."""
    fake_scan = SmartScanResult(
        type="vin", value="19XFC2F58JE000001",
        confidence="high", notes="VIN claro en sticker de puerta",
    )
    with patch(
        "app.api.scan.smart_scan", return_value=fake_scan
    ), patch(
        "app.services.pipeline._run_repuve", return_value=_clean_repuve(vin="19XFC2F58JE000001"),
    ):
        res = client.post(
            "/api/scan/plate",
            json={"image_base64": "x" * 200, "media_type": "image/jpeg"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["vin"] == "19XFC2F58JE000001"
    assert body["plate"] is None
    assert body["detected_type"] == "vin"


def test_scan_plate_image_smart_scanner_detects_invoice(client) -> None:
    """Smart scanner detecta factura → flow especial sin reporte preview."""
    fake_scan = SmartScanResult(
        type="invoice", value="ABCD1234-EF56-7890-ABCD-EF1234567890",
        confidence="high", notes="factura clara",
        extra={
            "folio_fiscal_uuid": "ABCD1234-EF56-7890-ABCD-EF1234567890",
            "rfc_emisor": "AAA010101AAA",
            "marca": "Honda", "modelo": "Civic", "año": 2018,
        },
    )
    with patch("app.api.scan.smart_scan", return_value=fake_scan):
        res = client.post(
            "/api/scan/plate",
            json={"image_base64": "x" * 200, "media_type": "image/jpeg"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["detected_type"] == "invoice"
    assert body["invoice_extra"]["rfc_emisor"] == "AAA010101AAA"
    assert "factura" in body["summary"].lower()


def test_scan_auto_endpoint_classifies_image(client) -> None:
    """`/api/scan/auto` clasifica sin disparar pipeline."""
    fake_scan = SmartScanResult(
        type="plate", value="DEF5678",
        confidence="medium", notes="placa con sombra",
    )
    with patch("app.api.scan.smart_scan", return_value=fake_scan):
        res = client.post(
            "/api/scan/auto",
            json={"image_base64": "x" * 200, "media_type": "image/jpeg"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "plate"
    assert body["value"] == "DEF5678"
    assert body["confidence"] == "medium"


def test_scan_auto_requires_image(client) -> None:
    res = client.post("/api/scan/auto", json={})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# /api/payments/checkout con report_id


def _fake_preference() -> CheckoutPreference:
    return CheckoutPreference(
        preference_id="pref-test-456",
        init_point="https://www.mercadopago.com.mx/checkout/v1/pay/pref-test-456",
        sandbox_init_point="https://sandbox.mercadopago.com.mx/checkout/v1/pay/pref-test-456",
        external_reference="ext-from-scan",
    )


def test_checkout_with_report_id_links_payment_and_snapshots_plate(
    client, db_factory
) -> None:
    """El checkout con report_id enlaza Payment ↔ Report y copia plate."""
    # 1. Scan-first crea preview
    with patch(
        "app.services.pipeline._run_repuve", return_value=_clean_repuve()
    ):
        scan_res = client.post(
            "/api/scan/plate", json={"manual_plate": "ABC123D"}
        )
    report_id = scan_res.json()["report_id"]

    # 2. Checkout con report_id (sin pasar plate explícita)
    with patch(
        "app.api.payments.create_preference", return_value=_fake_preference()
    ):
        res = client.post(
            "/api/payments/checkout",
            json={"report_id": report_id, "tier": "basic"},
        )
    assert res.status_code == 200, res.json()
    payment_id = res.json()["payment_id"]

    # 3. Verifica que el Payment heredó la plate y se enlazó al Report
    import asyncio

    async def _check():
        async with db_factory() as s:
            payment = (
                await s.execute(select(Payment).where(Payment.id == payment_id))
            ).scalar_one()
            report = (
                await s.execute(
                    select(ReportRecord).where(ReportRecord.id == report_id)
                )
            ).scalar_one()
            return payment, report

    payment, report = asyncio.get_event_loop().run_until_complete(_check())
    assert payment.plate == "ABC123D"
    assert report.payment_id == payment_id
    assert report.status == ReportStatus.PREVIEW


def test_checkout_with_unknown_report_id_returns_404(client) -> None:
    with patch(
        "app.api.payments.create_preference", return_value=_fake_preference()
    ):
        res = client.post(
            "/api/payments/checkout",
            json={"report_id": "nonexistent-uuid", "tier": "basic"},
        )
    assert res.status_code == 404


def test_checkout_with_already_unlocked_report_returns_409(
    client, db_factory
) -> None:
    """No permitir doble pago contra el mismo reporte ya desbloqueado."""
    import asyncio

    async def _seed():
        async with db_factory() as s:
            from datetime import UTC, datetime, timedelta

            r = ReportRecord(
                listing_hash="h" * 32,
                status=ReportStatus.UNLOCKED,
                score=80,
                risk_level="green",
                report_json={"score": 80, "risk_level": "green"},
                expires_at=datetime.now(UTC) + timedelta(hours=24),
                plate="ABC123D",
            )
            s.add(r)
            await s.commit()
            return r.id

    report_id = asyncio.get_event_loop().run_until_complete(_seed())

    with patch(
        "app.api.payments.create_preference", return_value=_fake_preference()
    ):
        res = client.post(
            "/api/payments/checkout",
            json={"report_id": report_id, "tier": "basic"},
        )
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# Status endpoint reports preview vs unlocked


def test_payment_status_returns_report_status(client, db_factory) -> None:
    import asyncio
    from datetime import UTC, datetime, timedelta

    async def _seed():
        async with db_factory() as s:
            payment = Payment(
                amount_mxn=49.0,
                mp_external_reference="status-ref-1",
                status=PaymentStatus.PAID,
            )
            s.add(payment)
            await s.flush()
            report = ReportRecord(
                listing_hash="h" * 32,
                status=ReportStatus.PREVIEW,
                score=70,
                risk_level="green",
                report_json={"score": 70, "risk_level": "green"},
                expires_at=datetime.now(UTC) + timedelta(hours=24),
                plate="ABC123D",
                payment_id=payment.id,
            )
            s.add(report)
            await s.commit()
            return payment.mp_external_reference, report.id, payment.id

    ext_ref, report_id, payment_id = asyncio.get_event_loop().run_until_complete(_seed())

    # MOD-005: el endpoint requiere ?token=X. Recomputamos con el helper.
    from app.api.payments import _make_polling_token
    token = _make_polling_token(payment_id, ext_ref)

    res = client.get(f"/api/payments/{ext_ref}?token={token}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "paid"
    assert body["report_id"] == report_id
    assert body["report_status"] == "preview"
    # El JSON completo NO se entrega mientras esté preview
    assert body["report_json"] is None
