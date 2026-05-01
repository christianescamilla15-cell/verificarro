"""Tests del background task que genera el reporte tras webhook PAID.

Mockea `run_pipeline` para evitar Playwright + scraping en los tests.
Valida persistencia, idempotencia y cache hit.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, PaymentStatus, ReportRecord
from app.db import session as db_session
from app.models.report import (
    ListingData,
    PriceEstimate,
    Report,
    RepuveResult,
    RiskLevel,
    Source,
)
from app.services.report_generator import (
    _hash_listing,
    generate_report_for_payment,
)


def _fake_report() -> Report:
    return Report(
        score=85, risk_level=RiskLevel.GREEN, summary="Reporte de prueba",
        listing=ListingData(
            source=Source.MERCADOLIBRE,
            title="Honda Civic 2018", price_mxn=230000,
            year=2018, make="Honda", model="Civic",
            kilometers=80000, location="CDMX",
        ),
        repuve=RepuveResult(queried=False),
        price=PriceEstimate(comparables_count=0),
    )


@pytest_asyncio.fixture
async def engine_factory():
    """Engine + factory + override del singleton de session module."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Inyecta el factory en el módulo session global
    db_session._engine = engine
    db_session._session_factory = factory

    yield factory

    db_session._engine = None
    db_session._session_factory = None
    await engine.dispose()


# ---------------------------------------------------------------------------
# _hash_listing


def test_hash_listing_deterministic() -> None:
    h1 = _hash_listing("https://x/MLM-1", "ABC123", None)
    h2 = _hash_listing("https://x/MLM-1", "ABC123", None)
    assert h1 == h2


def test_hash_listing_differs_by_url() -> None:
    h1 = _hash_listing("https://x/MLM-1", None, None)
    h2 = _hash_listing("https://x/MLM-2", None, None)
    assert h1 != h2


def test_hash_listing_normalizes_plate_case_and_dashes() -> None:
    h1 = _hash_listing("u", "ABC-123-D", None)
    h2 = _hash_listing("u", "abc123d", None)
    assert h1 == h2


# ---------------------------------------------------------------------------
# generate_report_for_payment


@pytest.mark.asyncio
async def test_generates_report_for_paid_payment(engine_factory) -> None:
    factory = engine_factory
    async with factory() as s:
        p = Payment(
            amount_mxn=49.0,
            mp_external_reference="gen-1",
            status=PaymentStatus.PAID,
            mp_payment_id="mp-1",
            paid_at=datetime.now(UTC),
            listing_url="https://auto.mercadolibre.com.mx/MLM-1234",
        )
        s.add(p)
        await s.commit()
        payment_id = p.id

    with patch(
        "app.services.report_generator.run_pipeline", return_value=_fake_report()
    ) as mock_pipe:
        report_id = await generate_report_for_payment(payment_id)

    assert report_id is not None
    assert mock_pipe.called

    # Verificamos persistencia
    async with factory() as s:
        result = await s.execute(
            select(ReportRecord).where(ReportRecord.id == report_id)
        )
        record = result.scalar_one()
        assert record.payment_id == payment_id
        assert record.score == 85
        assert record.make == "Honda"
        assert record.report_json["score"] == 85


@pytest.mark.asyncio
async def test_idempotent_returns_existing_report(engine_factory) -> None:
    """Si el payment ya tiene reporte, no regenera ni vuelve a llamar
    al pipeline."""
    factory = engine_factory
    async with factory() as s:
        p = Payment(
            amount_mxn=49.0, mp_external_reference="gen-2",
            status=PaymentStatus.PAID, paid_at=datetime.now(UTC),
            listing_url="https://x/MLM-2",
        )
        s.add(p)
        await s.commit()
        payment_id = p.id

    with patch(
        "app.services.report_generator.run_pipeline", return_value=_fake_report()
    ) as mock_pipe:
        report_id_1 = await generate_report_for_payment(payment_id)
        report_id_2 = await generate_report_for_payment(payment_id)

    # Mismo report_id devuelto, pipeline solo llamado UNA vez
    assert report_id_1 == report_id_2
    assert mock_pipe.call_count == 1


@pytest.mark.asyncio
async def test_skip_for_pending_payment(engine_factory) -> None:
    """Solo procesamos payments PAID; pending no debe correr."""
    factory = engine_factory
    async with factory() as s:
        p = Payment(
            amount_mxn=49.0, mp_external_reference="gen-3",
            status=PaymentStatus.PENDING,
        )
        s.add(p)
        await s.commit()
        payment_id = p.id

    with patch("app.services.report_generator.run_pipeline") as mock_pipe:
        result = await generate_report_for_payment(payment_id)
    assert result is None
    assert not mock_pipe.called


@pytest.mark.asyncio
async def test_cache_hit_for_repeated_listing(engine_factory) -> None:
    """Dos payments distintos sobre la misma URL → segundo usa cache."""
    factory = engine_factory
    listing_url = "https://auto.mercadolibre.com.mx/MLM-CACHE"

    async with factory() as s:
        p1 = Payment(
            amount_mxn=49.0, mp_external_reference="cache-1",
            status=PaymentStatus.PAID, paid_at=datetime.now(UTC),
            listing_url=listing_url,
        )
        p2 = Payment(
            amount_mxn=49.0, mp_external_reference="cache-2",
            status=PaymentStatus.PAID, paid_at=datetime.now(UTC),
            listing_url=listing_url,
        )
        s.add_all([p1, p2])
        await s.commit()
        p1_id, p2_id = p1.id, p2.id

    with patch(
        "app.services.report_generator.run_pipeline", return_value=_fake_report()
    ) as mock_pipe:
        rid_1 = await generate_report_for_payment(p1_id)
        rid_2 = await generate_report_for_payment(p2_id)

    # Pipeline solo se llamó UNA vez (segundo fue cache hit)
    assert mock_pipe.call_count == 1
    # Cada payment tiene SU propio ReportRecord (no se reutiliza el row),
    # pero ambos comparten el mismo report_json y score
    assert rid_1 != rid_2
    async with factory() as s:
        r1 = (await s.execute(
            select(ReportRecord).where(ReportRecord.id == rid_1)
        )).scalar_one()
        r2 = (await s.execute(
            select(ReportRecord).where(ReportRecord.id == rid_2)
        )).scalar_one()
        assert r1.score == r2.score
        assert r1.payment_id == p1_id
        assert r2.payment_id == p2_id


@pytest.mark.asyncio
async def test_cache_expired_re_runs_pipeline(engine_factory) -> None:
    """Cache TTL pasado → re-corremos el pipeline."""
    factory = engine_factory
    listing_url = "https://x/MLM-EXPIRED"

    async with factory() as s:
        # Reporte viejo (expirado)
        old_payment = Payment(
            amount_mxn=49.0, mp_external_reference="old-pay",
            status=PaymentStatus.PAID, paid_at=datetime.now(UTC),
            listing_url=listing_url,
        )
        s.add(old_payment)
        await s.flush()
        old_record = ReportRecord(
            listing_hash=_hash_listing(listing_url, None, None),
            score=70, risk_level="green",
            report_json={"score": 70},
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # expirado
            payment_id=old_payment.id,
        )
        s.add(old_record)
        # Nuevo payment con misma URL
        new_payment = Payment(
            amount_mxn=49.0, mp_external_reference="new-pay",
            status=PaymentStatus.PAID, paid_at=datetime.now(UTC),
            listing_url=listing_url,
        )
        s.add(new_payment)
        await s.commit()
        new_id = new_payment.id

    with patch(
        "app.services.report_generator.run_pipeline", return_value=_fake_report()
    ) as mock_pipe:
        await generate_report_for_payment(new_id)

    # Pipeline corrió porque el cache estaba expirado
    assert mock_pipe.called


@pytest.mark.asyncio
async def test_pipeline_failure_returns_none(engine_factory) -> None:
    factory = engine_factory
    async with factory() as s:
        p = Payment(
            amount_mxn=49.0, mp_external_reference="fail-1",
            status=PaymentStatus.PAID, paid_at=datetime.now(UTC),
            listing_url="https://x/fail",
        )
        s.add(p)
        await s.commit()
        payment_id = p.id

    with patch(
        "app.services.report_generator.run_pipeline",
        side_effect=RuntimeError("scraping died"),
    ):
        result = await generate_report_for_payment(payment_id)
    assert result is None
