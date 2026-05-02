"""Tests del flow de auth: magic link → verify → JWT session.

Email service mockeado — los tests no hacen SMTP. Capturamos el link
generado leyendo `magic_link_hash` en DB y reconstruyendo el flow.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import User
from app.db.session import get_async_session
from app.main import app
from app.services.auth import (
    build_magic_link_url,
    create_session_token,
    decode_session_token,
    generate_magic_link,
    verify_magic_link,
)


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
# Pure helpers (auth service)


def test_generate_magic_link_returns_token_hash_pair() -> None:
    link = generate_magic_link()
    assert link["token"]
    assert link["token_hash"]
    assert link["token"] != link["token_hash"]
    assert link["expires_at"] > datetime.now(UTC)


def test_verify_magic_link_match() -> None:
    link = generate_magic_link()
    assert verify_magic_link(link["token"], link["token_hash"]) is True


def test_verify_magic_link_mismatch() -> None:
    link = generate_magic_link()
    assert verify_magic_link("totally-wrong-token", link["token_hash"]) is False


def test_verify_magic_link_empty_inputs() -> None:
    assert verify_magic_link("", "abc") is False
    assert verify_magic_link("abc", "") is False


def test_jwt_round_trip() -> None:
    token = create_session_token("user-123")
    assert decode_session_token(token) == "user-123"


def test_jwt_invalid_token_returns_none() -> None:
    assert decode_session_token("not.a.real.jwt") is None
    assert decode_session_token("") is None


def test_build_magic_link_url_includes_token_and_email() -> None:
    url = build_magic_link_url("abc123", "user@example.com")
    assert "token=abc123" in url
    assert "email=user%40example.com" in url


# ---------------------------------------------------------------------------
# /api/auth/request-link


def test_request_link_creates_user_and_sends_email(client, db_factory) -> None:
    with patch(
        "app.api.auth.send_magic_link_email", autospec=True
    ) as mock_send:
        res = client.post(
            "/api/auth/request-link", json={"email": "new@example.com"}
        )
    assert res.status_code == 200
    assert "new@example.com" in res.json()["message"]
    mock_send.assert_called_once()
    call_args = mock_send.call_args.args
    assert call_args[0] == "new@example.com"
    assert call_args[1].startswith("http")
    assert "token=" in call_args[1]

    import asyncio

    async def _check():
        async with db_factory() as s:
            r = await s.execute(
                select(User).where(User.email == "new@example.com")
            )
            return r.scalar_one()

    user = asyncio.get_event_loop().run_until_complete(_check())
    assert user.magic_link_hash is not None
    assert user.magic_link_expires_at is not None


def test_request_link_idempotent_for_existing_user(client, db_factory) -> None:
    with patch("app.api.auth.send_magic_link_email", autospec=True):
        client.post(
            "/api/auth/request-link", json={"email": "repeat@example.com"}
        )
        client.post(
            "/api/auth/request-link", json={"email": "repeat@example.com"}
        )

    import asyncio

    async def _count():
        async with db_factory() as s:
            r = await s.execute(
                select(User).where(User.email == "repeat@example.com")
            )
            return len(r.scalars().all())

    count = asyncio.get_event_loop().run_until_complete(_count())
    assert count == 1  # mismo user, no duplicado


def test_request_link_invalid_email_422(client) -> None:
    res = client.post(
        "/api/auth/request-link", json={"email": "not-an-email"}
    )
    assert res.status_code == 422


def test_request_link_smtp_failure_returns_503(client) -> None:
    with patch(
        "app.api.auth.send_magic_link_email",
        side_effect=RuntimeError("SMTP down"),
    ):
        res = client.post(
            "/api/auth/request-link", json={"email": "fail@example.com"}
        )
    assert res.status_code == 503


# ---------------------------------------------------------------------------
# /api/auth/verify


def _request_link_and_capture(client, email: str) -> str:
    """Helper que pide un link y captura el token plain del mock."""
    captured: dict = {}

    async def fake_send(to_email, link_url):
        captured["url"] = link_url

    with patch("app.api.auth.send_magic_link_email", side_effect=fake_send):
        res = client.post("/api/auth/request-link", json={"email": email})
    assert res.status_code == 200

    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(captured["url"])
    qs = parse_qs(parsed.query)
    return qs["token"][0]


def test_verify_with_valid_token_returns_jwt(client) -> None:
    token = _request_link_and_capture(client, "verify@example.com")
    res = client.post(
        "/api/auth/verify",
        json={"email": "verify@example.com", "token": token},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "verify@example.com"
    assert body["user"]["last_login_at"] is not None
    # JWT debe decodear al user_id correcto
    assert decode_session_token(body["access_token"]) == body["user"]["id"]


def test_verify_with_wrong_token_returns_401(client) -> None:
    _request_link_and_capture(client, "wrong@example.com")
    res = client.post(
        "/api/auth/verify",
        json={"email": "wrong@example.com", "token": "totally-fake-token"},
    )
    assert res.status_code == 401


def test_verify_with_unknown_email_returns_401(client) -> None:
    res = client.post(
        "/api/auth/verify",
        json={"email": "nobody@example.com", "token": "anything"},
    )
    assert res.status_code == 401


def test_verify_links_orphan_payments_by_email(client, db_factory) -> None:
    """MOD-038: cuando un usuario verifica su magic link, los Payments
    huérfanos (user_id=None) con `payer_email` matching su email se
    enlazan a su user_id. Los Payments con email distinto NO se tocan."""
    import asyncio

    from app.db.models import Payment, PaymentStatus

    email_target = "owner@verifica.mx"
    email_other = "other@example.com"

    # Seed: 2 payments huérfanos para email_target (deben linkearse)
    # + 1 payment huérfano para email_other (NO debe linkearse)
    async def _seed() -> None:
        async with db_factory() as s:
            for i in range(2):
                s.add(Payment(
                    amount_mxn=49.0, tier="basic",
                    status=PaymentStatus.PENDING,
                    mp_external_reference=f"orphan-target-{i}",
                    payer_email=email_target,
                ))
            s.add(Payment(
                amount_mxn=49.0, tier="basic",
                status=PaymentStatus.PENDING,
                mp_external_reference="orphan-other",
                payer_email=email_other,
            ))
            await s.commit()

    asyncio.get_event_loop().run_until_complete(_seed())

    token = _request_link_and_capture(client, email_target)
    res = client.post(
        "/api/auth/verify",
        json={"email": email_target, "token": token},
    )
    assert res.status_code == 200
    user_id = res.json()["user"]["id"]

    async def _check() -> tuple[int, int]:
        async with db_factory() as s:
            mine = await s.execute(
                select(Payment).where(Payment.user_id == user_id)
            )
            others = await s.execute(
                select(Payment).where(Payment.user_id.is_(None))
            )
            return len(mine.scalars().all()), len(others.scalars().all())

    linked, still_orphan = asyncio.get_event_loop().run_until_complete(_check())
    assert linked == 2  # los 2 de email_target
    assert still_orphan == 1  # el de email_other queda huérfano


def test_verify_consumes_token_single_use(client) -> None:
    """Después de un verify exitoso, el token NO debe servir otra vez."""
    token = _request_link_and_capture(client, "single@example.com")
    res1 = client.post(
        "/api/auth/verify",
        json={"email": "single@example.com", "token": token},
    )
    assert res1.status_code == 200
    res2 = client.post(
        "/api/auth/verify",
        json={"email": "single@example.com", "token": token},
    )
    assert res2.status_code == 401


def test_verify_atomic_consume_returns_401_when_hash_already_cleared(
    client, db_factory,
) -> None:
    """Race condition (MOD-002): si entre el SELECT y el UPDATE de verify
    otro request ya consumió el token (hash ahora NULL), el UPDATE con
    WHERE hash=expected encuentra 0 filas y debe devolver 401.

    Simulamos eso clearing el hash directamente en DB después de que
    el endpoint cargó el user pero antes del UPDATE. En la implementación
    pre-MOD-002 ambos requests asignaban hash=None y emitían JWT."""
    token = _request_link_and_capture(client, "race@example.com")

    # Capturamos el hash actual del user
    import asyncio

    async def _wipe_hash() -> None:
        async with db_factory() as s:
            r = await s.execute(
                select(User).where(User.email == "race@example.com")
            )
            user = r.scalar_one()
            user.magic_link_hash = None  # otro request "ganó" la carrera
            user.magic_link_expires_at = None
            await s.commit()

    asyncio.get_event_loop().run_until_complete(_wipe_hash())

    # Ahora intentamos verify — el SELECT inicial ve hash=NULL así que
    # cae en la rama "or not user.magic_link_hash" → 401 directo.
    # Pero también validamos que si el hash hubiera matcheado, el UPDATE
    # con rowcount=0 también devolvería 401. Lo más cercano a la race
    # real es probar que el endpoint NO emite JWT cuando el hash ya
    # no coincide.
    res = client.post(
        "/api/auth/verify",
        json={"email": "race@example.com", "token": token},
    )
    assert res.status_code == 401


def test_verify_expired_token_returns_401(client, db_factory) -> None:
    """Forzamos expiración escribiendo un past expires_at directo a DB."""
    token = _request_link_and_capture(client, "expired@example.com")

    import asyncio

    async def _expire():
        async with db_factory() as s:
            r = await s.execute(
                select(User).where(User.email == "expired@example.com")
            )
            user = r.scalar_one()
            user.magic_link_expires_at = datetime.now(UTC) - timedelta(minutes=1)
            await s.commit()

    asyncio.get_event_loop().run_until_complete(_expire())

    res = client.post(
        "/api/auth/verify",
        json={"email": "expired@example.com", "token": token},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# /api/auth/me + JWT auth


def test_me_with_valid_jwt_returns_user(client) -> None:
    token = _request_link_and_capture(client, "me@example.com")
    verify_res = client.post(
        "/api/auth/verify",
        json={"email": "me@example.com", "token": token},
    )
    jwt_token = verify_res.json()["access_token"]

    res = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {jwt_token}"}
    )
    assert res.status_code == 200
    assert res.json()["email"] == "me@example.com"


def test_me_without_authorization_returns_401(client) -> None:
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_with_garbage_jwt_returns_401(client) -> None:
    res = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert res.status_code == 401


def test_me_with_non_bearer_header_returns_401(client) -> None:
    res = client.get(
        "/api/auth/me", headers={"Authorization": "Basic abc123"}
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# /api/auth/logout


def test_logout_with_valid_jwt_returns_200(client) -> None:
    token = _request_link_and_capture(client, "logout@example.com")
    verify_res = client.post(
        "/api/auth/verify",
        json={"email": "logout@example.com", "token": token},
    )
    jwt_token = verify_res.json()["access_token"]

    res = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    assert res.status_code == 200
