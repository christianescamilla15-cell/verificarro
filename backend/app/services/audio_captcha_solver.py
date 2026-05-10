"""reCAPTCHA v2 audio-challenge solver — local Whisper, sin APIs externas.

## Por qué existe

`captcha_solver.py` resuelve reCAPTCHA v2 vía 2Captcha (red de humanos,
~$0.003/solve, 10-30s). Este módulo intenta lo mismo gratis: usa el
botón "audio challenge" del propio widget reCAPTCHA (canal de
accesibilidad oficial de Google), descarga el .mp3, lo transcribe con
Whisper local (`faster-whisper`), tipea la respuesta y hace click en
verify.

- **Costo**: $0 (Whisper corre local, modelo ~75 MB en disco).
- **Latencia**: 3-7s end-to-end (1-2s download, 1-2s transcribe, 1s UI).
- **Hit rate empírico esperado**: 60-85% cuando IP no es flag de
  datacenter; 0-30% sobre IP datacenter (mismo bottleneck que 2Captcha).

## Diferencia arquitectural vs 2Captcha

| Eje | 2Captcha (`captcha_solver.py`) | Audio (este módulo) |
|---|---|---|
| Cuándo se invoca | ANTES de submit (inyecta token + monkey-patch) | DESPUÉS de submit (drive el iframe del challenge) |
| Token | Devuelve string para inyectar | El propio reCAPTCHA pone el token en `g-recaptcha-response` cuando passemos el challenge |
| Modelo | Pull (preguntamos por token) | Push (drive del UI hasta que valide) |

REPUVE usa **reCAPTCHA v2 invisible**: el challenge solo aparece cuando
el score es bajo. Es decir, este solver:

1. Espera que aparezca el iframe del challenge POST-submit.
2. Si no aparece (score alto, form ya se mandó) → return True (no había
   nada que resolver).
3. Si aparece, drive el flow audio → text → verify.

## Fallback chain

`repuve.py` orquesta:

    [intento 1] inject 2Captcha token PRE-submit (si está config)
    → click submit
    [intento 2] post-submit, si aparece challenge: audio_solver.run()
    → si valida, form submits y leemos modal
    → si no, raw_status="captcha_required"

## Whisper modelo

Default `tiny` (75 MB, ~1-2s CPU). reCAPTCHA audio dice 4 dígitos en
voz humana clara — `tiny` es suficiente. Bumpear a `base` (142 MB) si
ves WER alto. `WHISPER_MODEL_SIZE` env var controla esto.

## Detection risk

Google detecta automation del audio challenge: solving instantáneo,
audio replay, IP datacenter. Mitigaciones aplicadas:

- Pausa human-like 1-2s entre click audio y typing
- Typing con delay (no instant fill)
- Click verify con delay sostenido

Sigue siendo IP-bound. Sobre IP datacenter, Google rechaza incluso con
audio resuelto perfecto. Lo mismo que medimos en la tanda de 67 con 2Captcha.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import TYPE_CHECKING

import httpx

from app.config import get_settings

if TYPE_CHECKING:
    from playwright.async_api import Frame, Page

logger = logging.getLogger(__name__)


# Selectores observados en widget reCAPTCHA v2 audio challenge (2026-05-09).
# Si Google los cambia, ajustar aquí — el resto del módulo sigue igual.
_SEL_CHALLENGE_FRAME_URL = "api2/bframe"     # fragment del src del iframe
_SEL_AUDIO_BUTTON = "#recaptcha-audio-button"
_SEL_AUDIO_DOWNLOAD = "a.rc-audiochallenge-tdownload-link"
_SEL_AUDIO_RESPONSE_INPUT = "#audio-response"
_SEL_VERIFY_BUTTON = "#recaptcha-verify-button"
_SEL_TOKEN_TEXTAREA = "textarea[name='g-recaptcha-response'], #g-recaptcha-response"

# Mensaje que Google muestra cuando detecta abuso del audio challenge.
# Texto canónico — si aparece, abortamos con flag específico para que
# repuve.py degrade limpio sin reintentar inutilmente.
_BLOCK_MARKER = "Try again later"


class WhisperUnavailable(RuntimeError):
    """faster-whisper no se pudo importar (paquete no instalado)."""


# ---------------------------------------------------------------------------
# Whisper — lazy import + global model cache


_whisper_model = None  # type: ignore[var-annotated]
_whisper_lock = asyncio.Lock()


async def _get_whisper_model():
    """Carga el modelo Whisper la primera vez y lo cachea.

    `faster-whisper` descarga el modelo a `~/.cache/huggingface/` la
    primera vez (~75 MB para `tiny`). Las siguientes invocaciones reusan
    desde RAM.

    Lock async porque dos requests concurrentes en frío harían dos
    descargas del modelo simultáneas (race en HuggingFace cache).
    """
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    async with _whisper_lock:
        if _whisper_model is not None:  # double-check after acquiring lock
            return _whisper_model

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise WhisperUnavailable(
                "faster-whisper no instalado. `pip install faster-whisper`"
            ) from exc

        settings = get_settings()
        model_size = settings.whisper_model_size or "tiny"
        # CPU compute_type=int8 → más rápido en CPU y menor RAM (~150 MB
        # en runtime para tiny). float32 sería ~300 MB sin gain notorio
        # para nuestro caso de 4 dígitos.
        loop = asyncio.get_running_loop()
        _whisper_model = await loop.run_in_executor(
            None,
            lambda: WhisperModel(
                model_size, device="cpu", compute_type="int8"
            ),
        )
        logger.info("Whisper model %s loaded (compute_type=int8, cpu)", model_size)
        return _whisper_model


async def transcribe_audio(mp3_bytes: bytes, *, language: str | None = None) -> str:
    """Transcribe un .mp3 con Whisper local. Devuelve solo dígitos/letras.

    `language` opcional fuerza el detector de idioma. reCAPTCHA suele
    leer 4 dígitos en español (locale es-MX en nuestro Playwright); si
    Google decide cambiar a inglés en algún edge case, dejamos auto.

    El return se limpia a `[A-Za-z0-9]+` porque el input del audio
    challenge solo acepta dígitos/letras (sin espacios ni puntuación).
    """
    model = await _get_whisper_model()

    # Whisper API toma path o ndarray. Para bytes en memoria → tempfile.
    import tempfile

    loop = asyncio.get_running_loop()

    def _do_transcribe():
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_bytes)
            tmp_path = f.name
        try:
            segments, _info = model.transcribe(
                tmp_path,
                language=language,
                # Beam=1 (greedy) más rápido y suficiente para 4 dígitos
                beam_size=1,
                # vad_filter=True quita silencios → más rápido en audio
                # con cola larga de silence (típico en reCAPTCHA)
                vad_filter=True,
            )
            return " ".join(seg.text for seg in segments).strip()
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    raw_text = await loop.run_in_executor(None, _do_transcribe)
    # Convert "ocho" / "nueve" etc to digits if Whisper devolvió palabras
    cleaned = _normalize_digits_es(raw_text)
    # reCAPTCHA acepta solo alfanumérico, sin espacios
    final = re.sub(r"[^A-Za-z0-9]", "", cleaned)
    logger.info("Whisper raw=%r → clean=%r", raw_text, final)
    return final


# Mapa básico ES→dígito por si Whisper devuelve palabras en vez de cifras
# (sucede a veces en `tiny`). reCAPTCHA dice los dígitos uno por uno
# así que basta este mapeo simple, no necesitamos parsing numérico
# completo.
_ES_DIGITS = {
    "cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
}


def _normalize_digits_es(text: str) -> str:
    """Reemplaza palabras ES de dígitos por su cifra. Idempotente."""
    out = text.lower()
    for word, digit in _ES_DIGITS.items():
        out = re.sub(rf"\b{word}\b", digit, out)
    return out


# ---------------------------------------------------------------------------
# Audio download


async def _download_mp3(url: str, *, timeout_sec: float = 15.0) -> bytes | None:
    """Baja el .mp3 del audio challenge. None en error de red."""
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.get(url)
            if response.status_code != 200:
                logger.warning(
                    "Audio download HTTP %d: %s", response.status_code, url[:80],
                )
                return None
            return response.content
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("Audio download error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Frame discovery — el challenge vive en un iframe cross-origin


async def _find_challenge_frame(
    page: "Page", *, timeout_sec: float = 10.0
) -> "Frame | None":
    """Busca el iframe del challenge reCAPTCHA. None si no aparece a tiempo.

    El widget reCAPTCHA tiene 2 iframes: `anchor` (la checkbox visible o
    el invisible badge) y `bframe` (el challenge UI cuando se dispara).
    El bframe solo existe cuando hay un challenge activo.
    """
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        for frame in page.frames:
            if _SEL_CHALLENGE_FRAME_URL in (frame.url or ""):
                # bframe puede existir pero estar oculto (no challenge
                # activo). Probamos a ver si el botón audio renderizó.
                try:
                    btn = frame.locator(_SEL_AUDIO_BUTTON)
                    if await btn.count() > 0:
                        return frame
                except Exception:  # noqa: BLE001
                    continue
        await asyncio.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# Main entry — drive el challenge end-to-end


async def solve_invisible_recaptcha_audio(
    page: "Page", *, timeout_sec: float = 60.0,
) -> bool:
    """Drive del audio challenge POST-submit. Devuelve True si validó.

    Llamar DESPUÉS de hacer click en el botón submit del formulario.
    Si reCAPTCHA invisible no dispara challenge (score alto) devolvemos
    True inmediato porque no había nada que resolver y el form ya se mandó.

    Pasos:
      1. Espera bframe del challenge (≤10s)
      2. Click en audio button (humanizado con delay)
      3. Lee el href del download link → audio mp3 URL
      4. Descarga + transcribe con Whisper local
      5. Tipea respuesta en `#audio-response` (con delay)
      6. Click verify
      7. Espera que `g-recaptcha-response` tenga token

    En cualquier paso fallido devolvemos False para que el caller caiga
    al fallback de 2Captcha (o a `captcha_required` si tampoco está).

    `timeout_sec` es presupuesto END-TO-END del solve completo.
    """
    deadline = asyncio.get_running_loop().time() + timeout_sec

    # 1. Localizar iframe del challenge
    frame = await _find_challenge_frame(page, timeout_sec=10.0)
    if not frame:
        # Sin challenge → invisible reCAPTCHA dejó pasar (score OK).
        # NO es un error: el form ya se mandó.
        logger.info("Sin challenge frame — score reCAPTCHA OK, form ya enviado")
        return True

    # 2. Click audio button (humanizado)
    try:
        await frame.wait_for_selector(_SEL_AUDIO_BUTTON, timeout=5_000)
        await asyncio.sleep(random.uniform(0.4, 0.9))
        await frame.locator(_SEL_AUDIO_BUTTON).click(
            delay=random.randint(80, 180)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No pude clickear audio button: %s", exc)
        return False

    # Detect block ANTES de seguir — Google a veces despliega bloqueo
    # inmediato tras click audio si la sesión está flagged.
    if await _is_blocked(frame):
        logger.warning("reCAPTCHA bloqueado tras audio click ('Try again later')")
        return False

    # 3. Esperar download link y leer href
    try:
        await frame.wait_for_selector(_SEL_AUDIO_DOWNLOAD, timeout=10_000)
        audio_url = await frame.locator(_SEL_AUDIO_DOWNLOAD).get_attribute("href")
    except Exception as exc:  # noqa: BLE001
        logger.warning("No encontré download link del audio: %s", exc)
        return False

    if not audio_url:
        return False

    # 4. Download + transcribe
    if asyncio.get_running_loop().time() >= deadline:
        logger.warning("Timeout antes de descargar audio")
        return False

    mp3_bytes = await _download_mp3(audio_url)
    if not mp3_bytes:
        return False

    try:
        text = await transcribe_audio(mp3_bytes, language="es")
    except WhisperUnavailable:
        logger.error("faster-whisper no instalado — abortando audio solver")
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Whisper falló: %s", exc)
        return False

    if not text:
        logger.warning("Whisper devolvió texto vacío")
        return False

    # 5. Type response (con delay para parecer humano)
    try:
        # Click primero para focus
        await frame.locator(_SEL_AUDIO_RESPONSE_INPUT).click(
            delay=random.randint(60, 130)
        )
        await asyncio.sleep(random.uniform(0.2, 0.5))
        await frame.locator(_SEL_AUDIO_RESPONSE_INPUT).fill("")  # clear
        # `pressSequentially` mete delay entre cada char (Playwright nuevo)
        # En versiones viejas usar type(). Probamos primero pressSequentially.
        try:
            await frame.locator(_SEL_AUDIO_RESPONSE_INPUT).press_sequentially(
                text, delay=random.randint(40, 110)
            )
        except AttributeError:
            await frame.locator(_SEL_AUDIO_RESPONSE_INPUT).type(
                text, delay=random.randint(40, 110)
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No pude tipear respuesta audio: %s", exc)
        return False

    # 6. Click verify
    try:
        await asyncio.sleep(random.uniform(0.3, 0.8))
        await frame.locator(_SEL_VERIFY_BUTTON).click(
            delay=random.randint(100, 200)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No pude clickear verify: %s", exc)
        return False

    # 7. Esperar token en g-recaptcha-response (max 10s, capped a deadline)
    remaining = max(1.0, deadline - asyncio.get_running_loop().time())
    poll_budget = min(10.0, remaining)
    poll_start = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - poll_start < poll_budget:
        token = await _read_token(page)
        if token:
            logger.info("Audio challenge resuelto, token len=%d", len(token))
            return True
        # Detect Google rejection (text rechazado, audio mal transcrito)
        if await _is_blocked(frame):
            logger.warning("Google rechazó la respuesta del audio")
            return False
        await asyncio.sleep(0.5)

    logger.warning("Timeout esperando token tras verify")
    return False


async def _read_token(page: "Page") -> str | None:
    """Lee `g-recaptcha-response` del DOM principal. None si vacío."""
    try:
        textarea = page.locator(_SEL_TOKEN_TEXTAREA).first
        if await textarea.count() == 0:
            return None
        # `value` desde el DOM, no `inner_text` (textarea usa value).
        value = await textarea.input_value()
        return value or None
    except Exception:  # noqa: BLE001
        return None


async def _is_blocked(frame: "Frame") -> bool:
    """Detecta el banner de Google 'Try again later' que indica abuse flag."""
    try:
        body_text = await frame.locator("body").inner_text()
        return _BLOCK_MARKER.lower() in (body_text or "").lower()
    except Exception:  # noqa: BLE001
        return False
