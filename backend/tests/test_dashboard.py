"""Tests del tablero `/api/auth/me/dashboard`.

El dashboard agrega: stats de reportes del usuario, gasto total y la
suscripción más reciente. Estos tests cubren los 4 caminos no triviales:
sin reportes, con reportes mixtos, con suscripción activa, con
suscripción vencida.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, PaymentStatus, ReportRecord, ReportStatus, User
from app.db.session import get_async_session
from app.main import app
from app.services.auth import create_session_token


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


def _seed_user(db_factory, email: str = "dealer@example.com") -> tuple[str, str]:
    """Crea un user, retorna (user_id, jwt). Helper sync sobre asyncio.run."""
    async def _create() -> str:
        async with db_factory() as s:
            user = User(email=email)
            s.add(user)
            await s.flush()
            uid = user.id
            await s.commit()
            return uid

    user_id = asyncio.get_event_loop().run_until_complete(_create())
    return user_id, create_session_token(user_id)


def _seed_reports(
    db_factory,
    user_id: str,
    rows: list[dict],
) -> None:
    """Inserta ReportRecord rows. Cada dict puede traer score, risk_level,
    created_at (datetime UTC opcional, default now)."""
    async def _ins():
        async with db_factory() as s:
            for r in rows:
                rec = ReportRecord(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    listing_hash=r.get("listing_hash") or uuid.uuid4().hex,
                    score=r["score"],
                    risk_level=r["risk_level"],
                    status=r.get("status", ReportStatus.UNLOCKED),
                    report_json=r.get("report_json", {"score": r["score"]}),
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                )
                if "created_at" in r:
                    rec.created_at = r["created_at"]
                s.add(rec)
            await s.commit()

    asyncio.get_event_loop().run_until_complete(_ins())


def _seed_payment(
    db_factory,
    user_id: str,
    *,
    tier: str,
    amount_mxn: float,
    paid_at: datetime | None,
    status_value: PaymentStatus = PaymentStatus.PAID,
) -> None:
    async def _ins():
        async with db_factory() as s:
            p = Payment(
                user_id=user_id,
                amount_mxn=amount_mxn,
                tier=tier,
                status=status_value,
                mp_external_reference=str(uuid.uuid4()),
                paid_at=paid_at,
            )
            s.add(p)
            await s.commit()

    asyncio.get_event_loop().run_until_complete(_ins())


# ---------------------------------------------------------------------------


def test_dashboard_unauthenticated_returns_401(client) -> None:
    res = client.get("/api/auth/me/dashboard")
    assert res.status_code == 401


def test_dashboard_empty_user_returns_zeros(client, db_factory) -> None:
    _, jwt = _seed_user(db_factory, "empty@example.com")
    res = client.get(
        "/api/auth/me/dashboard",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["total_reports"] == 0
    assert body["summary"]["reports_this_month"] == 0
    assert body["summary"]["avg_score"] is None
    assert body["summary"]["spent_mxn"] == 0.0
    assert body["subscription"] is None
    assert body["reports"] == []


def test_dashboard_aggregates_mixed_risk_reports(client, db_factory) -> None:
    user_id, jwt = _seed_user(db_factory, "mixed@example.com")
    _seed_reports(
        db_factory,
        user_id,
        [
            {"score": 90, "risk_level": "low"},
            {"score": 60, "risk_level": "medium"},
            {"score": 30, "risk_level": "high"},
            {"score": 30, "risk_level": "high"},
        ],
    )
    _seed_payment(
        db_factory, user_id,
        tier="basic", amount_mxn=49.0, paid_at=datetime.now(UTC),
    )
    _seed_payment(
        db_factory, user_id,
        tier="basic", amount_mxn=49.0, paid_at=datetime.now(UTC),
    )

    res = client.get(
        "/api/auth/me/dashboard",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert res.status_code == 200
    body = res.json()
    s = body["summary"]
    assert s["total_reports"] == 4
    assert s["reports_this_month"] == 4
    assert s["high_risk_count"] == 2
    assert s["medium_risk_count"] == 1
    assert s["low_risk_count"] == 1
    assert s["avg_score"] == 52.5  # (90+60+30+30)/4
    assert s["spent_mxn"] == 98.0
    assert len(body["reports"]) == 4
    assert body["subscription"] is None  # tier basic no es suscripción


def test_dashboard_active_subscription_populated(client, db_factory) -> None:
    user_id, jwt = _seed_user(db_factory, "active-sub@example.com")
    paid_at = datetime.now(UTC) - timedelta(days=5)
    _seed_payment(
        db_factory, user_id,
        tier="search", amount_mxn=199.0, paid_at=paid_at,
    )

    res = client.get(
        "/api/auth/me/dashboard",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    body = res.json()
    sub = body["subscription"]
    assert sub is not None
    assert sub["tier"] == "search"
    assert sub["active"] is True
    assert sub["monthly_cap"] == 50
    assert sub["monthly_used"] == 0


def test_dashboard_expired_subscription_marked_inactive(
    client, db_factory,
) -> None:
    user_id, jwt = _seed_user(db_factory, "expired-sub@example.com")
    # Payment hace 40 días — fuera de la ventana de 30
    paid_at = datetime.now(UTC) - timedelta(days=40)
    _seed_payment(
        db_factory, user_id,
        tier="dealer", amount_mxn=1499.0, paid_at=paid_at,
    )

    res = client.get(
        "/api/auth/me/dashboard",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    body = res.json()
    sub = body["subscription"]
    assert sub is not None
    assert sub["tier"] == "dealer"
    assert sub["active"] is False
    assert sub["monthly_cap"] == 500


def test_dashboard_pending_payment_not_counted_in_spend(
    client, db_factory,
) -> None:
    """Solo Payment.status == paid suma a spent_mxn — un pending no
    debe aparecer aunque tenga amount_mxn."""
    user_id, jwt = _seed_user(db_factory, "pending@example.com")
    _seed_payment(
        db_factory, user_id,
        tier="basic", amount_mxn=49.0, paid_at=datetime.now(UTC),
    )
    _seed_payment(
        db_factory, user_id,
        tier="premium", amount_mxn=99.0,
        paid_at=None,
        status_value=PaymentStatus.PENDING,
    )

    res = client.get(
        "/api/auth/me/dashboard",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert res.json()["summary"]["spent_mxn"] == 49.0
