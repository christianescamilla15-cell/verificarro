"""Tests del playwright_bootstrap (Opción B fix REPUVE).

`ensure_chromium_installed()` corre en lifespan al boot. Cubre:
- Detección del binario en paths estándar
- Trigger de install en background si falta
- Fail-open: si el install CLI falla, log warning, no rompe boot
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.services.playwright_bootstrap import (
    chromium_installed,
    ensure_chromium_installed,
    install_chromium_sync,
)


# ---------------------------------------------------------------------------
# chromium_installed — detección de binario


def test_chromium_installed_returns_true_when_chrome_binary_exists(tmp_path) -> None:
    """Si el path candidato tiene chromium-XYZ/chrome-linux/chrome ejecutable,
    detectamos como instalado."""
    chrome_dir = tmp_path / "chromium-1140" / "chrome-linux"
    chrome_dir.mkdir(parents=True)
    (chrome_dir / "chrome").write_text("#!/bin/sh\necho fake")
    (chrome_dir / "chrome").chmod(0o755)

    with patch.dict("os.environ", {"PLAYWRIGHT_BROWSERS_PATH": str(tmp_path)}):
        assert chromium_installed() is True


def test_chromium_installed_returns_false_when_dir_empty(tmp_path) -> None:
    """Path existe pero NO tiene subdirs chromium-* → false."""
    with patch.dict("os.environ", {"PLAYWRIGHT_BROWSERS_PATH": str(tmp_path)}):
        assert chromium_installed() is False


def test_chromium_installed_false_when_chromium_dir_but_no_executable(tmp_path) -> None:
    """Tenemos el subdir chromium-1140 pero falta el binario chrome."""
    (tmp_path / "chromium-1140" / "chrome-linux").mkdir(parents=True)
    with patch.dict("os.environ", {"PLAYWRIGHT_BROWSERS_PATH": str(tmp_path)}):
        assert chromium_installed() is False


def test_chromium_installed_false_when_no_paths_exist(tmp_path) -> None:
    """Ninguno de los paths candidatos existe → false."""
    nonexistent = tmp_path / "definitely-not-here"
    with patch.dict("os.environ", {
        "PLAYWRIGHT_BROWSERS_PATH": str(nonexistent),
        "HOME": str(nonexistent),
    }):
        assert chromium_installed() is False


# ---------------------------------------------------------------------------
# install_chromium_sync — invocación del CLI


def test_install_chromium_sync_returns_false_when_cli_missing() -> None:
    """Si playwright CLI no está en PATH, retorna (False, mensaje)."""
    with patch("shutil.which", return_value=None):
        ok, msg = install_chromium_sync()
    assert ok is False
    assert "no encontrado" in msg.lower()


def test_install_chromium_sync_success_path() -> None:
    """CLI returncode=0 → success."""
    fake_result = MagicMock(returncode=0, stdout="Chromium 1140 installed", stderr="")
    with patch("shutil.which", return_value="/usr/local/bin/playwright"), \
         patch("subprocess.run", return_value=fake_result):
        ok, msg = install_chromium_sync()
    assert ok is True
    assert "installed" in msg.lower()


def test_install_chromium_sync_failure_returncode() -> None:
    """returncode != 0 → failure con stderr en el mensaje."""
    fake_result = MagicMock(returncode=1, stdout="", stderr="permission denied")
    with patch("shutil.which", return_value="/usr/local/bin/playwright"), \
         patch("subprocess.run", return_value=fake_result):
        ok, msg = install_chromium_sync()
    assert ok is False
    assert "permission" in msg.lower()


def test_install_chromium_sync_handles_timeout() -> None:
    """Si el CLI tarda >180s, capturamos TimeoutExpired."""
    with patch("shutil.which", return_value="/usr/local/bin/playwright"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired("playwright", 180)):
        ok, msg = install_chromium_sync()
    assert ok is False
    assert "timeout" in msg.lower()


# ---------------------------------------------------------------------------
# ensure_chromium_installed — boot hook


@pytest.mark.asyncio
async def test_ensure_chromium_skip_when_already_installed() -> None:
    """Si chromium_installed retorna True, NO disparamos install."""
    with patch(
        "app.services.playwright_bootstrap.chromium_installed",
        return_value=True,
    ), patch(
        "app.services.playwright_bootstrap._install_and_log",
    ) as mock_install:
        await ensure_chromium_installed()
    assert mock_install.call_count == 0


@pytest.mark.asyncio
async def test_ensure_chromium_dispatches_install_when_missing() -> None:
    """Si falta, lanza _install_and_log en executor (background)."""
    install_invoked = asyncio.Event()

    def fake_install():
        install_invoked.set()

    with patch(
        "app.services.playwright_bootstrap.chromium_installed",
        return_value=False,
    ), patch(
        "app.services.playwright_bootstrap._install_and_log",
        side_effect=fake_install,
    ):
        await ensure_chromium_installed()
        # Esperamos un tick para que el executor agarre el job
        await asyncio.wait_for(install_invoked.wait(), timeout=2.0)


@pytest.mark.asyncio
async def test_ensure_chromium_swallows_unexpected_errors() -> None:
    """Cualquier exc en chromium_installed NO debe romper el boot."""
    with patch(
        "app.services.playwright_bootstrap.chromium_installed",
        side_effect=RuntimeError("filesystem corrupted"),
    ):
        # Si esto lanza, el lifespan se cae y Render reinicia loop.
        # Debe loggear y continuar silenciosamente.
        await ensure_chromium_installed()  # no raises
