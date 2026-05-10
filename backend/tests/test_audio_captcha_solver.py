"""Tests del audio captcha solver — mockea Whisper, httpx y Playwright Frame.

No corre transcripción real ni baja audio — todo via mocks. La validación
end-to-end vive en test_repuve_live.py (saltado por default).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import audio_captcha_solver
from app.services.audio_captcha_solver import (
    WhisperUnavailable,
    _download_mp3,
    _normalize_digits_es,
    _read_token,
    solve_invisible_recaptcha_audio,
    transcribe_audio,
)


# ---------------------------------------------------------------------------
# _normalize_digits_es — pure


def test_normalize_digits_es_palabras() -> None:
    assert _normalize_digits_es("ocho cinco dos uno") == "8 5 2 1"


def test_normalize_digits_es_ya_numericos() -> None:
    """Si Whisper ya devolvió cifras, idempotente."""
    assert _normalize_digits_es("8521") == "8521"


def test_normalize_digits_es_mixto() -> None:
    """Cifras + palabras (raro, pero defensivo)."""
    assert _normalize_digits_es("8 cinco dos uno") == "8 5 2 1"


def test_normalize_digits_es_no_dígitos_intactos() -> None:
    """Palabras random NO se tocan."""
    assert _normalize_digits_es("hola mundo") == "hola mundo"


# ---------------------------------------------------------------------------
# transcribe_audio — mockea faster-whisper


@pytest.fixture(autouse=True)
def _reset_whisper_cache() -> None:
    """El módulo cachea la instancia del modelo. Reset entre tests."""
    audio_captcha_solver._whisper_model = None


@pytest.mark.asyncio
async def test_transcribe_audio_devuelve_solo_alfanuméricos() -> None:
    """Whisper retorna 'ocho cinco dos uno', limpiamos a '8521'."""
    fake_segment = SimpleNamespace(text="ocho cinco dos uno")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], None)

    with patch.object(audio_captcha_solver, "_get_whisper_model", AsyncMock(return_value=fake_model)):
        result = await transcribe_audio(b"\x00fake-mp3-bytes\x00", language="es")

    assert result == "8521"


@pytest.mark.asyncio
async def test_transcribe_audio_strip_puntuación() -> None:
    """Whisper devuelve 'Es 4, 7, 2.' → quitar coma+punto, lowercase
    (input de reCAPTCHA es case-insensitive)."""
    fake_segment = SimpleNamespace(text="Es 4, 7, 2.")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], None)

    with patch.object(audio_captcha_solver, "_get_whisper_model", AsyncMock(return_value=fake_model)):
        result = await transcribe_audio(b"\x00mp3\x00")

    assert result == "es472"


@pytest.mark.asyncio
async def test_transcribe_audio_sin_faster_whisper(monkeypatch) -> None:
    """Si faster-whisper no está instalado, raise WhisperUnavailable."""
    # Patch _get_whisper_model para que dispare el error real.
    async def _raise_unavailable():
        raise WhisperUnavailable("no instalado en test")

    monkeypatch.setattr(audio_captcha_solver, "_get_whisper_model", _raise_unavailable)

    with pytest.raises(WhisperUnavailable):
        await transcribe_audio(b"\x00mp3\x00")


# ---------------------------------------------------------------------------
# _download_mp3 — mockea httpx


@pytest.mark.asyncio
async def test_download_mp3_éxito() -> None:
    """200 OK con bytes → devuelve los bytes."""
    expected_bytes = b"\xff\xfb\x90\x00mp3-content"

    async def _get(self, url, **kwargs):  # noqa: ARG001
        return httpx.Response(
            200, content=expected_bytes,
            request=httpx.Request("GET", url),
        )

    with patch.object(httpx.AsyncClient, "get", _get):
        result = await _download_mp3("https://example.com/audio.mp3")

    assert result == expected_bytes


@pytest.mark.asyncio
async def test_download_mp3_404_devuelve_none() -> None:
    """HTTP no-200 → None (caller decide qué hacer)."""

    async def _get(self, url, **kwargs):  # noqa: ARG001
        return httpx.Response(
            404, request=httpx.Request("GET", url),
        )

    with patch.object(httpx.AsyncClient, "get", _get):
        result = await _download_mp3("https://example.com/missing.mp3")

    assert result is None


@pytest.mark.asyncio
async def test_download_mp3_timeout_devuelve_none() -> None:
    """httpx.TimeoutException → None, no propaga."""

    async def _get(self, url, **kwargs):  # noqa: ARG001
        raise httpx.TimeoutException("timeout simulado")

    with patch.object(httpx.AsyncClient, "get", _get):
        result = await _download_mp3("https://example.com/slow.mp3")

    assert result is None


# ---------------------------------------------------------------------------
# _read_token — lee g-recaptcha-response del DOM principal


@pytest.mark.asyncio
async def test_read_token_devuelve_value() -> None:
    """Si el textarea existe con value, lo devolvemos."""
    fake_textarea = MagicMock()
    fake_textarea.count = AsyncMock(return_value=1)
    fake_textarea.input_value = AsyncMock(return_value="03AGdBq25fake-token-xyz")

    fake_locator = MagicMock()
    fake_locator.first = fake_textarea

    fake_page = MagicMock()
    fake_page.locator = MagicMock(return_value=fake_locator)

    result = await _read_token(fake_page)
    assert result == "03AGdBq25fake-token-xyz"


@pytest.mark.asyncio
async def test_read_token_textarea_inexistente() -> None:
    fake_locator = MagicMock()
    fake_locator.first = MagicMock(count=AsyncMock(return_value=0))

    fake_page = MagicMock()
    fake_page.locator = MagicMock(return_value=fake_locator)

    result = await _read_token(fake_page)
    assert result is None


@pytest.mark.asyncio
async def test_read_token_textarea_vacío() -> None:
    """Textarea existe pero value es '' → devolvemos None."""
    fake_textarea = MagicMock()
    fake_textarea.count = AsyncMock(return_value=1)
    fake_textarea.input_value = AsyncMock(return_value="")

    fake_locator = MagicMock()
    fake_locator.first = fake_textarea

    fake_page = MagicMock()
    fake_page.locator = MagicMock(return_value=fake_locator)

    result = await _read_token(fake_page)
    assert result is None


# ---------------------------------------------------------------------------
# solve_invisible_recaptcha_audio — orquestación end-to-end con mocks


@pytest.mark.asyncio
async def test_solve_no_challenge_devuelve_true() -> None:
    """Si no hay challenge frame en 10s, asumimos que el form ya se mandó.

    Empíricamente el caso happy de invisible reCAPTCHA con score alto.
    Devolver True deja que el caller siga al modal sin pegar al captcha.
    """
    fake_page = MagicMock()
    fake_page.frames = []  # ningún frame con bframe

    with patch.object(
        audio_captcha_solver, "_find_challenge_frame",
        AsyncMock(return_value=None),
    ):
        result = await solve_invisible_recaptcha_audio(fake_page, timeout_sec=1.0)

    assert result is True


@pytest.mark.asyncio
async def test_solve_happy_path_full() -> None:
    """Challenge aparece → audio click → download → transcribe → type → verify
    → token llega al main page → True."""

    # 1. Mock del frame del challenge
    fake_frame = MagicMock()
    fake_audio_btn_locator = MagicMock()
    fake_audio_btn_locator.click = AsyncMock()
    fake_download_link_locator = MagicMock()
    fake_download_link_locator.get_attribute = AsyncMock(
        return_value="https://google.com/audio.mp3"
    )
    fake_response_input_locator = MagicMock()
    fake_response_input_locator.click = AsyncMock()
    fake_response_input_locator.fill = AsyncMock()
    fake_response_input_locator.press_sequentially = AsyncMock()
    fake_verify_btn_locator = MagicMock()
    fake_verify_btn_locator.click = AsyncMock()
    fake_body_locator = MagicMock()
    fake_body_locator.inner_text = AsyncMock(return_value="audio challenge")

    def _frame_locator(sel: str):
        if "audio-button" in sel:
            return fake_audio_btn_locator
        if "tdownload-link" in sel:
            return fake_download_link_locator
        if "audio-response" in sel:
            return fake_response_input_locator
        if "verify-button" in sel:
            return fake_verify_btn_locator
        if sel == "body":
            return fake_body_locator
        return MagicMock()

    fake_frame.wait_for_selector = AsyncMock()
    fake_frame.locator = MagicMock(side_effect=_frame_locator)

    # 2. Mock del page (con token ya disponible)
    fake_token_textarea = MagicMock()
    fake_token_textarea.count = AsyncMock(return_value=1)
    fake_token_textarea.input_value = AsyncMock(return_value="03AGdBq25real-token")

    fake_page_locator = MagicMock()
    fake_page_locator.first = fake_token_textarea

    fake_page = MagicMock()
    fake_page.locator = MagicMock(return_value=fake_page_locator)

    # 3. Mock dependencies
    with patch.object(audio_captcha_solver, "_find_challenge_frame", AsyncMock(return_value=fake_frame)), \
         patch.object(audio_captcha_solver, "_download_mp3", AsyncMock(return_value=b"\x00mp3\x00")), \
         patch.object(audio_captcha_solver, "transcribe_audio", AsyncMock(return_value="8521")):
        result = await solve_invisible_recaptcha_audio(fake_page, timeout_sec=10.0)

    assert result is True
    # Verificar que SI tipeamos la respuesta de Whisper
    fake_response_input_locator.press_sequentially.assert_awaited_once()
    args, _kwargs = fake_response_input_locator.press_sequentially.await_args
    assert args[0] == "8521"


@pytest.mark.asyncio
async def test_solve_whisper_falla_devuelve_false() -> None:
    """Whisper raise → False, sin tipear ni clickear verify."""
    fake_frame = MagicMock()
    fake_frame.wait_for_selector = AsyncMock()
    fake_audio_btn_locator = MagicMock()
    fake_audio_btn_locator.click = AsyncMock()
    fake_download_link_locator = MagicMock()
    fake_download_link_locator.get_attribute = AsyncMock(
        return_value="https://google.com/audio.mp3"
    )
    fake_body_locator = MagicMock()
    fake_body_locator.inner_text = AsyncMock(return_value="ok")

    def _frame_locator(sel: str):
        if "audio-button" in sel:
            return fake_audio_btn_locator
        if "tdownload-link" in sel:
            return fake_download_link_locator
        if sel == "body":
            return fake_body_locator
        # NO debe pedir input de respuesta ni verify
        raise AssertionError(f"locator inesperado tras Whisper fail: {sel}")

    fake_frame.locator = MagicMock(side_effect=_frame_locator)
    fake_page = MagicMock()

    with patch.object(audio_captcha_solver, "_find_challenge_frame", AsyncMock(return_value=fake_frame)), \
         patch.object(audio_captcha_solver, "_download_mp3", AsyncMock(return_value=b"\x00mp3\x00")), \
         patch.object(
             audio_captcha_solver, "transcribe_audio",
             AsyncMock(side_effect=Exception("Whisper boom")),
         ):
        result = await solve_invisible_recaptcha_audio(fake_page, timeout_sec=5.0)

    assert result is False


@pytest.mark.asyncio
async def test_solve_google_block_devuelve_false() -> None:
    """Tras click audio Google muestra 'Try again later' → False inmediato."""
    fake_frame = MagicMock()
    fake_frame.wait_for_selector = AsyncMock()

    fake_audio_btn_locator = MagicMock()
    fake_audio_btn_locator.click = AsyncMock()
    fake_body_locator = MagicMock()
    fake_body_locator.inner_text = AsyncMock(
        return_value="Sorry, your computer or network may be sending automated queries. Try again later."
    )

    def _frame_locator(sel: str):
        if "audio-button" in sel:
            return fake_audio_btn_locator
        if sel == "body":
            return fake_body_locator
        raise AssertionError(f"locator inesperado tras block: {sel}")

    fake_frame.locator = MagicMock(side_effect=_frame_locator)
    fake_page = MagicMock()

    with patch.object(audio_captcha_solver, "_find_challenge_frame", AsyncMock(return_value=fake_frame)):
        result = await solve_invisible_recaptcha_audio(fake_page, timeout_sec=5.0)

    assert result is False


@pytest.mark.asyncio
async def test_solve_download_falla_devuelve_false() -> None:
    """No pudimos bajar el .mp3 → False."""
    fake_frame = MagicMock()
    fake_frame.wait_for_selector = AsyncMock()

    fake_audio_btn_locator = MagicMock()
    fake_audio_btn_locator.click = AsyncMock()
    fake_download_link_locator = MagicMock()
    fake_download_link_locator.get_attribute = AsyncMock(
        return_value="https://google.com/audio.mp3"
    )
    fake_body_locator = MagicMock()
    fake_body_locator.inner_text = AsyncMock(return_value="ok")

    def _frame_locator(sel: str):
        if "audio-button" in sel:
            return fake_audio_btn_locator
        if "tdownload-link" in sel:
            return fake_download_link_locator
        if sel == "body":
            return fake_body_locator
        raise AssertionError(f"locator inesperado tras download fail: {sel}")

    fake_frame.locator = MagicMock(side_effect=_frame_locator)
    fake_page = MagicMock()

    with patch.object(audio_captcha_solver, "_find_challenge_frame", AsyncMock(return_value=fake_frame)), \
         patch.object(audio_captcha_solver, "_download_mp3", AsyncMock(return_value=None)):
        result = await solve_invisible_recaptcha_audio(fake_page, timeout_sec=5.0)

    assert result is False
