"""Background task: cuando un Payment pasa a PAID, generamos el reporte.

Corre en `FastAPI BackgroundTasks` (mismo process). Para MVP es
suficiente — Render Starter aguanta ~10 reportes simultáneos sin
saturar. Cuando volumen lo justifique, mover a Celery + Redis queue.

## Flow

1. Webhook MP confirma payment → llama `enqueue_report_generation(payment_id)`
2. Background task abre nueva DB session (no comparte la del request)
3. Lee el `Payment` row, construye `AnalyzeRequest` con
   `listing_url`, `plate`, `vin` snapshot guardados al checkout
4. Corre `run_pipeline()` (puede tomar ~15-30s con scraping + Claude visión)
5. Persiste `ReportRecord` con `report_json`, indexes, y `payment_id`
   link
6. Frontend hace polling a `/api/payments/{ref}` — cuando ve
   `report_json` poblado, redirige a la vista del reporte

## Cache hit

Si la misma URL se solicitó en las últimas 24h, el ReportRecord
existente se devuelve sin re-correr el pipeline. Ahorra costo y
tiempo en el caso de múltiples compradores investigando el mismo
anuncio (común con Civic populares).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Payment, PaymentStatus, ReportRecord, ReportStatus
from app.db.session import get_session_factory
from app.models.report import AnalyzeRequest, ManualListing, Source
from app.services.pipeline import run_pipeline

logger = logging.getLogger(__name__)


CACHE_TTL_HOURS = 24


async def unlock_report_for_payment(payment_id: str) -> str | None:
    """Sube un ReportRecord de `preview` → `unlocked` corriendo el pipeline completo.

    Diseñado para el scan-first flow (2026-05-01):
    - El preview Report ya existe (creado por `/api/scan/plate`) y tiene
      `payment_id` set tras `/api/payments/checkout`.
    - Aquí buscamos ese preview, ejecutamos `run_pipeline` con la URL
      del anuncio (si el usuario la pegó al checkout) o sin ella, y
      reescribimos `report_json` + `status='unlocked'`.

    Idempotente: si el report ya está unlocked, devolvemos su id sin
    re-correr el pipeline.

    Si no hay preview enlazado (no debería pasar — el webhook ya
    eligió esta función vs `generate_report_for_payment`), caemos al
    flow legacy que crea uno nuevo.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            payment = (
                await session.execute(
                    select(Payment).where(Payment.id == payment_id)
                )
            ).scalar_one_or_none()
            if not payment or payment.status != PaymentStatus.PAID:
                logger.warning(
                    "unlock: Payment %s no PAID (estado=%s)",
                    payment_id,
                    payment.status.value if payment else "missing",
                )
                return None

            preview = (
                await session.execute(
                    select(ReportRecord).where(
                        ReportRecord.payment_id == payment_id
                    )
                )
            ).scalar_one_or_none()

            if preview is None:
                logger.warning(
                    "unlock: Payment %s sin preview, fallback a legacy",
                    payment_id,
                )
                return await generate_report_for_payment(payment_id)

            if preview.status == ReportStatus.UNLOCKED:
                logger.info(
                    "unlock: Report %s ya unlocked, idempotente",
                    preview.id,
                )
                return preview.id

            # Pipeline completo. Si no hay listing_url, run_pipeline
            # explota — capturamos y dejamos el preview como está
            # (el usuario obtuvo lo que se le ofreció: REPUVE detallado).
            req = _build_analyze_request(payment, preview)
            try:
                report = await run_pipeline(req)
            except ValueError as exc:
                logger.warning(
                    "unlock: pipeline no pudo correr (%s) — marcando "
                    "preview como unlocked sin upgrade", exc,
                )
                preview.status = ReportStatus.UNLOCKED
                await session.commit()
                return preview.id

            preview.report_json = report.model_dump(mode="json")
            preview.score = report.score
            preview.risk_level = report.risk_level.value
            preview.make = report.listing.make or None
            preview.model = report.listing.model or None
            preview.year = report.listing.year or None
            preview.price_mxn = report.listing.price_mxn or None
            preview.source_url = (
                str(payment.listing_url) if payment.listing_url else None
            )
            preview.status = ReportStatus.UNLOCKED
            preview.expires_at = datetime.now(UTC) + timedelta(
                hours=CACHE_TTL_HOURS
            )
            await session.commit()
            logger.info(
                "unlock: Report %s upgraded a unlocked (payment %s)",
                preview.id,
                payment_id,
            )
            return preview.id

        except Exception:
            logger.exception(
                "unlock: falló para payment %s", payment_id
            )
            await session.rollback()
            return None


async def generate_report_for_payment(payment_id: str) -> str | None:
    """Genera el reporte para un Payment confirmado. Devuelve el
    `ReportRecord.id` en éxito, None en error.

    Idempotente: si el payment ya tiene un ReportRecord asociado,
    devuelve ese mismo id sin re-generar.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                select(Payment).where(Payment.id == payment_id)
            )
            payment = result.scalar_one_or_none()
            if not payment:
                logger.warning("Payment %s no existe", payment_id)
                return None
            if payment.status != PaymentStatus.PAID:
                logger.warning(
                    "Payment %s no está PAID (estado=%s), skip",
                    payment_id, payment.status.value,
                )
                return None

            # Si ya existe reporte para este payment, idempotente.
            existing = await session.execute(
                select(ReportRecord).where(ReportRecord.payment_id == payment_id)
            )
            existing_report = existing.scalar_one_or_none()
            if existing_report:
                logger.info("Payment %s ya tiene reporte %s",
                            payment_id, existing_report.id)
                return existing_report.id

            # Cache check: misma URL en últimas 24h
            listing_hash = _hash_listing(
                listing_url=payment.listing_url,
                plate=payment.plate,
                vin=payment.vin,
            )
            cache_result = await session.execute(
                select(ReportRecord).where(
                    ReportRecord.listing_hash == listing_hash,
                    ReportRecord.expires_at > datetime.now(UTC),
                ).order_by(ReportRecord.created_at.desc())
            )
            cached = cache_result.scalars().first()
            if cached:
                logger.info(
                    "Cache hit listing_hash=%s → reporte %s",
                    listing_hash, cached.id,
                )
                # Vinculamos este payment con el reporte cacheado
                # (mismo report sirve a múltiples payments)
                new_record = ReportRecord(
                    user_id=payment.user_id,
                    source_url=cached.source_url,
                    listing_hash=listing_hash,
                    make=cached.make,
                    model=cached.model,
                    year=cached.year,
                    price_mxn=cached.price_mxn,
                    score=cached.score,
                    risk_level=cached.risk_level,
                    report_json=cached.report_json,
                    expires_at=cached.expires_at,
                    payment_id=payment_id,
                )
                session.add(new_record)
                await session.commit()
                return new_record.id

            # No cache → corremos el pipeline
            req = _build_analyze_request(payment)
            logger.info("Corriendo pipeline para payment %s", payment_id)
            report = await run_pipeline(req)

            record = ReportRecord(
                user_id=payment.user_id,
                source_url=payment.listing_url,
                listing_hash=listing_hash,
                make=report.listing.make or None,
                model=report.listing.model or None,
                year=report.listing.year or None,
                price_mxn=report.listing.price_mxn or None,
                score=report.score,
                risk_level=report.risk_level.value,
                report_json=report.model_dump(mode="json"),
                expires_at=datetime.now(UTC) + timedelta(hours=CACHE_TTL_HOURS),
                payment_id=payment_id,
            )
            session.add(record)
            await session.commit()
            logger.info("Reporte %s generado para payment %s",
                        record.id, payment_id)
            return record.id

        except Exception:
            logger.exception("Generación de reporte falló para %s", payment_id)
            await session.rollback()
            return None


def _build_analyze_request(
    payment: Payment, preview: ReportRecord | None = None
) -> AnalyzeRequest:
    """Construye `AnalyzeRequest` desde Payment (+ preview opcional).

    Plate/VIN gana del Payment (snapshot al checkout); si está vacío,
    cae al preview (snapshot al scan).

    Si Payment tiene `listing_url`, usamos source=mercadolibre con la
    URL. Si no, usamos manual_listing con un placeholder mínimo — el
    pipeline correrá REPUVE pero no precio ni fotos.
    """
    plate = payment.plate or (preview.plate if preview else None)
    vin = payment.vin or (preview.vin if preview else None)

    if payment.listing_url:
        return AnalyzeRequest(
            url=payment.listing_url,  # type: ignore[arg-type]
            source=Source.MERCADOLIBRE,
            plate=plate,
            vin=vin,
        )
    return AnalyzeRequest(
        source=Source.MANUAL,
        plate=plate,
        vin=vin,
        manual_listing=ManualListing(
            title="(escaneado por placa, sin URL del anuncio)",
            price_mxn=0,
            year=0,
            make="",
            model="",
            kilometers=0,
            location="",
        ),
    )


def _hash_listing(
    listing_url: str | None, plate: str | None, vin: str | None
) -> str:
    """Hash determinista de los identificadores del listing para cache.

    Si dos payments piden el mismo listing_url + plate + vin, comparten
    cache. Si solo hay listing_url, cachean por URL.
    """
    parts = [
        listing_url or "",
        (plate or "").upper().replace("-", "").replace(" ", ""),
        (vin or "").upper().replace("-", "").replace(" ", ""),
    ]
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]
