"""Tests del recovery de tareas perdidas (MOD-012).

`recover_orphan_paid_payments()` busca Payments PAID recientes (últimos
30 min) sin ReportRecord linked y re-encola los pipelines. Llamado por
el lifespan startup hook tras un restart de Render.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, PaymentStatus, ReportRecord, ReportStatus
from app.db.session import _set_engine_for_tests, reset_engine_for_tests


@pytest_asyncio.fixture
async def db_factory():
    """Engine in-memory aislado por test, vinculado al singleton del módulo
    para que `get_session_factory()` (usado por recover_orphan_paid_payments)
    use esta misma DB."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    _set_engine_for_tests(engine, factory)
    yield factory
    reset_engine_for_tests()
    await engine.dispose()


def _seed_payment(
    db_factory,
    *,
    status: PaymentStatus,
    paid_at: datetime | None,
    tier: str = "basic",
    has_report: bool = False,
) -> str:
    async def _seed() -> str:
        async with db_factory() as s:
            p = Payment(
                amount_mxn=49.0,
                tier=tier,
                status=status,
                mp_external_reference=f"orphan-test-{datetime.now(UTC).timestamp()}",
                paid_at=paid_at,
            )
            s.add(p)
            await s.flush()
            if has_report:
                r = ReportRecord(
                    listing_hash="h" * 32,
                    score=70,
                    risk_level="green",
                    status=ReportStatus.UNLOCKED,
                    report_json={"score": 70},
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                    payment_id=p.id,
                )
                s.add(r)
            await s.commit()
            return p.id

    return asyncio.run(_seed())


def test_recover_finds_orphan_paid_payment_without_report(db_factory) -> None:
    """Payment PAID hace 5 min sin report → recover lo encola."""
    from app.services.report_generator import recover_orphan_paid_payments

    payment_id = _seed_payment(
        db_factory,
        status=PaymentStatus.PAID,
        paid_at=datetime.now(UTC) - timedelta(minutes=5),
        has_report=False,
    )

    # Mock task functions para que no corran el pipeline real (lento + red)
    with patch(
        "app.services.report_generator.unlock_report_for_payment"
    ) as mock_unlock, patch(
        "app.services.report_generator.generate_report_for_payment"
    ) as mock_generate:
        mock_unlock.return_value = None
        mock_generate.return_value = None
        recovered = asyncio.run(
            recover_orphan_paid_payments()
        )

    assert payment_id in recovered
    # Sin preview → cae al legacy generate
    assert mock_generate.called or mock_unlock.called


def test_recover_skips_payment_with_existing_report(db_factory) -> None:
    """Payment PAID con ReportRecord linked → NO encola (ya hecho)."""
    from app.services.report_generator import recover_orphan_paid_payments

    payment_id = _seed_payment(
        db_factory,
        status=PaymentStatus.PAID,
        paid_at=datetime.now(UTC) - timedelta(minutes=5),
        has_report=True,  # ya tiene report
    )

    recovered = asyncio.run(
        recover_orphan_paid_payments()
    )
    assert payment_id not in recovered


def test_recover_skips_payment_outside_window(db_factory) -> None:
    """Payment PAID hace 1 hora (>30 min ventana) → NO encola.
    Asumimos que ya fue manualmente arreglado o abandonado."""
    from app.services.report_generator import recover_orphan_paid_payments

    payment_id = _seed_payment(
        db_factory,
        status=PaymentStatus.PAID,
        paid_at=datetime.now(UTC) - timedelta(hours=1),
        has_report=False,
    )

    recovered = asyncio.run(
        recover_orphan_paid_payments()
    )
    assert payment_id not in recovered


def test_recover_skips_pending_payments(db_factory) -> None:
    """Payment PENDING (sin pagar) → NO encola, no es orphan."""
    from app.services.report_generator import recover_orphan_paid_payments

    payment_id = _seed_payment(
        db_factory,
        status=PaymentStatus.PENDING,
        paid_at=None,
    )

    recovered = asyncio.run(
        recover_orphan_paid_payments()
    )
    assert payment_id not in recovered


def test_recover_skips_subscription_tiers(db_factory) -> None:
    """Tier search/dealer (preapproval) → NO encola pipeline. La
    activación es manual / via webhook preapproval, no pipeline."""
    from app.services.report_generator import recover_orphan_paid_payments

    payment_id = _seed_payment(
        db_factory,
        status=PaymentStatus.PAID,
        paid_at=datetime.now(UTC) - timedelta(minutes=5),
        tier="search",
        has_report=False,
    )

    recovered = asyncio.run(
        recover_orphan_paid_payments()
    )
    assert payment_id not in recovered


def test_recover_idempotent_when_no_orphans(db_factory) -> None:
    """DB vacía o sin orphans → devuelve [] sin error."""
    from app.services.report_generator import recover_orphan_paid_payments

    recovered = asyncio.run(
        recover_orphan_paid_payments()
    )
    assert recovered == []
