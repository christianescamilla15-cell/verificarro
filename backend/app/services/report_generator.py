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

from app.analyzers import scoring
from app.db.models import Payment, PaymentStatus, ReportRecord, ReportStatus
from app.db.session import get_session_factory
from app.models.report import AnalyzeRequest, ManualListing, PhotoFinding, Source
from app.services import photo_dedup
from app.services.email import send_report_email
from app.services.pdf_report import generate_pdf
from app.services.photo_fetcher import fetch_photos
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

            # Photo dedup: post-procesa fotos con pHash para detectar
            # fotos recicladas en otros listings de nuestra base histórica.
            await _apply_photo_dedup(session, preview.listing_hash, report)

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

            # Manda email con PDF adjunto si tenemos payer_email.
            # Failure tolerant: si SMTP falla, NO bloqueamos el unlock —
            # el reporte ya está disponible en la web.
            if payment.payer_email:
                await _send_report_email_safe(
                    payment=payment, preview=preview, report=report,
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


async def _send_report_email_safe(
    payment: Payment, preview: ReportRecord, report
) -> None:
    """Genera el PDF y manda el email al payer_email. Failure tolerant.

    Si el PDF gen o el SMTP falla, loguea y sigue — el unlock ya quedó
    persistido en DB y el usuario puede ver el reporte en la web.
    El email es bonus, no requirement.
    """
    try:
        pdf_bytes = generate_pdf(report)
    except Exception:  # noqa: BLE001
        logger.exception("Falló generar PDF para email post-unlock")
        return

    title_hint = (
        report.listing.title or
        f"{report.listing.make} {report.listing.model}".strip() or
        "tu reporte"
    )

    # URL pública del reporte. En producción el frontend está en
    # `verificarro.mx` o `verificarro.vercel.app`. Construimos best-effort
    # con `MAGIC_LINK_BASE_URL` como pivot (apunta al frontend root).
    from app.config import get_settings
    settings = get_settings()
    base = settings.magic_link_base_url.rsplit("/auth/", 1)[0]
    report_url = f"{base}/checkout/success?external_reference={payment.mp_external_reference}"

    try:
        await send_report_email(
            payment.payer_email or "",
            pdf_bytes,
            title_hint=title_hint,
            score=report.score,
            risk_level=report.risk_level.value,
            report_id=preview.id,
            report_url=report_url,
        )
    except Exception:  # noqa: BLE001
        logger.exception("send_report_email falló (no-bloqueante)")


async def _apply_photo_dedup(
    session, listing_hash: str, report
) -> None:
    """Hashea las fotos del listing, busca matches en `photo_hashes` con
    listing_hash distinto, agrega `PhotoFinding` por cada match
    detectado (foto reciclada = high severity), almacena los hashes
    nuevos y reescribe el scoring.

    No-op si el listing no tiene fotos. Failure tolerant: si pHash o
    DB falla, loguea y sigue sin tumbar el unlock.
    """
    photo_urls = report.listing.photo_urls if report.listing else []
    if not photo_urls:
        return

    try:
        bytes_list = await fetch_photos(photo_urls[:6])
    except Exception:  # noqa: BLE001
        logger.exception("Photo dedup: falló descarga de fotos")
        return

    hashes = [photo_dedup.compute_phash(b) for b in bytes_list]

    # Buscar matches en histórico
    try:
        matches = await photo_dedup.find_recycled_photos(
            session, hashes, listing_hash
        )
    except Exception:  # noqa: BLE001
        logger.exception("Photo dedup: query DB falló")
        matches = []

    # Convertir matches en PhotoFinding HIGH
    for idx, info in matches:
        report.photo_findings.append(PhotoFinding(
            photo_index=idx,
            issue="watermark_or_stock",
            severity="high",
            note=(
                f"Foto reciclada: misma imagen apareció en otro listing "
                f"(hash dist {info['hamming']}/64). Posible foto stock "
                "o anuncio fraudulento reusando fotos."
            ),
        ))
    if matches:
        # Re-correr scoring para integrar los nuevos findings
        scoring.populate(report)
        logger.warning(
            "Photo dedup: %d fotos recicladas detectadas", len(matches)
        )

    # Almacenar nuevos hashes para próximos reports
    try:
        hash_pairs = list(zip(
            hashes,
            photo_urls[:6] + [None] * max(0, 6 - len(photo_urls)),
        ))
        await photo_dedup.store_photo_hashes(
            session, listing_hash, hash_pairs
        )
    except Exception:  # noqa: BLE001
        logger.exception("Photo dedup: store hashes falló")


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
    invoice_number = payment.invoice_number

    # invoice_extra está en el preview report_json si el smart scanner
    # detectó factura previamente — recuperamos para cross-validation.
    invoice_extra = None
    if preview and preview.report_json:
        existing_invoice = preview.report_json.get("invoice")
        if isinstance(existing_invoice, dict):
            # Reconstruir extra dict desde campos guardados
            inv_extra = {}
            for key in ("rfc_emisor", "rfc_receptor", "marca", "modelo", "año", "niv"):
                v = existing_invoice.get(key)
                if v:
                    inv_extra[key] = v
            if inv_extra:
                invoice_extra = inv_extra

    if payment.listing_url:
        return AnalyzeRequest(
            url=payment.listing_url,  # type: ignore[arg-type]
            source=Source.MERCADOLIBRE,
            plate=plate,
            vin=vin,
            invoice_number=invoice_number,
            invoice_extra=invoice_extra,
        )
    return AnalyzeRequest(
        source=Source.MANUAL,
        plate=plate,
        vin=vin,
        invoice_number=invoice_number,
        invoice_extra=invoice_extra,
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


# ---------------------------------------------------------------------------
# MOD-012: Recovery de tareas perdidas por restart de Render

# Window post-paid_at en el que consideramos un Payment como
# "potencialmente con tarea perdida". Si Christian intentó pagar hace
# 7 días y el server estaba caído, no queremos re-encolar 7 días después
# (el listing puede haber expirado, los precios cambiaron, etc.). 30 min
# es ventana razonable: el unlock pipeline debe completar en <60s normal,
# 30 min cubre cualquier restart razonable de Render.
ORPHAN_RECOVERY_WINDOW_MIN = 30


async def recover_orphan_paid_payments() -> list[str]:
    """Detecta Payments PAID sin ReportRecord linked y re-encola sus
    pipelines. Llamado por el lifespan startup hook después de un boot
    de Render para recuperar tareas perdidas durante un restart.

    Solo procesa Payments en `ORPHAN_RECOVERY_WINDOW_MIN` minutos
    recientes — más viejos se asumen abandonados/manualmente arreglados.

    Devuelve lista de payment_ids re-encolados (útil para logging y test).
    Idempotente: una segunda llamada NO re-encola, porque para entonces
    los pipelines pendientes ya completaron y el filtro `payment_id NOT IN
    (reports.payment_id)` los excluye.
    """
    import asyncio
    factory = get_session_factory()
    async with factory() as session:
        cutoff = datetime.now(UTC) - timedelta(minutes=ORPHAN_RECOVERY_WINDOW_MIN)
        # Subquery: payment_ids que ya tienen ReportRecord
        from sqlalchemy import not_
        already_reported = select(ReportRecord.payment_id).where(
            ReportRecord.payment_id.is_not(None)
        )
        # Payments PAID recientes sin report linked
        result = await session.execute(
            select(Payment).where(
                Payment.status == PaymentStatus.PAID,
                Payment.paid_at >= cutoff,
                not_(Payment.id.in_(already_reported)),
            )
        )
        orphans = list(result.scalars().all())

    if not orphans:
        return []

    requeued: list[str] = []
    for payment in orphans:
        # Si el Payment fue tier search/dealer (preapproval), NO tiene
        # pipeline asociado — el "report" es la activación del plan,
        # no un análisis. Skip.
        if payment.tier in {"search", "dealer"}:
            continue
        # Decidimos qué task encolar buscando si hay preview ya creado
        # (scan-first) o no (legacy URL-first).
        async with factory() as s2:
            preview_q = await s2.execute(
                select(ReportRecord).where(
                    ReportRecord.payment_id == payment.id,
                    ReportRecord.status == ReportStatus.PREVIEW,
                )
            )
            has_preview = preview_q.scalar_one_or_none() is not None
        task_fn = unlock_report_for_payment if has_preview else generate_report_for_payment
        # Encolamos en el event loop sin bloquear el startup. Cada
        # tarea ya es idempotente (re-checkea su estado al iniciar).
        asyncio.create_task(task_fn(payment.id))
        requeued.append(payment.id)
        logger.warning(
            "[ORPHAN-RECOVERY] payment=%s tier=%s — re-encolando %s "
            "tras posible restart (paid_at=%s)",
            payment.id, payment.tier, task_fn.__name__, payment.paid_at,
        )

    if requeued:
        logger.info(
            "[ORPHAN-RECOVERY] %d payments re-encolados", len(requeued),
        )
    return requeued
