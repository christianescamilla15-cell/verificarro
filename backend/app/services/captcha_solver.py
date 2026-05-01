"""2Captcha API client — resuelve reCaptcha v2 vía red de humanos.

REPUVE protege la consulta con reCaptcha v2 de Google. Claude visión NO
puede resolverlo (Google hace análisis de comportamiento, no es OCR).
2Captcha (2captcha.com) tiene una red de humanos que resuelven captchas
en ~10-30s y devuelven el token `g-recaptcha-response` que inyectamos
en la página antes de enviar el formulario.

## Costos

- reCaptcha v2: ~$2.99 USD / 1000 solves = **~$0.003 USD por solve**
- Saldo mínimo: $10 USD (válido sin caducidad)
- A volumen 2,000 reportes/día: $6/día = ~$180/mes

## Flow del API

1. `POST https://2captcha.com/in.php?key=API_KEY&method=userrecaptcha&googlekey=SITEKEY&pageurl=URL`
   → devuelve `OK|TASK_ID`
2. Polling cada 5s: `GET https://2captcha.com/res.php?key=API_KEY&action=get&id=TASK_ID`
   → devuelve `CAPCHA_NOT_READY` o `OK|TOKEN`
3. Inyectamos token via `document.getElementById('g-recaptcha-response').innerHTML = TOKEN`
4. Submit del formulario → REPUVE devuelve datos reales

## Degradación

Si:
- `CAPTCHA_SOLVER_API_KEY` no está set → devolvemos None inmediato
- 2Captcha falla / timeout → devolvemos None
- Saldo de 2Captcha agotado → devolvemos None

En todos los casos, REPUVE cae al flow legacy (preview con
`captcha_required`).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


_SUBMIT_URL = "https://2captcha.com/in.php"
_RESULT_URL = "https://2captcha.com/res.php"
_POLL_INTERVAL_SEC = 5.0
_POLL_MAX_SECONDS = 120  # 2Captcha promete <60s típico, damos margen 2x
_HTTP_TIMEOUT_SEC = 15.0


async def solve_recaptcha_v2(
    sitekey: str, page_url: str, *, invisible: bool = False
) -> str | None:
    """Resuelve un reCaptcha v2 vía 2Captcha. Devuelve el token o None.

    `sitekey` viene del atributo `data-sitekey` del widget reCaptcha
    en la página, o del query param de la iframe `?k=SITEKEY`.
    `page_url` es la URL exacta donde está embebido el captcha.
    `invisible=True` para reCaptcha v2 invisible (size=invisible) — sin
    este flag, 2Captcha devuelve un token de la variante visible que
    Google rechaza al verificar (siteverify) en el sitio.

    El polling máximo es 120s. Si tarda más asumimos que algo falló y
    devolvemos None — el llamante decide qué hacer (típicamente caer
    al flow legacy "captcha_required").
    """
    settings = get_settings()
    api_key = settings.captcha_solver_api_key
    if not api_key:
        logger.info("CAPTCHA_SOLVER_API_KEY no configurada, skip")
        return None

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
            task_id = await _submit_task(
                client, api_key, sitekey, page_url, invisible=invisible
            )
            if not task_id:
                return None
            return await _poll_result(client, api_key, task_id)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("2Captcha network error: %s", exc)
        return None


async def _submit_task(
    client: httpx.AsyncClient,
    api_key: str,
    sitekey: str,
    page_url: str,
    *,
    invisible: bool = False,
) -> str | None:
    """POST /in.php con method=userrecaptcha. Devuelve el task_id o None.

    Si `invisible=True`, agrega el flag `invisible=1` que 2Captcha usa
    para distinguir v2 visible de v2 invisible. Es CRÍTICO para sitios
    como REPUVE — sin el flag, el token resultante es rechazado.
    """
    payload = {
        "key": api_key,
        "method": "userrecaptcha",
        "googlekey": sitekey,
        "pageurl": page_url,
        "json": "0",
    }
    if invisible:
        payload["invisible"] = "1"

    response = await client.post(_SUBMIT_URL, data=payload)
    response.raise_for_status()
    text = response.text.strip()

    if not text.startswith("OK|"):
        logger.warning("2Captcha submit rechazado: %s", text)
        return None
    return text.split("|", 1)[1]


async def _poll_result(
    client: httpx.AsyncClient, api_key: str, task_id: str
) -> str | None:
    """Polling cada 5s hasta que devuelve token o timeout."""
    deadline = _POLL_MAX_SECONDS
    elapsed = 0
    while elapsed < deadline:
        await asyncio.sleep(_POLL_INTERVAL_SEC)
        elapsed += _POLL_INTERVAL_SEC

        response = await client.get(
            _RESULT_URL,
            params={
                "key": api_key,
                "action": "get",
                "id": task_id,
                "json": "0",
            },
        )
        response.raise_for_status()
        text = response.text.strip()

        if text == "CAPCHA_NOT_READY":
            continue
        if text.startswith("OK|"):
            return text.split("|", 1)[1]
        # Cualquier otra respuesta es error (ERROR_CAPTCHA_UNSOLVABLE, etc.)
        logger.warning("2Captcha resultado inesperado: %s", text)
        return None

    logger.warning("2Captcha timeout tras %ds polling task=%s", deadline, task_id)
    return None
