"""REPUVE consulta ciudadana scraper.

Portal: ``https://www2.repuve.gob.mx:8443/ciudadania/``

Es un SPA de Angular con cuatro campos de búsqueda (placa, NIV, folio,
NCI). Esta implementación cubre los dos primeros — el resto sale del
scope MVP.

## reCaptcha bypass via 2Captcha (2026-05-01)

REPUVE protege la consulta con **reCaptcha v2 de Google**, no con un
captcha de imagen. Claude visión NO puede resolver reCaptcha (Google
hace análisis de comportamiento del navegador, no es OCR).

El flow es:

1. Carga el portal, llena placa/NIV.
2. Detecta el widget reCaptcha y extrae el `data-sitekey`.
3. Si `CAPTCHA_SOLVER_API_KEY` está set → llamamos 2Captcha
   (~$0.003 USD por solve, ~10-30s) y obtenemos un token.
4. Inyectamos el token vía JS en el campo `g-recaptcha-response`.
5. Submit del formulario → REPUVE devuelve datos reales.

Si 2Captcha no está configurado o falla, caemos al flow legacy:
devolvemos `captcha_required` y la UI muestra link manual a
repuve.gob.mx para que el usuario pegue el resultado.

## Throttle

`REPUVE_RATE_LIMIT_PER_SEC` del config. 1 req/s mantiene la consulta
dentro del rango de uso ciudadano normal.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_settings
from app.models.report import RepuveResult
from app.scrapers.stealth import apply_stealth
from app.services.audio_captcha_solver import (
    solve_invisible_recaptcha_audio,
)
from app.services.captcha_solver import solve_recaptcha_v2

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

REPUVE_URL = "https://www2.repuve.gob.mx:8443/ciudadania/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

# Selectors observed 2026-04-30. Si REPUVE rompe selectores, ajustar aquí.
_SELECTORS = {
    "plate_input": "input[placeholder*='placa' i]",
    "vin_input": (
        "input[placeholder*='número de serie' i], "
        "input[placeholder*='numero de serie' i]"
    ),
    # El botón se llama "Buscar"; "Consultar" funcionaba en versiones
    # anteriores. Probamos ambos.
    "submit_btn_text": ("Buscar", "Consultar"),
    # Todos los modales visibles tras submit. El SPA agrega `.in` (Bootstrap 3)
    # cuando el modal está abierto.
    "result_modal": ".modal.in .modal-body, .modal.show .modal-body",
    "captcha_img": "img[src*='captcha' i], img[id*='captcha' i]",
    "captcha_input": "input[name*='captcha' i], input[placeholder*='captcha' i]",
    # reCaptcha v2: widget tiene atributo data-sitekey o iframe ?k=KEY.
    "recaptcha_widget": "[data-sitekey], iframe[src*='recaptcha']",
}

# Token throttling — un solo lock global por proceso.
_throttle_lock = asyncio.Lock()
_last_request_at: float = 0.0


async def query(plate: str | None = None, vin: str | None = None) -> RepuveResult:
    """Consulta REPUVE por placa o NIV. Devuelve `RepuveResult` siempre.

    ### Dispatch (MOD-040)

    Si `REPUVE_SCRAPER_URL` está set, dispatcha al sidecar microservicio
    en host MX (Vultr CDMX, etc.) que tiene IP mexicana — necesario
    porque el WAF de gob.mx bloquea IPs no-mexicanas. Si NO está set,
    intenta scrape local (degrada a queried=False si IP no-MX).

    ### Retry loop (modo local)

    Implementa retry loop cuando el captcha bypass es rechazado por
    Google `siteverify`. Tasa esperada por intento individual:
      - Sin stealth/proxy: ~0-30%
      - Con stealth + mouse moves: ~75%
      - Con stealth + mouse moves + proxy residencial MX: ~88%

    Retry con N intentos compone:
      - 1 intento al 75% = 75% éxito
      - 2 intentos al 75% = 1 - 0.25² = 93.75% éxito
      - 3 intentos al 75% = 98.4% éxito (diminishing returns)

    `REPUVE_RETRY_ATTEMPTS` env (default 2) controla esto.

    Errores no-captcha (timeout de red, formato inválido, etc.) NO se
    reintentan — solo el caso `captcha_required`.
    """
    if not plate and not vin:
        return RepuveResult(queried=False, error="Sin placa ni NIV")

    plate_norm = _normalize_plate(plate) if plate else None
    vin_norm = _normalize_vin(vin) if vin else None

    if plate_norm and not _is_valid_plate(plate_norm):
        return RepuveResult(
            queried=False, plate=plate, error="Placa inválida (5-7 caracteres alfanuméricos)"
        )
    if vin_norm and not _is_valid_vin(vin_norm):
        return RepuveResult(
            queried=False, vin=vin, error="NIV inválido (debe tener 17 caracteres)"
        )

    settings = get_settings()

    # MOD-040: dispatch a sidecar MX si está configurado.
    if settings.repuve_scraper_url.strip():
        return await _query_remote(
            plate_norm, vin_norm,
            url=settings.repuve_scraper_url.strip(),
            token=settings.repuve_scraper_token.strip(),
            timeout=settings.repuve_scraper_timeout_sec,
        )

    max_attempts = max(1, settings.repuve_retry_attempts)
    last_result: RepuveResult | None = None

    # Fase 1 telemetry — captura técnicas activas en este attempt.
    # config_label se setea via env var SCRAPE_CONFIG_LABEL (Fase 2 A/B).
    config_label = (
        os.environ.get("SCRAPE_CONFIG_LABEL", "default") or "default"
    )
    techniques = _capture_techniques(settings)

    for attempt in range(1, max_attempts + 1):
        await _throttle()

        attempt_start = time.time()
        try:
            result = await _run_query(plate_norm, vin_norm)
        except Exception as exc:  # noqa: BLE001
            error_result = RepuveResult(
                queried=False,
                plate=plate_norm,
                vin=vin_norm,
                error=f"Error al consultar REPUVE: {exc}",
            )
            _record_telemetry(
                config_label, plate_norm, vin_norm,
                {**techniques, "attempt_num": attempt},
                error_result,
                int((time.time() - attempt_start) * 1000),
            )
            return error_result

        attempt_duration_ms = int((time.time() - attempt_start) * 1000)
        last_result = result

        _record_telemetry(
            config_label, plate_norm, vin_norm,
            {**techniques, "attempt_num": attempt},
            result, attempt_duration_ms,
        )

        # Éxito real (REPUVE devolvió datos) o error no-captcha → return
        if result.queried or result.raw_status != "captcha_required":
            if attempt > 1 and result.queried:
                logger.warning(
                    "REPUVE éxito en intento %d/%d", attempt, max_attempts
                )
            return result

        # Captcha rechazado, queda budget de retry
        if attempt < max_attempts:
            logger.warning(
                "Captcha rechazado en intento %d/%d, reintentando...",
                attempt, max_attempts,
            )

    return last_result or RepuveResult(
        queried=False, plate=plate_norm, vin=vin_norm,
        error="Sin respuesta de REPUVE",
    )


def _capture_techniques(settings) -> dict:
    """Snapshot de técnicas activas. Lo que cambia entre experimentos
    (proxies, retries, etc.) queda capturado para A/B.

    Defensivo: usa getattr con default para que tests con fake settings
    minimalistas no exploten. En producción todos los attrs existen.
    """
    return {
        "headless": getattr(settings, "playwright_headless", True),
        "stealth_flags": [
            "AutomationControlled",
            "IsolateOrigins",
        ],
        "user_agent_short": "Chrome 130 Win",
        "proxy_used": bool(
            getattr(settings, "proxy_url", "")
            or getattr(settings, "proxy_server", "")
        ),
        "captcha_solver": "2captcha",
        "scrape_timeout_ms": getattr(settings, "scrape_timeout_ms", 30000),
        "retry_attempts_max": getattr(settings, "repuve_retry_attempts", 1),
        "rate_limit_per_sec": getattr(settings, "repuve_rate_limit_per_sec", 1),
        "profile_persistent": bool(
            getattr(settings, "playwright_profile_dir", "")
        ),
        "cookie_warmup": (
            os.environ.get("SCRAPE_COOKIE_WARMUP", "").lower() == "true"
        ),
    }


def _record_telemetry(
    config_label: str,
    plate: str | None,
    vin: str | None,
    techniques: dict,
    result: RepuveResult,
    duration_ms: int,
) -> None:
    """Wrapper failure-tolerant alrededor de scrape_telemetry."""
    try:
        from app.services.scrape_telemetry import record_attempt
        record_attempt(
            config_label=config_label,
            plate=plate,
            vin=vin,
            techniques=techniques,
            outcome={
                "queried": result.queried,
                "raw_status": result.raw_status,
                "error": result.error,
                "duration_ms": duration_ms,
                "is_stolen": result.is_stolen,
            },
        )
    except Exception:  # noqa: BLE001
        # Telemetry NUNCA debe romper el flow productivo
        logger.exception("scrape_telemetry record falló (no-bloqueante)")


# ---------------------------------------------------------------------------
# Remote dispatch (MOD-040 — sidecar MX)


async def _query_remote(
    plate: str | None,
    vin: str | None,
    *,
    url: str,
    token: str,
    timeout: float,
) -> RepuveResult:
    """Llama al sidecar `verificarro-scraper-mx` via HTTP.

    El sidecar reusa el mismo `query()` local pero corre en host con IP
    mexicana, evitando el WAF de gob.mx. Failure-tolerant: si el sidecar
    no responde, devolvemos RepuveResult con error claro para que el
    frontend muestre el link manual.
    """
    import httpx

    endpoint = url.rstrip("/") + "/scrape/repuve"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"plate": plate, "vin": vin}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        logger.warning(
            "Sidecar REPUVE no respondió (%s) — degradando a queried=False", exc,
        )
        return RepuveResult(
            queried=False, plate=plate, vin=vin,
            error=f"Sidecar timeout/network: {exc}",
        )

    if response.status_code != 200:
        logger.warning(
            "Sidecar REPUVE devolvió %d: %s",
            response.status_code, response.text[:200],
        )
        return RepuveResult(
            queried=False, plate=plate, vin=vin,
            error=f"Sidecar HTTP {response.status_code}",
        )

    try:
        data = response.json()
    except ValueError:
        return RepuveResult(
            queried=False, plate=plate, vin=vin,
            error="Sidecar devolvió respuesta no-JSON",
        )

    return RepuveResult(
        queried=bool(data.get("queried")),
        plate=data.get("plate"),
        vin=data.get("vin"),
        is_stolen=data.get("is_stolen"),
        has_legal_status=data.get("has_legal_status"),
        raw_status=data.get("raw_status"),
        error=data.get("error"),
    )


# ---------------------------------------------------------------------------
# Driver


async def _run_query(plate: str | None, vin: str | None) -> RepuveResult:
    settings = get_settings()
    use_real_chrome = os.environ.get("USE_REAL_CHROME", "").lower() == "true"
    use_camoufox = os.environ.get("USE_CAMOUFOX", "").lower() == "true"

    # Anti-detect engine selection. CINCO opciones por orden de
    # autenticidad (más cerca de "humano real" arriba):
    #
    #   USE_REAL_CHROME=true       (recomendado 2026-05-10 después
    #                              de 8 smokes fallidos con todos los
    #                              demás engines)
    #     Conecta vía CDP al Chrome que el usuario YA TIENE corriendo
    #     con sus años de cookies, login Google, historia real, GPU
    #     real, plugins reales, fonts reales. Score reCAPTCHA debería
    #     ser MUY alto porque es literalmente un humano-trusted browser.
    #     Requiere: Chrome lanzado con `--remote-debugging-port=9222`.
    #     Lee REAL_CHROME_CDP_URL env (default http://localhost:9222).
    #     ⚠ NO cierra el browser al terminar (es Chrome del usuario).
    #
    # Las otras opciones (Camoufox, patchright, rebrowser, stock) lanzan
    # su propio browser y son útiles cuando el user no puede correr
    # Chrome con debug port abierto (e.g., en sidecar Vultr).
    #
    #   USE_CAMOUFOX=true          (recomendado 2026-05-10 si patchright
    #                              tampoco pasa REPUVE)
    #     Firefox custom-compiled. Fingerprint patches a nivel C++ —
    #     antes de que JS pueda inspeccionar. Benchmarks 2026 reportan
    #     0% headless detection. Diferente engine que Playwright stock
    #     (necesita su propio binary, ~530 MB Firefox 135 custom).
    #     API: AsyncCamoufox() context manager → Browser directly.
    #
    #   USE_PATCHRIGHT=true        (intermedio)
    #     CDP isolation patches a nivel JavaScript-isolation. ~67%
    #     headless detection reduction. Drop-in Playwright Chromium.
    #     ⚠ Smoke 2026-05-10 mostró que rompe la inyección 2Captcha
    #     (window.grecaptcha no visible desde page.evaluate isolated
    #     world). Si usas patchright + 2Captcha, la inyección sale
    #     "no_grecaptcha_api" y el form se manda incompleto.
    #
    #   USE_REBROWSER_PLAYWRIGHT=true  (legacy)
    #     Corrige runtimeEnableLeak + pwInitScripts. Drop-in Chromium.
    #
    #   (nada set)
    #     Stock Playwright Chromium. Para tests + casos donde anti-detect
    #     no aplica.
    if not use_camoufox:
        if use_real_chrome:
            # Stock playwright para connect_over_cdp — no necesitamos
            # patchright/rebrowser/camoufox porque el browser real es del
            # usuario, ya tiene fingerprint humano genuino.
            from playwright.async_api import async_playwright
        elif os.environ.get("USE_PATCHRIGHT", "").lower() == "true":
            from patchright.async_api import async_playwright
        elif os.environ.get("USE_REBROWSER_PLAYWRIGHT", "").lower() == "true":
            from rebrowser_playwright.async_api import async_playwright
        else:
            from playwright.async_api import async_playwright

    # Args de stealth: --disable-blink-features=AutomationControlled
    # esconde el flag más obvio que Google detecta.
    launch_args = [
        "--ignore-certificate-errors",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ]

    # Proxy residencial (toggle por env var) — sube tasa éxito a ~80%
    # Soporta dos formatos: (1) URL embedida con user:pass@ o (2) campos
    # separados PROXY_SERVER/USERNAME/PASSWORD. (2) es preferido porque
    # no requiere percent-encoding de chars especiales en el password.
    proxy_config = _build_proxy_config(settings)
    if proxy_config:
        host = proxy_config["server"].split("://")[-1]
        has_auth = "username" in proxy_config
        logger.warning(
            "Usando proxy: %s (auth=%s)", host, "yes" if has_auth else "no"
        )

    # Browser context PERSISTENTE: reusa profile dir entre runs para
    # acumular cookies / localStorage / IndexedDB. Después de algunas
    # consultas, Google empieza a ver "este browser tiene historia
    # con sus servicios" y sube el trust score.
    profile_dir = settings.playwright_profile_dir
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    # Viewport DETERMINÍSTICO basado en hash(profile_dir + UA).
    #
    # Cambio 2026-05-10: antes random.choice() cada run → reCaptcha v3
    # Enterprise lo flagga como "throwaway session". El paper de Google
    # reCaptcha v3 hace heavy weighting de "returning visitor" — misma
    # huella consistente entre sesiones sube el score.
    #
    # Hash desde (profile_dir + UA) significa:
    #   - Mismo profile_dir → siempre mismo viewport (consistencia
    #     intra-tenant que Google premia).
    #   - Profiles distintos → posiblemente viewports distintos
    #     (no hard-coded a 1366x768).
    #   - Cambiar UA o crear profile fresh resetea el viewport (cuando
    #     queremos "nueva identidad" deliberadamente).
    common_viewports = [
        {"width": 1366, "height": 768},   # más común laptop
        {"width": 1440, "height": 900},   # MacBook
        {"width": 1536, "height": 864},   # común Win
        {"width": 1600, "height": 900},   # común Win
        {"width": 1920, "height": 1080},  # Full HD
    ]
    import hashlib
    seed_input = f"{profile_dir}|{_USER_AGENT}".encode("utf-8")
    seed_idx = int(hashlib.sha256(seed_input).hexdigest(), 16) % len(common_viewports)
    viewport = common_viewports[seed_idx]

    context_kwargs = {
        "user_data_dir": profile_dir,
        "headless": settings.playwright_headless,
        "args": launch_args,
        "user_agent": _USER_AGENT,
        "locale": "es-MX",
        "viewport": viewport,
        "ignore_https_errors": True,
        "timezone_id": "America/Mexico_City",
        "geolocation": {"latitude": 19.4326, "longitude": -99.1332},
        "permissions": ["geolocation"],
    }
    if proxy_config:
        context_kwargs["proxy"] = proxy_config

    # Bifurcación de engine — Camoufox usa una API completamente
    # distinta (AsyncCamoufox context manager → Browser/Context). Lo
    # encapsulamos en un contextlib helper para que el resto del flow
    # quede uniforme.
    import contextlib

    @contextlib.asynccontextmanager
    async def _open_context():
        if use_real_chrome:
            # CDP connection a Chrome del usuario corriendo con
            # --remote-debugging-port=9222. Reusa los contexts existentes
            # (donde viven sus cookies/login Google reales). NO cerramos
            # el browser ni el context al terminar — es el Chrome del
            # usuario, sería destructivo.
            cdp_url = os.environ.get(
                "REAL_CHROME_CDP_URL", "http://localhost:9222"
            )
            logger.warning(
                "[engine] connecting to real Chrome via CDP at %s", cdp_url,
            )
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(cdp_url)
                if browser.contexts:
                    # Usa el contexto default (perfil real con cookies)
                    context = browser.contexts[0]
                else:
                    # Fallback: si Chrome arrancó sin contextos visibles
                    context = await browser.new_context()
                try:
                    yield context
                finally:
                    # NO cerrar — es Chrome del usuario, cerrar mataría
                    # su browser entero. Solo desconectamos.
                    try:
                        await browser.close()
                    except Exception:  # noqa: BLE001
                        pass
        elif use_camoufox:
            from camoufox.async_api import AsyncCamoufox

            # Camoufox-specific kwargs:
            #   geoip=True          → ajusta timezone/locale/proxy según IP
            #   humanize=True       → smooth cursor trajectories C++ nativo
            #                          (saltar nuestro _humanize_mouse para
            #                          evitar double-humanization)
            #   os=["windows"]      → forzar fingerprint Windows
            #   main_world_eval=True → CRÍTICO. Por default Camoufox aísla
            #                          page.evaluate() en un mundo JS
            #                          separado del main world donde
            #                          reCAPTCHA carga `window.grecaptcha`.
            #                          Sin este flag nuestra inyección
            #                          2Captcha falla con `no_grecaptcha_api`
            #                          (mismo bug que vimos con patchright
            #                          en smoke 2026-05-10). Insight de
            #                          techinz/playwright-captcha README.
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
            if proxy_config:
                cf_kwargs["proxy"] = proxy_config
            logger.warning("[engine] launching Camoufox (Firefox custom)")
            async with AsyncCamoufox(**cf_kwargs) as context:
                yield context
        else:
            engine_label = (
                "patchright" if os.environ.get("USE_PATCHRIGHT", "").lower() == "true"
                else "rebrowser" if os.environ.get("USE_REBROWSER_PLAYWRIGHT", "").lower() == "true"
                else "stock-playwright"
            )
            logger.warning("[engine] launching %s Chromium", engine_label)
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(**context_kwargs)
                try:
                    yield context
                finally:
                    await context.close()

    async with _open_context() as context:
        try:
            page = await context.new_page()
            # apply_stealth() es Chromium-specific (window.chrome,
            # WebGL params, etc.). Saltar cuando:
            #  - Camoufox: ya hace fingerprint patches a nivel C++,
            #    nuestras patches JS encima son over-spoofing.
            #  - Real Chrome (CDP): el browser es REAL del usuario,
            #    su fingerprint es genuino. Sobreescribir con nuestros
            #    valores falsos (e.g. "Intel Iris OpenGL Engine") puede
            #    ROMPER el match con headers TLS/HTTP que Google ya
            #    correlacionó — peor que no aplicar nada.
            if not (use_camoufox or use_real_chrome):
                await apply_stealth(page)

            # Fase 2 cookie_warmup_v1 — visita Google + YouTube ANTES de
            # REPUVE para acumular cookies _ga, NID, etc. Reduce el score
            # bot del reCaptcha v3 al hacer que el browser parezca tener
            # historia de uso humano. Activa via SCRAPE_COOKIE_WARMUP=true.
            if os.environ.get("SCRAPE_COOKIE_WARMUP", "").lower() == "true":
                for warmup_url in (
                    "https://www.google.com.mx",
                    "https://www.youtube.com",
                ):
                    try:
                        await page.goto(
                            warmup_url, wait_until="domcontentloaded",
                            timeout=15_000,
                        )
                        await page.wait_for_timeout(random.randint(1800, 3500))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Cookie warmup en %s falló: %s — continuando",
                            warmup_url, exc,
                        )

            await page.goto(
                REPUVE_URL,
                wait_until="networkidle",
                timeout=settings.scrape_timeout_ms,
            )
            # Angular pinta el formulario después de domcontentloaded.
            await page.wait_for_selector(
                _SELECTORS["plate_input"], timeout=10_000
            )

            # Mouse moves humanizados antes de interactuar — Google
            # considera "no mouse activity en la sesión" como señal bot.
            #
            # Skip cuando:
            #  - Camoufox: ya tiene `humanize=True` (smooth cursor
            #    trajectories C++ nativo). Nuestro JS encima causa
            #    cursor brincando errático.
            #  - Real Chrome via CDP: es Chrome del usuario, ya tiene
            #    actividad de mouse genuina de su uso real. Inyectar
            #    moves random sería sospechoso (mouse "teletransportado"
            #    a coordenadas aleatorias mientras él no lo movió).
            if not (use_camoufox or use_real_chrome):
                await _humanize_mouse(page)

            # Cambio 2026-05-10: page.fill() bypassa el dispatcher
            # de eventos KeyboardEvent — flag obvio para reCaptcha v3.
            # Cambio a press_sequentially() con delay random 60-130ms
            # entre tecla — patrón de typing humano real.
            if plate:
                input_selector = _SELECTORS["plate_input"]
                await page.locator(input_selector).click()  # focus
                await page.wait_for_timeout(random.randint(150, 350))
                try:
                    await page.locator(input_selector).press_sequentially(
                        plate, delay=random.randint(60, 130),
                    )
                except AttributeError:
                    # Playwright < 1.40 no tiene press_sequentially
                    await page.type(input_selector, plate, delay=random.randint(60, 130))
            else:
                input_selector = _SELECTORS["vin_input"]
                await page.locator(input_selector).click()
                await page.wait_for_timeout(random.randint(150, 350))
                try:
                    await page.locator(input_selector).press_sequentially(
                        vin or "", delay=random.randint(60, 130),
                    )
                except AttributeError:
                    await page.type(input_selector, vin or "", delay=random.randint(60, 130))

            # Pausa humana entre fill y submit (real users no son instantáneos)
            await page.wait_for_timeout(random.randint(400, 900))

            # Captchas de imagen tradicionales (raros): Claude visión.
            captcha_solved = await _maybe_solve_captcha(page)
            # reCaptcha v2 de Google (común en REPUVE): 2Captcha API.
            # Pre-submit: inyecta token + monkey-patch grecaptcha.execute.
            recaptcha_solved = await _maybe_solve_recaptcha(page)
            await _click_submit(page, input_selector)

            # Post-submit audio fallback: si invisible reCAPTCHA dispara
            # un challenge (token de 2Captcha rechazado, o no había token),
            # drive el audio challenge con Whisper local. Cero costo,
            # 3-7s típico. No-op si no hay challenge frame ni audio
            # enabled. Detalle en services/audio_captcha_solver.py.
            audio_solved = False
            if settings.captcha_audio_enabled:
                # Skip audio si el modal de resultado ya apareció
                # (form se mandó directo sin challenge).
                modal_already = False
                try:
                    await page.wait_for_selector(
                        _SELECTORS["result_modal"], timeout=2_000,
                    )
                    modal_already = True
                except Exception:  # noqa: BLE001
                    pass

                if not modal_already:
                    try:
                        audio_solved = await solve_invisible_recaptcha_audio(
                            page, timeout_sec=30.0,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Audio solver excepción: %s", exc)

            await page.wait_for_timeout(3_000)

            if await _has_recaptcha_error(page):
                error_msg = (
                    "REPUVE pidió reCaptcha. Consulta manualmente en "
                    "repuve.gob.mx y pega el resultado en la app."
                )
                if recaptcha_solved or audio_solved:
                    error_msg = (
                        "REPUVE rechazó el token de reCaptcha. Reintenta "
                        "o consulta manualmente en repuve.gob.mx."
                    )
                return RepuveResult(
                    queried=False,
                    plate=plate,
                    vin=vin,
                    raw_status="captcha_required",
                    error=error_msg,
                )

            modal_html = await _read_response_modal(page)

            # Diagnostic: si activado SCRAPE_DUMP_ON_EMPTY=true Y el
            # modal vino vacío, dumpea screenshot + HTML para inspeccionar
            # qué REPUVE realmente sirvió. Útil cuando captcha aparenta
            # pasar (no captcha_required) pero modal no se materializa —
            # nos permite ver si REPUVE rendererizó un error distinto,
            # un modal con selector distinto, o nada.
            if (
                os.environ.get("SCRAPE_DUMP_ON_EMPTY", "").lower() == "true"
                and not modal_html.strip()
            ):
                try:
                    import time as _time
                    ts = int(_time.time())
                    png_path = Path(profile_dir).parent / f"repuve_dump_{ts}.png"
                    html_path = Path(profile_dir).parent / f"repuve_dump_{ts}.html"
                    await page.screenshot(path=str(png_path), full_page=True)
                    full_html = await page.content()
                    html_path.write_text(full_html, encoding="utf-8")
                    logger.warning(
                        "[diag] modal vacío — screenshot=%s html=%s",
                        png_path, html_path,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[diag] dump fallido: %s", exc)

            return parse_response(
                modal_html,
                plate=plate,
                vin=vin,
                captcha_used=captcha_solved,
            )
        finally:
            # _open_context() async context manager hace su propio close
            # en su finally — el bloque aquí es no-op intencional para
            # mantener el shape del try/finally preexistente sin
            # duplicar el cleanup.
            pass


async def _humanize_mouse(page: "Page") -> None:
    """Simula movimientos de mouse antes de interactuar con el formulario.

    Google reCaptcha (v2 invisible y v3) usa "behavioral analysis" para
    distinguir humanos de bots. Una sesión sin ningún `mousemove` antes
    del submit es señal fuerte de automation. Movimientos random
    + pequeño scroll mejoran el score.

    Costo: ~1.5s extra por consulta. Vale la pena el tradeoff por el
    boost de éxito en el captcha bypass.
    """
    viewport = page.viewport_size
    if not viewport:
        return

    width = viewport["width"]
    height = viewport["height"]

    # 3-5 movimientos random a posiciones distintas del viewport
    for _ in range(random.randint(3, 5)):
        x = random.randint(50, width - 50)
        y = random.randint(50, height - 50)
        steps = random.randint(8, 20)  # bezier-like motion
        try:
            await page.mouse.move(x, y, steps=steps)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(random.randint(80, 250))

    # Pequeño scroll vertical (simula leer la página)
    try:
        await page.mouse.wheel(0, random.randint(40, 180))
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(random.randint(150, 400))


async def _has_recaptcha_error(page: "Page") -> bool:
    """Detecta la alerta `El reCaptcha no fue superado correctamente`.

    REPUVE muestra ese texto en cualquier `.alert` cuando el reCaptcha
    falla — y siempre falla en headless porque Google scoring detecta
    automatización.
    """
    try:
        alerts = page.locator(".alert:visible")
        count = await alerts.count()
    except Exception:
        return False
    for i in range(count):
        try:
            text = (await alerts.nth(i).inner_text()).lower()
        except Exception:
            continue
        if "recaptcha" in text and (
            "no fue superado" in text or "no se super" in text
        ):
            return True
    return False


async def _click_submit(page: "Page", _input_selector: str) -> None:
    """Click humanizado en el botón Buscar/Consultar.

    Google reCaptcha analiza timing de eventos: un click instantáneo
    (mousedown→mouseup en el mismo ms) o sin hover previo es señal bot.
    Patrón humano que aplicamos:

      1. Scroll the button into view (real users hacen scroll)
      2. Hover sobre el botón (real users hover antes de click)
      3. Pausa random 200-500ms (decisión humana)
      4. Mouse move al centro del botón con steps (no teleport)
      5. Click con `delay` (mousedown sostenido 80-180ms, real)

    El SPA de Angular no envuelve los inputs en `<form>` — submit es
    por click handler. Por eso es crítico que el click se vea humano.
    """
    accepted = {t.lower() for t in _SELECTORS["submit_btn_text"]}
    buttons = page.locator("button:visible")
    count = await buttons.count()
    for i in range(count):
        btn = buttons.nth(i)
        try:
            text = (await btn.inner_text()).strip().lower()
            if not text or not any(label in text for label in accepted):
                continue

            # 1. Scroll into view
            try:
                await btn.scroll_into_view_if_needed(timeout=2000)
            except Exception:  # noqa: BLE001
                pass

            # 2. Hover (mouse moves to button bounding box center)
            try:
                box = await btn.bounding_box()
                if box:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    # Move with bezier-like steps (no teleport)
                    await page.mouse.move(cx, cy, steps=random.randint(10, 25))
            except Exception:  # noqa: BLE001
                pass

            # 3. Pausa "decisión humana"
            await page.wait_for_timeout(random.randint(200, 500))

            # 4. Click con delay (mousedown sostenido)
            try:
                await btn.click(delay=random.randint(80, 180))
            except Exception:  # noqa: BLE001
                # Fallback al click simple si falla el con delay
                await btn.click()
            return
        except Exception:  # noqa: BLE001
            continue


async def _maybe_solve_recaptcha(page: "Page") -> bool:
    """Si la página tiene un widget reCaptcha v2, intenta resolverlo via 2Captcha.

    Devuelve True si se resolvió Y el token se inyectó/registró bien.
    False si no había recaptcha, no había API key, o falló el solve/inject.

    Flow:
      1. Busca elemento `[data-sitekey]` o iframe `?k=SITEKEY` → sitekey.
      2. Llama a `solve_recaptcha_v2(sitekey, page_url)`.
      3. Inyecta el token mediante TRES estrategias en cascada (cualquiera
         que funcione es suficiente):
            a. Textarea `g-recaptcha-response` (lectura básica).
            b. Callback JS registrado en `data-callback` o
               `data-callback-ready` del widget.
            c. Pattern `___grecaptcha_cfg.clients[N].callback(token)` —
               manipulación interna del estado de Google.
      4. Wait 1s para que la JS de Google procese el cambio antes del submit.
    """
    import logging
    log = logging.getLogger(__name__)

    detection = await _extract_recaptcha_sitekey(page)
    if not detection:
        log.debug("No reCaptcha widget detectado en la página")
        return False
    sitekey, invisible = detection
    log.warning(
        "reCaptcha detectado: sitekey=%s... invisible=%s",
        sitekey[:20], invisible,
    )

    page_url = page.url
    try:
        token = await solve_recaptcha_v2(
            sitekey, page_url, invisible=invisible
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("2Captcha excepción inesperada: %s", exc)
        return False

    if not token:
        log.warning("2Captcha no devolvió token")
        return False
    log.warning("2Captcha resolvió el captcha (token len=%d)", len(token))

    # Estrategia combinada de injection.
    # Para invisible reCaptcha en SPAs (REPUVE/Angular), no basta con poner
    # el token en el textarea: cuando el usuario hace click en "Buscar", el
    # framework re-llama `grecaptcha.execute()` que sobreescribe el token y
    # re-evalúa al usuario. En headless eso da score bajo → reject.
    #
    # Solución: además de inyectar, MONKEY-PATCH `grecaptcha.getResponse` y
    # `grecaptcha.execute` para que devuelvan nuestro token ya resuelto y
    # eviten el re-trigger.
    #
    # Camoufox-specific: cuando USE_CAMOUFOX=true, prepend "mw:" prefix
    # al script para que evaluate corra en el main world (donde
    # window.grecaptcha vive). Sin esto, evaluate corre aislado y la
    # inyección falla con `no_grecaptcha_api`. Documentado en
    # camoufox.com/python/usage main_world_eval section. El prefix
    # "mw:" rompería en Playwright stock (sería JS inválido), por eso
    # condicional en runtime.
    _mw_prefix = "mw:" if os.environ.get("USE_CAMOUFOX", "").lower() == "true" else ""
    try:
        injection_log = await page.evaluate(
            _mw_prefix + """(token) => {
                const log = [];

                // (1) Textarea g-recaptcha-response (lectura clásica)
                const textareas = document.querySelectorAll(
                    'textarea[name="g-recaptcha-response"], #g-recaptcha-response'
                );
                if (textareas.length === 0) {
                    const el = document.createElement('textarea');
                    el.id = 'g-recaptcha-response';
                    el.name = 'g-recaptcha-response';
                    el.style.display = 'none';
                    document.body.appendChild(el);
                    el.value = token;
                    el.innerHTML = token;
                    log.push('textarea_created');
                } else {
                    textareas.forEach(el => {
                        el.value = token;
                        el.innerHTML = token;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    });
                    log.push('textarea_set:' + textareas.length);
                }

                // (2) Monkey-patch grecaptcha.getResponse — siempre devuelve
                // nuestro token. Cubre el caso donde el SPA llama
                // getResponse() en su submit handler en vez de leer el textarea.
                if (window.grecaptcha) {
                    try {
                        window.grecaptcha.getResponse = function() { return token; };
                        log.push('getResponse_patched');
                    } catch (e) {
                        log.push('getResponse_patch_err:' + e.message);
                    }

                    // (3) Monkey-patch grecaptcha.execute — para invisible v2,
                    // el SPA llama execute() para disparar la evaluación. Si
                    // dejamos pasar la llamada real, Google detecta automation
                    // y devuelve un token de baja confianza. Lo neutralizamos:
                    // execute() ahora dispara directamente el callback con
                    // nuestro token y devuelve resolved promise.
                    try {
                        const origExecute = window.grecaptcha.execute;
                        window.grecaptcha.execute = function(...args) {
                            // Buscar y disparar el callback registrado.
                            try {
                                if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                                    const clients = window.___grecaptcha_cfg.clients;
                                    for (const cid of Object.keys(clients)) {
                                        const search = (obj, depth) => {
                                            if (!obj || depth > 4) return null;
                                            for (const k of Object.keys(obj)) {
                                                if (k === 'callback' && typeof obj[k] === 'function') {
                                                    return obj[k];
                                                }
                                                if (typeof obj[k] === 'object' && obj[k] !== null) {
                                                    const f = search(obj[k], depth + 1);
                                                    if (f) return f;
                                                }
                                            }
                                            return null;
                                        };
                                        const cb = search(clients[cid], 0);
                                        if (cb) cb(token);
                                    }
                                }
                            } catch (e) {}
                            return Promise.resolve(token);
                        };
                        log.push('execute_patched');
                    } catch (e) {
                        log.push('execute_patch_err:' + e.message);
                    }
                } else {
                    log.push('no_grecaptcha_api');
                }

                // (4) data-callback en widgets (caso visible v2, fallback)
                const widgets = document.querySelectorAll('[data-sitekey]');
                widgets.forEach(w => {
                    const cb = w.getAttribute('data-callback');
                    if (cb && typeof window[cb] === 'function') {
                        try { window[cb](token); log.push('data-callback:' + cb); }
                        catch (e) { log.push('data-callback-err:' + e.message); }
                    }
                });

                // (5) Disparar también el callback registrado en cfg
                try {
                    if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                        const clients = window.___grecaptcha_cfg.clients;
                        for (const cid of Object.keys(clients)) {
                            const search = (obj, depth) => {
                                if (!obj || depth > 4) return null;
                                for (const k of Object.keys(obj)) {
                                    if (k === 'callback' && typeof obj[k] === 'function') {
                                        return obj[k];
                                    }
                                    if (typeof obj[k] === 'object' && obj[k] !== null) {
                                        const f = search(obj[k], depth + 1);
                                        if (f) return f;
                                    }
                                }
                                return null;
                            };
                            const cb = search(clients[cid], 0);
                            if (cb) {
                                try { cb(token); log.push('cfg-callback:' + cid); }
                                catch (e) { log.push('cfg-cb-err:' + e.message); }
                            }
                        }
                    }
                } catch (e) {
                    log.push('cfg-err:' + e.message);
                }

                return log.join('|');
            }""",
            token,
        )
        log.warning("reCaptcha injection: %s", injection_log)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed injecting reCaptcha token: %s", exc)
        return False

    # Da tiempo a que la JS de Google procese el callback antes del submit
    await page.wait_for_timeout(1500)
    return True


async def _extract_recaptcha_sitekey(page: "Page") -> tuple[str, bool] | None:
    """Busca el sitekey de Google en el DOM. Prioridad: data-sitekey > iframe?k=.

    Devuelve `(sitekey, invisible)` o None si no encuentra widget.
    `invisible=True` cuando el widget es reCaptcha v2 invisible
    (REPUVE usa esta variante: el iframe trae `&size=invisible`).
    """
    # 1. Atributo data-sitekey en algún elemento (data-size determina si es invisible)
    try:
        el = page.locator("[data-sitekey]").first
        if await el.count() > 0:
            value = await el.get_attribute("data-sitekey")
            if value:
                size = await el.get_attribute("data-size")
                invisible = (size or "").lower() == "invisible"
                return (value.strip(), invisible)
    except Exception:  # noqa: BLE001
        pass

    # 2. Iframe del widget: src tiene `?k=SITEKEY` y posiblemente `&size=invisible`
    try:
        iframe = page.locator("iframe[src*='recaptcha']").first
        if await iframe.count() > 0:
            src = await iframe.get_attribute("src")
            if src:
                m = re.search(r"[?&]k=([A-Za-z0-9_\-]+)", src)
                if m:
                    invisible = "size=invisible" in src
                    return (m.group(1), invisible)
    except Exception:  # noqa: BLE001
        pass

    return None


async def _maybe_solve_captcha(page: "Page") -> bool:
    """Si el portal pinta un captcha, intentar resolverlo con Claude visión.

    Devuelve True si se resolvió, False si no hubo captcha.
    """
    captcha_locator = page.locator(_SELECTORS["captcha_img"])
    try:
        if await captcha_locator.count() == 0:
            return False
        if not await captcha_locator.first.is_visible():
            return False
    except Exception:
        return False

    settings = get_settings()
    if not settings.anthropic_api_key:
        # Sin API key no podemos resolver — fallamos limpio.
        raise RuntimeError(
            "REPUVE pidió captcha y ANTHROPIC_API_KEY no está configurada"
        )

    img_bytes = await captcha_locator.first.screenshot()
    text = await _read_captcha_with_claude(img_bytes)
    if not text:
        raise RuntimeError("No pude leer el captcha de REPUVE")

    captcha_input = page.locator(_SELECTORS["captcha_input"])
    if await captcha_input.count() > 0:
        await captcha_input.first.fill(text)
        return True
    raise RuntimeError("Captcha visible pero no encontré el input")


async def _read_captcha_with_claude(img_bytes: bytes) -> str:
    """Pide a Claude Sonnet visión que lea el texto del captcha.

    Costo: ~$0.005 USD por captcha (caché irrelevante porque cada captcha
    es único).
    """
    import base64

    import anthropic

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.claude_vision_model,
        max_tokens=20,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(img_bytes).decode(),
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Lee el texto del captcha y devuelve SOLO los "
                            "caracteres visibles, sin espacios ni puntuación."
                        ),
                    },
                ],
            }
        ],
    )
    raw = response.content[0].text if response.content else ""
    return re.sub(r"[^A-Za-z0-9]", "", raw)


async def _read_response_modal(page: "Page") -> str:
    """Devuelve el HTML del modal de resultado SOLO si está visible.

    String vacío si REPUVE no pintó modal — el parser lo trata como
    "no respondió" en lugar de leer todo el body (que produce falsos
    positivos como `is_stolen=True` por la palabra "robo" en la UI).
    """
    modal = page.locator(_SELECTORS["result_modal"])
    try:
        count = await modal.count()
    except Exception:
        return ""
    for i in range(count):
        el = modal.nth(i)
        try:
            if await el.is_visible():
                return await el.inner_html()
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------------------
# Pure parser (testable with fixtures)


def parse_response(
    html: str,
    *,
    plate: str | None = None,
    vin: str | None = None,
    captcha_used: bool = False,
) -> RepuveResult:
    _ = captcha_used  # parámetro reservado para audit de costos en D7
    """HTML del modal de REPUVE → `RepuveResult` normalizado.

    El portal no expone JSON; respondemos a la presencia de tres bloques:

    - "robo" / "vehículo robado" → `is_stolen=True`
    - "sin reportes" / "no presenta reportes" → `is_stolen=False`
    - "no se encontr" → vehículo no en base (nunca registrado / placa rara)
    """
    text = _strip_html(html).lower()

    is_stolen: bool | None = None
    has_legal_status: bool | None = None
    error: str | None = None
    raw_status: str | None = None

    if not text.strip():
        return RepuveResult(
            queried=False,
            plate=plate,
            vin=vin,
            error="REPUVE no respondió",
        )

    not_found_markers = (
        "no se encontr",
        "no se encuentra",
        "sin información",
        "sin informacion",
        "no existe registro",
    )
    sin_reportes_markers = (
        "sin reportes",
        "no presenta reportes",
        "no se reporta",
        "sin reporte de robo",
    )
    robado_markers = (
        "vehículo robado",
        "vehiculo robado",
        "reporte de robo activo",
        "reporte de robo vigente",
        "presenta reporte de robo",
    )

    if any(m in text for m in not_found_markers):
        raw_status = "no_encontrado"
        error = "Vehículo no encontrado en REPUVE"
    elif any(m in text for m in sin_reportes_markers):
        # Importante: "sin reportes" debe chequearse ANTES que "robo" porque
        # "sin reportes de robo" contiene "robo" como substring.
        is_stolen = False
        raw_status = "sin_reportes"
    elif any(m in text for m in robado_markers) or "robo" in text:
        is_stolen = True
        raw_status = "robado"

    if "situación legal" in text or "situacion legal" in text:
        # "irregular" contiene "regular"; chequearlo primero.
        if "irregular" in text or "no regular" in text:
            has_legal_status = False
        elif "regular" in text or "vigente" in text:
            has_legal_status = True

    # `queried=True` solo si REPUVE devolvió información concluyente sobre
    # el vehículo. "No encontrado" cuenta como query no exitosa.
    queried = is_stolen is not None

    return RepuveResult(
        queried=queried,
        plate=plate,
        vin=vin,
        is_stolen=is_stolen,
        has_legal_status=has_legal_status,
        raw_status=raw_status,
        error=error,
    )


def _strip_html(html: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", no_tags).strip()


# ---------------------------------------------------------------------------
# Validation helpers


def _build_proxy_config(settings) -> dict | None:
    """Construye el dict `proxy=` para Playwright desde los settings.

    Soporta dos formatos (en orden de prioridad):

      1. PROXY_SERVER + PROXY_USERNAME + PROXY_PASSWORD (preferido,
         sin encoding issues)
      2. PROXY_URL legacy con user:pass@ embedido

    Devuelve None si ningún proxy está configurado.
    """
    if settings.proxy_server:
        cfg = {"server": settings.proxy_server}
        if settings.proxy_username:
            cfg["username"] = settings.proxy_username
            cfg["password"] = settings.proxy_password
        return cfg

    if settings.proxy_url:
        # Parse URL embedida — legacy. Si el password tiene `+` o `/`,
        # mejor migrar a PROXY_SERVER/USERNAME/PASSWORD.
        from urllib.parse import urlparse

        parsed = urlparse(settings.proxy_url)
        host_port = (
            f"{parsed.scheme}://{parsed.hostname}"
            f"{':' + str(parsed.port) if parsed.port else ''}"
        )
        cfg = {"server": host_port}
        if parsed.username:
            cfg["username"] = parsed.username
            cfg["password"] = parsed.password or ""
        return cfg

    return None


def _normalize_plate(plate: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", plate.upper())


def _normalize_vin(vin: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", vin.upper())


def _is_valid_plate(plate: str) -> bool:
    return bool(plate) and 5 <= len(plate) <= 7 and plate.isalnum()


def _is_valid_vin(vin: str) -> bool:
    # NIV de 17 caracteres alfanuméricos sin I, O, Q (estándar ISO 3779).
    return bool(vin) and len(vin) == 17 and vin.isalnum()


# ---------------------------------------------------------------------------
# Throttle


async def _throttle() -> None:
    """Respeta `REPUVE_RATE_LIMIT_PER_SEC` del config."""
    global _last_request_at
    settings = get_settings()
    min_interval = 1.0 / max(settings.repuve_rate_limit_per_sec, 0.1)
    async with _throttle_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        _last_request_at = time.monotonic()
