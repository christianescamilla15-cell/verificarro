"""WebSocket live-audio captcha — usuario transcribe en tiempo real.

## Innovación 2026-05-10 (idea 2 pioneer)

Reframe del flow REPUVE: backend drive el browser hasta el reCAPTCHA,
si Google ofrece audio challenge, **el usuario lo resuelve en vivo**
escuchando 3 segundos y tipeando los dígitos. No 2Captcha externo,
no Whisper local — actividad humana genuina vía WebSocket.

## Por qué innovador

- **Sin extension publish** (vs Chrome extension), sin instalación
- **Sin captcha solver externo** (vs 2Captcha), sin costo por query
- **UX banking-like**: usuario participa 3s en captcha (no abre REPUVE)
- **Feedback humano genuino** → Google ve sesión legítima → debería pasar
- **Reusable**: misma infra pipe-able a otros sitios con reCAPTCHA

## Caveat empírico

Smokes 1-11 mostraron que REPUVE NO offers audio challenge UI en
invisible v2 con score bajo — auto-rechaza directamente. Para que
este flow se dispare, necesitamos sesión con score "medio" (no muy
bajo, no muy alto). Stack más promising:
  - Camoufox + main_world_eval
  - Profile con algunas cookies (no fresh, no logueado)
  - Mouse activity natural pre-submit

Si REPUVE igual rechaza directo (sin challenge), el flow degrada
limpio a `raw_status=captcha_required` y el frontend cae a upload
manual existente.

## WebSocket protocol

```
CLIENT → SERVER  {"type":"start","plate":"ABC123"}
SERVER → CLIENT  {"type":"status","msg":"navegando REPUVE..."}
SERVER → CLIENT  {"type":"status","msg":"captcha detectado, descargando audio..."}
SERVER → CLIENT  {"type":"audio","b64":"<base64 mp3>","duration_est":3}
CLIENT → SERVER  {"type":"answer","text":"1234"}
SERVER → CLIENT  {"type":"status","msg":"validando con REPUVE..."}
SERVER → CLIENT  {"type":"result","data":{queried:true,is_stolen:false,...}}
                 OR
SERVER → CLIENT  {"type":"error","msg":"..."}
```

Cierra después del result/error.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repuve", tags=["repuve-live"])


@router.websocket("/live")
async def repuve_live_ws(websocket: WebSocket) -> None:
    """WebSocket que orquesta el flow user-driven captcha.

    Auth: por ahora sin auth (mismo principio que /api/repuve/screenshot
    que ya está en producción sin JWT). Si el feature escala, agregar
    rate limit por IP via slowapi.

    Lifecycle: 1 WS = 1 query REPUVE. Después de result/error, cierra.
    """
    await websocket.accept()
    session_id = uuid.uuid4().hex[:8]
    logger.info("[live %s] WS connected", session_id)

    # State para el handshake answer del usuario
    answer_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1)

    async def audio_callback(mp3_bytes: bytes) -> None:
        """Envía el mp3 al cliente como base64."""
        b64 = base64.b64encode(mp3_bytes).decode()
        await websocket.send_json({
            "type": "audio",
            "b64": b64,
            "size_bytes": len(mp3_bytes),
            # reCAPTCHA audio típico = 3-7 seg
            "duration_est": 5,
        })
        logger.info("[live %s] audio mp3 sent (%d bytes)", session_id, len(mp3_bytes))

    async def answer_provider(timeout_sec: float) -> str | None:
        """Espera la respuesta del cliente con timeout."""
        try:
            return await asyncio.wait_for(answer_queue.get(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            return None

    try:
        # Esperar mensaje "start" con la placa
        init = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        if init.get("type") != "start":
            await websocket.send_json({"type": "error", "msg": "Expected start message"})
            return

        plate = (init.get("plate") or "").strip().upper()
        vin = (init.get("vin") or "").strip().upper()
        if not plate and not vin:
            await websocket.send_json({"type": "error", "msg": "Sin placa ni NIV"})
            return

        logger.info("[live %s] start plate=%s vin=%s", session_id, plate, vin)

        # Arrancar tarea de scraping en background — paralelamente
        # escuchamos por mensajes "answer" del cliente.
        async def listener_task() -> None:
            """Loop que recibe mensajes del cliente (answer)."""
            try:
                while True:
                    msg = await websocket.receive_json()
                    if msg.get("type") == "answer":
                        text = (msg.get("text") or "").strip()
                        await answer_queue.put(text or None)
                    elif msg.get("type") == "cancel":
                        await answer_queue.put(None)
                        return
            except WebSocketDisconnect:
                # Si el cliente se desconecta, marcamos answer como None
                # para que el solver no quede colgado en wait
                try:
                    answer_queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass

        listener = asyncio.create_task(listener_task())

        try:
            # Driver scraping — usamos el orquestador existente pero
            # con flag user-driven en lugar de Whisper/2Captcha.
            await websocket.send_json({"type": "status", "msg": "Iniciando navegación REPUVE..."})
            result = await _run_user_driven_query(
                plate=plate or None,
                vin=vin or None,
                audio_callback=audio_callback,
                answer_provider=answer_provider,
                status_callback=lambda m: websocket.send_json({"type": "status", "msg": m}),
            )

            await websocket.send_json({
                "type": "result",
                "data": result.model_dump(mode="json"),
            })
            logger.info(
                "[live %s] DONE queried=%s raw_status=%s",
                session_id, result.queried, result.raw_status,
            )
        finally:
            listener.cancel()
            try:
                await listener
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    except asyncio.TimeoutError:
        await _safe_send_json(websocket, {"type": "error", "msg": "Timeout en init"})
    except WebSocketDisconnect:
        logger.info("[live %s] client disconnected", session_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[live %s] error inesperado", session_id)
        await _safe_send_json(websocket, {"type": "error", "msg": f"Error: {exc}"})
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


async def _safe_send_json(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_json(payload)
    except Exception:  # noqa: BLE001
        pass


async def _run_user_driven_query(
    *,
    plate: str | None,
    vin: str | None,
    audio_callback,
    answer_provider,
    status_callback,
):
    """Bridge entre el WS endpoint y el scraper Camoufox + user-driven solver.

    Encapsulado en función separada para que el test pueda mockear las
    callbacks y validar el protocolo sin tocar Playwright real.

    Reusa Camoufox como engine porque es el más cercano a "real Chrome"
    sin requerir CDP attachment del browser real del usuario. Si tu
    profile/cookies eventualmente generan score "medio", Camoufox
    debería ver el challenge UI.
    """
    from app.models.report import RepuveResult
    from app.scrapers import repuve
    from app.services.audio_captcha_solver import solve_with_user_input

    # Override del flow estándar — armamos un mini-driver inline que
    # llega hasta submit y delega el captcha al user-driven solver.
    # Reusar _run_query monolítico sería más complejo (haría 2Captcha
    # automático antes de llegar al audio user).

    # Por ahora delegamos a una versión SIMPLIFICADA del scraper.
    # Si el smoke real con un usuario muestra que necesitamos el flow
    # completo (mouse humanization, cookie warmup, etc.), portamos.
    plate_n = repuve._normalize_plate(plate) if plate else None
    vin_n = repuve._normalize_vin(vin) if vin else None

    if plate_n and not repuve._is_valid_plate(plate_n):
        return RepuveResult(queried=False, plate=plate, error="Placa inválida")
    if vin_n and not repuve._is_valid_vin(vin_n):
        return RepuveResult(queried=False, vin=vin, error="NIV inválido")

    await status_callback("Lanzando navegador anti-detect...")

    import os
    from pathlib import Path
    from app.config import get_settings
    from app.scrapers.stealth import apply_stealth

    settings = get_settings()
    profile_dir = settings.playwright_profile_dir
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    # Engine selection: Camoufox preferido (mejor stealth + más probable
    # que Google muestre challenge UI), pero fallback a stock Playwright
    # si Camoufox no está instalado en el deploy target (Render no
    # ejecuta `python -m camoufox fetch` durante build por defecto —
    # el Firefox custom de 530MB excede limites de build cache).
    #
    # Para el LIVE audio path, stock Playwright funciona porque NO
    # estamos inyectando 2Captcha tokens en el main world — solo
    # esperando que Google muestre challenge iframe y lo driveamos.
    use_camoufox = False
    try:
        from camoufox.async_api import AsyncCamoufox
        use_camoufox = True
    except ImportError:
        logger.info("Camoufox no disponible — usando stock Playwright")

    # Context manager unificado
    import contextlib

    @contextlib.asynccontextmanager
    async def _open_browser():
        if use_camoufox:
            cf_kwargs = {
                "persistent_context": True,
                "user_data_dir": profile_dir,
                "headless": settings.playwright_headless,
                "locale": "es-MX",
                "geoip": True,
                "humanize": True,
                "os": ["windows"],
                "main_world_eval": True,
            }
            try:
                async with AsyncCamoufox(**cf_kwargs) as ctx:
                    yield ctx, True
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Camoufox launch failed (%s) — fallback a stock Playwright", exc,
                )

        # Stock Playwright path (fallback OR primary si no hay camoufox)
        from playwright.async_api import async_playwright
        launch_args = [
            "--ignore-certificate-errors",
            "--disable-blink-features=AutomationControlled",
        ]
        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=settings.playwright_headless,
                args=launch_args,
                locale="es-MX",
                ignore_https_errors=True,
                timezone_id="America/Mexico_City",
            )
            try:
                yield ctx, False
            finally:
                await ctx.close()

    async with _open_browser() as (context, is_camoufox):
        page = await context.new_page()
        # Stock Playwright: aplicar stealth manualmente. Camoufox lo hace
        # a nivel C++ nativo, no necesita nuestro init script.
        if not is_camoufox:
            await apply_stealth(page)

        await page.goto(
            repuve.REPUVE_URL,
            wait_until="networkidle",
            timeout=settings.scrape_timeout_ms,
        )

        await status_callback("Llenando formulario REPUVE...")
        await page.wait_for_selector(
            repuve._SELECTORS["plate_input"], timeout=10_000,
        )

        import random
        if plate_n:
            sel = repuve._SELECTORS["plate_input"]
            await page.locator(sel).click()
            await page.wait_for_timeout(random.randint(150, 350))
            try:
                await page.locator(sel).press_sequentially(plate_n, delay=random.randint(60, 130))
            except AttributeError:
                await page.type(sel, plate_n, delay=random.randint(60, 130))
        else:
            sel = repuve._SELECTORS["vin_input"]
            await page.locator(sel).click()
            await page.wait_for_timeout(random.randint(150, 350))
            try:
                await page.locator(sel).press_sequentially(vin_n or "", delay=random.randint(60, 130))
            except AttributeError:
                await page.type(sel, vin_n or "", delay=random.randint(60, 130))

        await page.wait_for_timeout(random.randint(400, 900))
        await status_callback("Enviando consulta...")
        await repuve._click_submit(page, sel)

        # User-driven captcha (la innovación)
        await status_callback("Esperando captcha challenge de REPUVE...")
        captcha_resolved = await solve_with_user_input(
            page,
            audio_callback=audio_callback,
            answer_provider=answer_provider,
            challenge_timeout_sec=10.0,
            answer_timeout_sec=60.0,
        )

        await page.wait_for_timeout(3_000)

        if await repuve._has_recaptcha_error(page):
            return RepuveResult(
                queried=False, plate=plate, vin=vin,
                raw_status="captcha_required",
                error=(
                    "REPUVE rechazó el captcha. Esto pasa cuando REPUVE no "
                    "ofreció challenge UI (auto-rechazo). Intenta el flow "
                    "manual de subida de captura."
                ),
            )

        await status_callback("Leyendo resultado...")
        modal_html = await repuve._read_response_modal(page)
        return repuve.parse_response(
            modal_html, plate=plate, vin=vin, captcha_used=captcha_resolved,
        )
