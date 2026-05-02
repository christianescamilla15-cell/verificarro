"""Tests de la encriptación PII Fernet (MOD-032).

Verifica:
- encrypt/decrypt round-trip preserva el valor
- encrypt es no-determinista (IV random) — dos llamadas producen
  tokens distintos pero ambos desencriptan al mismo plaintext
- decrypt_pii_safe maneja legacy plaintext (sin prefix Fernet)
- EncryptedString TypeDecorator integra transparente con SQLAlchemy
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, PaymentStatus
from app.services.crypto import decrypt_pii_safe, encrypt_pii


def test_encrypt_decrypt_roundtrip() -> None:
    plain = "user@example.com"
    token = encrypt_pii(plain)
    assert token != plain
    assert token.startswith("gAAAAA")
    assert decrypt_pii_safe(token) == plain


def test_encrypt_is_non_deterministic() -> None:
    """Cada llamada produce token distinto por IV random — pero ambos
    desencriptan al mismo plaintext."""
    plain = "ABC123"
    token_a = encrypt_pii(plain)
    token_b = encrypt_pii(plain)
    assert token_a != token_b
    assert decrypt_pii_safe(token_a) == plain
    assert decrypt_pii_safe(token_b) == plain


def test_encrypt_none_returns_none() -> None:
    assert encrypt_pii(None) is None


def test_decrypt_none_returns_none() -> None:
    assert decrypt_pii_safe(None) is None


def test_decrypt_legacy_plaintext_returns_as_is() -> None:
    """Datos pre-MOD-032 (sin prefix Fernet) se devuelven sin
    desencriptar — backward compat para migración gradual."""
    legacy_email = "old@example.com"
    legacy_plate = "ABC123D"
    assert decrypt_pii_safe(legacy_email) == legacy_email
    assert decrypt_pii_safe(legacy_plate) == legacy_plate


def test_decrypt_corrupt_token_returns_as_is() -> None:
    """Token con prefix Fernet pero contenido corrupto → log warning
    + return as-is (no tumba la app)."""
    corrupt = "gAAAAAcorrupt-not-a-valid-token"
    result = decrypt_pii_safe(corrupt)
    # Devuelve as-is en lugar de raise
    assert result == corrupt


# ---------------------------------------------------------------------------
# EncryptedString TypeDecorator integration


@pytest_asyncio.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_payment_persists_pii_encrypted_in_db(db_factory) -> None:
    """Insertar un Payment encripta payer_email/plate/vin en disk,
    desencripta al leer."""
    import uuid

    async def _test():
        async with db_factory() as s:
            p = Payment(
                id=str(uuid.uuid4()),
                amount_mxn=49.0,
                status=PaymentStatus.PENDING,
                mp_external_reference=str(uuid.uuid4()),
                payer_email="alice@example.com",
                plate="ABC123D",
                vin="1HGBH41JXMN109186",
            )
            s.add(p)
            await s.commit()
            payment_id = p.id

        # Re-fetch — values vuelven en plaintext (decrypt automático)
        async with db_factory() as s2:
            from sqlalchemy import select
            result = await s2.execute(
                select(Payment).where(Payment.id == payment_id)
            )
            fetched = result.scalar_one()
            assert fetched.payer_email == "alice@example.com"
            assert fetched.plate == "ABC123D"
            assert fetched.vin == "1HGBH41JXMN109186"

        # Verificar que en disk SÍ está encriptado (raw query)
        async with db_factory() as s3:
            from sqlalchemy import text
            raw = await s3.execute(
                text(
                    "SELECT payer_email, plate, vin FROM payments "
                    "WHERE id = :id"
                ),
                {"id": payment_id},
            )
            row = raw.fetchone()
            assert row.payer_email.startswith("gAAAAA")
            assert row.plate.startswith("gAAAAA")
            assert row.vin.startswith("gAAAAA")
            # Verificación: el ciphertext NO contiene el plaintext
            assert "alice@example.com" not in row.payer_email
            assert "ABC123D" not in row.plate

    asyncio.get_event_loop().run_until_complete(_test())


def test_payment_null_pii_persists_as_null(db_factory) -> None:
    """Si los campos PII son None, NO se encripta — siguen None."""
    import uuid

    async def _test():
        async with db_factory() as s:
            p = Payment(
                id=str(uuid.uuid4()),
                amount_mxn=49.0,
                status=PaymentStatus.PENDING,
                mp_external_reference=str(uuid.uuid4()),
                payer_email=None,
                plate=None,
                vin=None,
            )
            s.add(p)
            await s.commit()
            payment_id = p.id

        async with db_factory() as s2:
            from sqlalchemy import select
            result = await s2.execute(
                select(Payment).where(Payment.id == payment_id)
            )
            fetched = result.scalar_one()
            assert fetched.payer_email is None
            assert fetched.plate is None
            assert fetched.vin is None

    asyncio.get_event_loop().run_until_complete(_test())
