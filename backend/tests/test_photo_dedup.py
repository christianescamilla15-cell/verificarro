"""Tests del photo_dedup service. Pure helpers + DB integration con SQLite."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import PhotoHash
from app.services.photo_dedup import (
    _to_signed_64,
    compute_phash,
    find_recycled_photos,
    hamming_distance,
    store_photo_hashes,
)


# ---------------------------------------------------------------------------
# Helpers


def _img_bytes(color: tuple[int, int, int] = (200, 50, 50), size: int = 64) -> bytes:
    img = Image.new("RGB", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _img_pattern(seed: int, size: int = 128) -> bytes:
    """Genera una imagen con estructura única basada en `seed`. pHash
    captura ESTRUCTURA, no color — para tests reales necesitamos imágenes
    con patrones distinguibles."""
    import random as _r
    rng = _r.Random(seed)
    img = Image.new("RGB", (size, size), color=(255, 255, 255))
    pixels = img.load()
    for x in range(size):
        for y in range(size):
            v = (rng.randint(0, 255) + x * 2 + y * 3) % 256
            pixels[x, y] = (v, (v + 50) % 256, (v + 100) % 256)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# compute_phash


def test_compute_phash_returns_int_for_valid_image() -> None:
    out = compute_phash(_img_bytes())
    assert out is not None
    assert isinstance(out, int)


def test_compute_phash_none_for_invalid() -> None:
    assert compute_phash(None) is None
    assert compute_phash(b"") is None
    assert compute_phash(b"not a jpeg, just garbage") is None


def test_compute_phash_identical_images_same_hash() -> None:
    a = compute_phash(_img_pattern(seed=1))
    b = compute_phash(_img_pattern(seed=1))
    assert a == b


def test_compute_phash_different_images_different_hash() -> None:
    """pHash captura ESTRUCTURA, no color. Imágenes con patrones distintos
    deben tener hashes que difieren significativamente."""
    a = compute_phash(_img_pattern(seed=1))
    b = compute_phash(_img_pattern(seed=999))
    assert hamming_distance(a, b) > 5


# ---------------------------------------------------------------------------
# hamming_distance


def test_hamming_distance_identical_zero() -> None:
    assert hamming_distance(0xDEADBEEF, 0xDEADBEEF) == 0


def test_hamming_distance_inverted_max() -> None:
    # 64 bits invertidos = distancia 64
    a = 0
    b = -1  # All bits set en signed 64-bit
    assert hamming_distance(a, b) == 64


def test_hamming_distance_negative_handles_signed() -> None:
    """Asegura que int negativos (representación signed) se interpretan
    correctamente como uint64 antes del XOR."""
    a = _to_signed_64(0xFFFFFFFFFFFFFFFF)  # all-ones
    b = _to_signed_64(0xFFFFFFFFFFFFFFFE)  # all-ones excepto LSB
    assert hamming_distance(a, b) == 1


# ---------------------------------------------------------------------------
# find_recycled_photos + store_photo_hashes (DB integration)


@pytest.mark.asyncio
async def test_no_matches_when_db_empty(session_factory) -> None:
    async with session_factory() as session:
        h1 = compute_phash(_img_pattern(seed=42))
        out = await find_recycled_photos(session, [h1], "listing-A")
        assert out == []


@pytest.mark.asyncio
async def test_match_found_with_different_listing_hash(session_factory) -> None:
    """Si una foto idéntica está en photo_hashes con listing_hash distinto,
    detectamos match y devolvemos info."""
    img = _img_pattern(seed=42)
    h_existing = compute_phash(img)

    async with session_factory() as session:
        # Sembrar hash existente bajo listing-A
        record = PhotoHash(
            listing_hash="listing-A",
            photo_index=0,
            phash=h_existing,
            source_url="https://cdn.ml.com/foto-A.jpg",
            captured_at=datetime.now(UTC),
        )
        session.add(record)
        await session.commit()

        # Buscar match para nuevo listing-B con la MISMA foto
        out = await find_recycled_photos(
            session, [h_existing], "listing-B"
        )

    assert len(out) == 1
    idx, info = out[0]
    assert idx == 0
    assert info["listing_hash"] == "listing-A"
    assert info["hamming"] == 0
    assert info["source_url"] == "https://cdn.ml.com/foto-A.jpg"


@pytest.mark.asyncio
async def test_no_match_with_same_listing_hash(session_factory) -> None:
    """Mismo listing_hash = mismo reporte (re-corrido). NO contamos como
    foto reciclada (el usuario está re-analizando su propio listing)."""
    img = _img_pattern(seed=77)
    h = compute_phash(img)

    async with session_factory() as session:
        session.add(PhotoHash(
            listing_hash="listing-X",
            photo_index=0,
            phash=h,
            captured_at=datetime.now(UTC),
        ))
        await session.commit()

        out = await find_recycled_photos(session, [h], "listing-X")

    assert out == []


@pytest.mark.asyncio
async def test_no_match_when_hamming_too_high(session_factory) -> None:
    """Imágenes con estructura muy distinta no matchean."""
    h_a = compute_phash(_img_pattern(seed=1))
    h_b = compute_phash(_img_pattern(seed=999))

    async with session_factory() as session:
        session.add(PhotoHash(
            listing_hash="listing-A",
            photo_index=0,
            phash=h_a,
            captured_at=datetime.now(UTC),
        ))
        await session.commit()

        out = await find_recycled_photos(session, [h_b], "listing-B")

    # h_a y h_b deben ser muy distintas → sin match
    assert hamming_distance(h_a, h_b) > 5
    assert out == []


@pytest.mark.asyncio
async def test_store_photo_hashes_persists(session_factory) -> None:
    h1 = compute_phash(_img_pattern(seed=10))
    h2 = compute_phash(_img_pattern(seed=20))

    async with session_factory() as session:
        await store_photo_hashes(
            session, "listing-store-test",
            [(h1, "https://x/1.jpg"), (h2, "https://x/2.jpg")],
        )
        await session.commit()

        from sqlalchemy import select
        result = await session.execute(
            select(PhotoHash).where(
                PhotoHash.listing_hash == "listing-store-test"
            )
        )
        rows = list(result.scalars().all())

    assert len(rows) == 2
    indices = sorted(r.photo_index for r in rows)
    assert indices == [0, 1]


@pytest.mark.asyncio
async def test_store_photo_hashes_skips_none(session_factory) -> None:
    """Hashes None (foto no descargada / corrupta) se saltean."""
    h1 = compute_phash(_img_pattern(seed=33))

    async with session_factory() as session:
        await store_photo_hashes(
            session, "listing-with-none",
            [(h1, "url1"), (None, "url2"), (None, None)],
        )
        await session.commit()

        from sqlalchemy import select
        result = await session.execute(
            select(PhotoHash).where(
                PhotoHash.listing_hash == "listing-with-none"
            )
        )
        rows = list(result.scalars().all())

    assert len(rows) == 1
    assert rows[0].photo_index == 0
