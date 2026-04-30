"""REPUVE consulta ciudadana scraper.

Portal: ``https://www2.repuve.gob.mx:8443/ciudadania/``

Es un SPA de Angular con cuatro campos de búsqueda (placa, NIV, folio,
NCI). Esta implementación cubre los dos primeros — el resto sale del
scope MVP.

## Limitación conocida — reCaptcha de Google (2026-04-30)

REPUVE protege la consulta con **reCaptcha**, no con un captcha de
imagen. Claude visión puede leer captchas de texto pero NO resuelve
reCaptcha v2/v3 (es un widget de Google con análisis de comportamiento).

Por eso `query()` actualmente:

1. Carga el portal, llena placa/NIV y hace click en "Buscar".
2. Si tras el submit aparece la alerta "El reCaptcha no fue superado
   correctamente", devuelve `RepuveResult(queried=False, error=...)` con
   un mensaje accionable y `raw_status="captcha_required"`.
3. La UI debe ofrecer un fallback manual: link a REPUVE y campo para
   pegar el resultado.

Migración futura a 2Captcha / Anti-Captcha (~$0.003 USD por reCaptcha)
es directa cuando justifique el volumen — basta con plug-in en
`_solve_recaptcha()`.

## Throttle

`REPUVE_RATE_LIMIT_PER_SEC` del config. 1 req/s mantiene la consulta
dentro del rango de uso ciudadano normal.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING

from app.config import get_settings
from app.models.report import RepuveResult

if TYPE_CHECKING:
    from playwright.async_api import Page

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
}

# Token throttling — un solo lock global por proceso.
_throttle_lock = asyncio.Lock()
_last_request_at: float = 0.0


async def query(plate: str | None = None, vin: str | None = None) -> RepuveResult:
    """Consulta REPUVE por placa o NIV. Devuelve `RepuveResult` siempre."""
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

    await _throttle()

    try:
        return await _run_query(plate_norm, vin_norm)
    except Exception as exc:  # noqa: BLE001
        return RepuveResult(
            queried=False,
            plate=plate_norm,
            vin=vin_norm,
            error=f"Error al consultar REPUVE: {exc}",
        )


# ---------------------------------------------------------------------------
# Driver


async def _run_query(plate: str | None, vin: str | None) -> RepuveResult:
    settings = get_settings()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=settings.playwright_headless,
            args=["--ignore-certificate-errors"],
        )
        try:
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                locale="es-MX",
                viewport={"width": 1280, "height": 900},
                ignore_https_errors=True,
            )
            page = await context.new_page()
            await page.goto(
                REPUVE_URL,
                wait_until="networkidle",
                timeout=settings.scrape_timeout_ms,
            )
            # Angular pinta el formulario después de domcontentloaded.
            await page.wait_for_selector(
                _SELECTORS["plate_input"], timeout=10_000
            )

            if plate:
                input_selector = _SELECTORS["plate_input"]
                await page.fill(input_selector, plate)
            else:
                input_selector = _SELECTORS["vin_input"]
                await page.fill(input_selector, vin or "")

            captcha_solved = await _maybe_solve_captcha(page)
            await _click_submit(page, input_selector)
            await page.wait_for_timeout(3_000)

            if await _has_recaptcha_error(page):
                return RepuveResult(
                    queried=False,
                    plate=plate,
                    vin=vin,
                    raw_status="captcha_required",
                    error=(
                        "REPUVE pidió reCaptcha. Consulta manualmente en "
                        "repuve.gob.mx y pega el resultado en la app."
                    ),
                )

            modal_html = await _read_response_modal(page)
            return parse_response(
                modal_html,
                plate=plate,
                vin=vin,
                captcha_used=captcha_solved,
            )
        finally:
            await browser.close()


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
    """Click en el primer botón visible cuyo texto sea Buscar / Consultar.

    El SPA de Angular no envuelve los inputs de búsqueda en `<form>` HTML —
    el envío es por click handler. La alerta "POR FAVOR, INGRESE SÓLO UN
    CRITERIO DE BÚSQUEDA" que se ve siempre es texto INFORMATIVO permanente,
    no respuesta a un submit.
    """
    accepted = {t.lower() for t in _SELECTORS["submit_btn_text"]}
    buttons = page.locator("button:visible")
    count = await buttons.count()
    for i in range(count):
        btn = buttons.nth(i)
        try:
            text = (await btn.inner_text()).strip().lower()
            if text and any(label in text for label in accepted):
                await btn.click()
                return
        except Exception:
            continue


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
