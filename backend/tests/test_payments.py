"""Tests de los endpoints de pagos.

Mockean el SDK de Mercado Pago — los tests NO hacen red. La fixture
`client` usa SQLite in-memory con override del dependency
`get_async_session` para aislar cada test.
"""

from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.payments import _map_mp_status
from app.db.base import Base
from app.db.models import Payment, PaymentStatus
from app.db.session import get_async_session
from app.main import app
from app.services.mercadopago import CheckoutPreference, MpPaymentInfo


@pytest_asyncio.fixture
async def db_factory():
    """Engine + factory in-memory por test, con teardown."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def client(db_factory):
    """TestClient con override del dependency de DB."""
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
# _map_mp_status helper


@pytest.mark.parametrize(
    ("mp_status", "expected"),
    [
        ("approved", PaymentStatus.PAID),
        ("pending", PaymentStatus.PENDING),
        ("in_process", PaymentStatus.PENDING),
        ("rejected", PaymentStatus.FAILED),
        ("cancelled", PaymentStatus.FAILED),
        ("refunded", PaymentStatus.REFUNDED),
        ("charged_back", PaymentStatus.REFUNDED),
        ("unknown_status", PaymentStatus.PENDING),  # fallback
    ],
)
def test_map_mp_status(mp_status: str, expected: PaymentStatus) -> None:
    assert _map_mp_status(mp_status) == expected


# ---------------------------------------------------------------------------
# /api/payments/checkout


def _fake_preference() -> CheckoutPreference:
    return CheckoutPreference(
        preference_id="pref-test-123",
        init_point="https://www.mercadopago.com.mx/checkout/v1/pay/pref-test-123",
        sandbox_init_point="https://sandbox.mercadopago.com.mx/checkout/v1/pay/pref-test-123",
        external_reference="ext-ref-from-test",
    )


def test_checkout_creates_payment_pending_and_calls_mp(client) -> None:
    with patch(
        "app.api.payments.create_preference", return_value=_fake_preference()
    ) as mock_create:
        res = client.post("/api/payments/checkout", json={
            "listing_url": "https://auto.mercadolibre.com.mx/MLM-1234-honda-civic",
            "tier": "basic",
            "title_hint": "Honda Civic 2018",
        })
    assert res.status_code == 200
    body = res.json()
    assert body["amount_mxn"] == 49.0
    assert body["tier"] == "basic"
    assert body["init_point"].startswith("https://")
    assert mock_create.called
    # El title pasado a MP incluye el hint
    call_kwargs = mock_create.call_args.kwargs
    assert "Honda Civic 2018" in call_kwargs["title"]


def test_checkout_premium_tier_charges_99(client) -> None:
    with patch(
        "app.api.payments.create_preference", return_value=_fake_preference()
    ):
        res = client.post("/api/payments/checkout", json={"tier": "premium"})
    assert res.status_code == 200
    assert res.json()["amount_mxn"] == 99.0


def test_checkout_invalid_tier_returns_422(client) -> None:
    res = client.post("/api/payments/checkout", json={"tier": "deluxe"})
    assert res.status_code == 422


def test_checkout_mp_failure_returns_503(client) -> None:
    with patch(
        "app.api.payments.create_preference",
        side_effect=RuntimeError("MP timeout"),
    ):
        res = client.post("/api/payments/checkout", json={"tier": "basic"})
    assert res.status_code == 503
    assert "Mercado Pago" in res.json()["detail"]


# ---------------------------------------------------------------------------
# /api/payments/webhook


def _seed_payment(db_factory, external_ref: str = "webhook-ref-1") -> str:
    """Helper síncrono que crea un Payment pending y devuelve su id.

    Usa el factory directo porque corre fuera del request lifecycle.
    """
    import asyncio

    async def _seed() -> str:
        async with db_factory() as s:
            p = Payment(
                amount_mxn=49.0,
                mp_external_reference=external_ref,
                status=PaymentStatus.PENDING,
                mp_preference_id="pref-seed-1",
            )
            s.add(p)
            await s.commit()
            return p.id

    return asyncio.run(_seed())


def test_webhook_payment_approved_updates_status(client, db_factory) -> None:
    external_ref = "webhook-ref-approved"
    payment_id = _seed_payment(db_factory, external_ref)

    info = MpPaymentInfo(
        payment_id="mp-pay-999",
        status="approved",
        status_detail="accredited",
        external_reference=external_ref,
        transaction_amount=49.0,
    )
    with patch("app.api.payments.get_payment_info", return_value=info):
        res = client.post("/api/payments/webhook", json={
            "type": "payment",
            "data": {"id": "mp-pay-999"},
        })
    assert res.status_code == 200

    # Verificamos en DB
    import asyncio

    async def _check():
        async with db_factory() as s:
            r = await s.execute(
                select(Payment).where(Payment.id == payment_id)
            )
            return r.scalar_one()

    p = asyncio.run(_check())
    assert p.status == PaymentStatus.PAID
    assert p.mp_payment_id == "mp-pay-999"
    assert p.paid_at is not None


def test_webhook_unknown_external_reference_returns_204(client) -> None:
    info = MpPaymentInfo(
        payment_id="mp-pay-orphan",
        status="approved",
        status_detail="ok",
        external_reference="ref-that-doesnt-exist",
        transaction_amount=49.0,
    )
    with patch("app.api.payments.get_payment_info", return_value=info):
        res = client.post("/api/payments/webhook", json={
            "type": "payment", "data": {"id": "mp-pay-orphan"},
        })
    # No ruido — ack al webhook con 204 igual.
    assert res.status_code == 200


def test_webhook_non_payment_topic_ignored(client) -> None:
    """Topics tipo `merchant_order` los ignoramos con 204 limpio."""
    with patch("app.api.payments.get_payment_info") as mock_get:
        res = client.post("/api/payments/webhook", json={
            "type": "merchant_order", "data": {"id": "12345"},
        })
        assert mock_get.called is False
    assert res.status_code == 200


def test_webhook_idempotent_duplicate_does_nothing(client, db_factory) -> None:
    """Webhook duplicado para un Payment ya en `paid` no cambia nada."""
    external_ref = "webhook-ref-dup"
    _seed_payment(db_factory, external_ref)

    info = MpPaymentInfo(
        payment_id="mp-pay-dup",
        status="approved",
        status_detail="accredited",
        external_reference=external_ref,
        transaction_amount=49.0,
    )
    with patch("app.api.payments.get_payment_info", return_value=info):
        client.post("/api/payments/webhook", json={
            "type": "payment", "data": {"id": "mp-pay-dup"},
        })
        # Segundo webhook idéntico
        res = client.post("/api/payments/webhook", json={
            "type": "payment", "data": {"id": "mp-pay-dup"},
        })
    assert res.status_code == 200  # sin error, no-op


# ---------------------------------------------------------------------------
# Webhook HMAC validation (MOD-001)
#
# Cuando MP_WEBHOOK_SECRET está configurado, el handler debe rechazar
# 401 cualquier POST sin x-signature válido. Sin esto un atacante podría
# disparar unlock_report_for_payment para reportes ajenos. Test cubre:
#   - secret vacío (default actual) → no validamos, 200 (backward-compat)
#   - secret set + signature válida → 200
#   - secret set + signature inválida → 401
#   - secret set + signature ausente → 401
#   - secret set + manifest manipulado (id distinto) → 401


def _now_ts() -> str:
    """Timestamp actual (epoch seconds) — usado para que los tests
    pasen el replay-window check de 600s en _verify_mp_signature (M-2)."""
    from datetime import UTC, datetime
    return str(int(datetime.now(UTC).timestamp()))


def _hmac_signature(
    secret: str, payment_id: str, ts: str | None = None, request_id: str = "",
) -> str:
    """Genera el header x-signature como lo haría MP. Si `ts` no se
    provee, usa el actual (para pasar replay-window check)."""
    import hashlib
    import hmac as _hmac
    if ts is None:
        ts = _now_ts()
    segments = []
    if payment_id:
        segments.append(f"id:{payment_id};")
    if request_id:
        segments.append(f"request-id:{request_id};")
    segments.append(f"ts:{ts};")
    manifest = "".join(segments)
    sig = _hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"ts={ts},v1={sig}"


def test_webhook_no_secret_skips_validation(client, db_factory) -> None:
    """Backward-compat: si MP_WEBHOOK_SECRET vacío, sigue funcionando
    sin validar (modo dev/MVP). Solo log warning."""
    external_ref = "webhook-no-secret"
    _seed_payment(db_factory, external_ref)
    info = MpPaymentInfo(
        payment_id="mp-pay-nosec", status="approved", status_detail="ok",
        external_reference=external_ref, transaction_amount=49.0,
    )
    # Settings default: mp_webhook_secret = ""
    with patch("app.api.payments.get_payment_info", return_value=info):
        res = client.post("/api/payments/webhook", json={
            "type": "payment", "data": {"id": "mp-pay-nosec"},
        })  # sin x-signature header
    assert res.status_code == 200


def test_webhook_with_secret_valid_signature_accepted(client, db_factory) -> None:
    external_ref = "webhook-valid-sig"
    _seed_payment(db_factory, external_ref)
    secret = "test-secret-abc-123"
    payment_id = "mp-pay-valid"
    sig_header = _hmac_signature(secret, payment_id)  # ts=now

    info = MpPaymentInfo(
        payment_id=payment_id, status="approved", status_detail="ok",
        external_reference=external_ref, transaction_amount=49.0,
    )
    fake_settings = type("S", (), {
        "mp_webhook_secret": secret,
        "price_basic_mxn": 49.0, "price_premium_mxn": 99.0,
        "price_search_mxn": 199.0, "price_dealer_mxn": 1499.0,
    })()
    with patch("app.api.payments.get_settings", return_value=fake_settings), \
         patch("app.api.payments.get_payment_info", return_value=info):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "payment", "data": {"id": payment_id}},
            headers={"x-signature": sig_header},
        )
    assert res.status_code == 200


def test_webhook_with_secret_missing_signature_returns_401(client) -> None:
    fake_settings = type("S", (), {
        "mp_webhook_secret": "test-secret",
        "price_basic_mxn": 49.0, "price_premium_mxn": 99.0,
        "price_search_mxn": 199.0, "price_dealer_mxn": 1499.0,
    })()
    with patch("app.api.payments.get_settings", return_value=fake_settings):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "payment", "data": {"id": "mp-pay-x"}},
        )  # sin header
    assert res.status_code == 401
    assert "signature" in res.json()["detail"].lower()


def test_webhook_with_secret_invalid_signature_returns_401(client) -> None:
    fake_settings = type("S", (), {
        "mp_webhook_secret": "test-secret",
        "price_basic_mxn": 49.0, "price_premium_mxn": 99.0,
        "price_search_mxn": 199.0, "price_dealer_mxn": 1499.0,
    })()
    with patch("app.api.payments.get_settings", return_value=fake_settings):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "payment", "data": {"id": "mp-pay-x"}},
            headers={"x-signature": f"ts={_now_ts()},v1=garbage_sig"},
        )
    assert res.status_code == 401


def test_webhook_replay_window_rejects_old_signature(client) -> None:
    """M-2: una firma válida pero con `ts` fuera de la ventana de 10 min
    debe rechazarse con 401. Sin esto, un atacante con una firma vieja
    (capturada de logs, MITM, etc.) podría replearla ad infinitum."""
    secret = "replay-window-secret"
    payment_id = "mp-pay-replay"
    old_ts = "1700000000"  # Nov 2023, way fuera de la ventana
    sig_header = _hmac_signature(secret, payment_id, ts=old_ts)
    fake_settings = type("S", (), {
        "mp_webhook_secret": secret,
        "price_basic_mxn": 49.0, "price_premium_mxn": 99.0,
        "price_search_mxn": 199.0, "price_dealer_mxn": 1499.0,
    })()
    with patch("app.api.payments.get_settings", return_value=fake_settings):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "payment", "data": {"id": payment_id}},
            headers={"x-signature": sig_header},
        )
    assert res.status_code == 401


def test_webhook_with_secret_tampered_payment_id_returns_401(client) -> None:
    """Manifest con id distinto al body → HMAC mismatch → 401.
    Esto previene replay attack donde alguien firma para id X pero
    cambia el body a id Y."""
    secret = "test-secret"
    sig_header = _hmac_signature(secret, "mp-pay-aaa")  # ts=now
    fake_settings = type("S", (), {
        "mp_webhook_secret": secret,
        "price_basic_mxn": 49.0, "price_premium_mxn": 99.0,
        "price_search_mxn": 199.0, "price_dealer_mxn": 1499.0,
    })()
    with patch("app.api.payments.get_settings", return_value=fake_settings):
        res = client.post(
            "/api/payments/webhook",
            json={"type": "payment", "data": {"id": "mp-pay-bbb"}},  # id distinto
            headers={"x-signature": sig_header},
        )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# /api/payments/{external_reference} (MOD-005: requiere polling_token)


def _polling_token_for(payment_id: str, external_ref: str) -> str:
    """Recomputa el polling_token con el JWT_SECRET de tests."""
    from app.api.payments import _make_polling_token
    return _make_polling_token(payment_id, external_ref)


def test_payment_status_pending_returns_no_report(client, db_factory) -> None:
    external_ref = "status-ref-pending"
    payment_id = _seed_payment(db_factory, external_ref)
    token = _polling_token_for(payment_id, external_ref)
    res = client.get(f"/api/payments/{external_ref}?token={token}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert body["report_id"] is None
    assert body["report_json"] is None


def test_payment_status_not_found_returns_404(client) -> None:
    res = client.get("/api/payments/does-not-exist?token=anything")
    assert res.status_code == 404


def test_payment_status_without_token_returns_401(client, db_factory) -> None:
    """MOD-005: sin ?token=X el endpoint rechaza, aunque el ref exista."""
    external_ref = "status-ref-no-token"
    _seed_payment(db_factory, external_ref)
    res = client.get(f"/api/payments/{external_ref}")  # sin token
    assert res.status_code == 401
    assert "token" in res.json()["detail"].lower()


def test_payment_status_with_invalid_token_returns_401(
    client, db_factory,
) -> None:
    """Token con HMAC mal calculado → 401, no leak del status."""
    external_ref = "status-ref-bad-token"
    _seed_payment(db_factory, external_ref)
    res = client.get(
        f"/api/payments/{external_ref}?token=garbage-not-real-hmac"
    )
    assert res.status_code == 401


def test_payment_status_with_token_for_other_payment_returns_401(
    client, db_factory,
) -> None:
    """Token válido para Payment A NO permite leer Payment B (binding)."""
    ref_a = "status-ref-a"
    ref_b = "status-ref-b"
    payment_a_id = _seed_payment(db_factory, ref_a)
    _seed_payment(db_factory, ref_b)
    token_a = _polling_token_for(payment_a_id, ref_a)
    # Intento usar token de A para consultar B
    res = client.get(f"/api/payments/{ref_b}?token={token_a}")
    assert res.status_code == 401
