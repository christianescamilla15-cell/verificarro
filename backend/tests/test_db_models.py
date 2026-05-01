"""Tests CRUD de los modelos ORM contra SQLite in-memory.

Cada test corre con un engine async fresh sobre `:memory:` para
aislamiento completo. NO usa la DB persistente del dev local.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, PaymentStatus, ReportRecord, User


@pytest_asyncio.fixture
async def session():
    """Engine + tablas + sesión con teardown automático."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# User


@pytest.mark.asyncio
async def test_create_and_query_user(session) -> None:
    user = User(email="christian@example.com")
    session.add(user)
    await session.commit()

    result = await session.execute(
        select(User).where(User.email == "christian@example.com")
    )
    fetched = result.scalar_one()
    assert fetched.id == user.id
    assert fetched.email == "christian@example.com"
    assert fetched.created_at is not None
    assert fetched.last_login_at is None


@pytest.mark.asyncio
async def test_user_email_unique(session) -> None:
    session.add(User(email="dup@example.com"))
    await session.commit()
    session.add(User(email="dup@example.com"))
    with pytest.raises(Exception):  # IntegrityError vía SQLAlchemy
        await session.commit()


# ---------------------------------------------------------------------------
# Payment


@pytest.mark.asyncio
async def test_payment_default_status_is_pending(session) -> None:
    payment = Payment(
        amount_mxn=49.0,
        mp_external_reference="ref-001",
    )
    session.add(payment)
    await session.commit()
    assert payment.status == PaymentStatus.PENDING
    assert payment.tier == "basic"


@pytest.mark.asyncio
async def test_payment_external_reference_unique(session) -> None:
    session.add(Payment(amount_mxn=49.0, mp_external_reference="ref-dup"))
    await session.commit()
    session.add(Payment(amount_mxn=49.0, mp_external_reference="ref-dup"))
    with pytest.raises(Exception):
        await session.commit()


@pytest.mark.asyncio
async def test_payment_status_transition(session) -> None:
    payment = Payment(
        amount_mxn=99.0, tier="premium",
        mp_external_reference="ref-002",
    )
    session.add(payment)
    await session.commit()

    payment.status = PaymentStatus.PAID
    payment.mp_payment_id = "mp_abc123"
    payment.paid_at = datetime.now(UTC)
    await session.commit()

    result = await session.execute(
        select(Payment).where(Payment.mp_external_reference == "ref-002")
    )
    fetched = result.scalar_one()
    assert fetched.status == PaymentStatus.PAID
    assert fetched.mp_payment_id == "mp_abc123"


# ---------------------------------------------------------------------------
# ReportRecord


@pytest.mark.asyncio
async def test_create_report_record(session) -> None:
    user = User(email="buyer@example.com")
    session.add(user)
    await session.commit()

    expires = datetime.now(UTC) + timedelta(hours=24)
    report = ReportRecord(
        user_id=user.id,
        source_url="https://auto.mercadolibre.com.mx/MLM-1234",
        listing_hash="abc123",
        make="Honda",
        model="Civic",
        year=2018,
        price_mxn=230_000,
        score=85,
        risk_level="green",
        report_json={"score": 85, "summary": "test"},
        expires_at=expires,
    )
    session.add(report)
    await session.commit()

    result = await session.execute(
        select(ReportRecord).where(ReportRecord.listing_hash == "abc123")
    )
    fetched = result.scalar_one()
    assert fetched.score == 85
    assert fetched.report_json["summary"] == "test"
    assert fetched.user_id == user.id


@pytest.mark.asyncio
async def test_report_anonymous_no_user(session) -> None:
    """Un reporte puede tener `user_id=None` (compra anónima)."""
    report = ReportRecord(
        listing_hash="anon-001",
        score=72, risk_level="green",
        report_json={"score": 72},
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(report)
    await session.commit()
    assert report.user_id is None


# ---------------------------------------------------------------------------
# Relationships y queries combinadas


@pytest.mark.asyncio
async def test_user_payment_report_chain(session) -> None:
    """Flow real: user → payment → report linkado al payment."""
    user = User(email="flow@example.com")
    session.add(user)
    await session.flush()  # asigna id

    payment = Payment(
        user_id=user.id, amount_mxn=49.0,
        mp_external_reference="flow-ref",
        status=PaymentStatus.PAID,
        mp_payment_id="mp_xyz",
        paid_at=datetime.now(UTC),
    )
    session.add(payment)
    await session.flush()

    report = ReportRecord(
        user_id=user.id,
        listing_hash="flow-hash",
        score=88, risk_level="green",
        report_json={"score": 88},
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        payment_id=payment.id,
    )
    session.add(report)
    await session.commit()

    result = await session.execute(
        select(ReportRecord).where(ReportRecord.user_id == user.id)
    )
    user_reports = result.scalars().all()
    assert len(user_reports) == 1
    assert user_reports[0].payment_id == payment.id
