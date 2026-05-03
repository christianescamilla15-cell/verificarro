"""Playwright Chromium bootstrap defensivo (Opción B fix REPUVE).

## Por qué existe

El runtime de Render a veces despliega sin instalar el binario de Chromium
(buildCommand del dashboard que se desincroniza de render.yaml, Docker
build cache stale, OOM mid-install, etc.). Cuando esto pasa:

    BrowserType.launch_persistent_context: Executable doesn't exist
    at /opt/render/.cache/ms-playwright/chromium-1140/chrome-linux/chrome

REPUVE scrape falla 100% pero el rest del pipeline degrada gracefully
(usuario ve el link manual REPUVE en el preview).

Este módulo verifica al boot si Chromium existe; si no, lanza
`playwright install chromium` en background. Así el primer pago real
podría todavía fallar REPUVE (mientras descarga, ~30-60s) pero
SUBSECUENTES pagos ya tienen Chromium listo. Sin esto, REPUVE queda
roto hasta el próximo redeploy manual con el buildCommand correcto.

## Trade-offs

- ✅ Self-healing — el container se cura solo después del primer boot.
- ✅ Non-blocking — lifespan yield inmediato, install corre en thread.
- ✅ Idempotente — `playwright install chromium` con browser presente
    es no-op de <1s.
- ❌ +200 MB de descarga la primera vez (red Render → CDN Microsoft).
- ❌ Si el binary install falla por permisos/disk-full, NO retry — lo
    detectamos solo si el primer scan también falla.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# Pinned a la versión de Playwright en requirements.txt. Si bumpeas
# Playwright, actualizá este número (tests cubren la consistencia).
_EXPECTED_CHROMIUM_BUILD = "chromium-1140"


def _candidate_chromium_paths() -> list[Path]:
    """Paths donde Playwright busca el binario de Chromium en Linux/Mac.

    Prioridad: PLAYWRIGHT_BROWSERS_PATH (custom) → ~/.cache/ms-playwright
    (default Linux) → /ms-playwright (Docker official Playwright image).
    """
    import os

    paths: list[Path] = []
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if custom:
        paths.append(Path(custom))

    home = os.environ.get("HOME") or os.path.expanduser("~")
    paths.append(Path(home) / ".cache" / "ms-playwright")

    # Imagen oficial de Playwright instala browsers acá
    paths.append(Path("/ms-playwright"))

    return paths


def chromium_installed() -> bool:
    """True si encontramos el binario chrome ejecutable en algún path
    conocido de Playwright. False si no hay binario o no es ejecutable.
    """
    for base in _candidate_chromium_paths():
        if not base.exists():
            continue
        for child in base.iterdir():
            if not child.is_dir() or not child.name.startswith("chromium-"):
                continue
            chrome = child / "chrome-linux" / "chrome"
            if chrome.is_file():
                return True
    return False


def install_chromium_sync() -> tuple[bool, str]:
    """Ejecuta `playwright install chromium` síncrono. Bloquea el thread
    actual hasta ~60s. Devuelve (success, stdout_or_error).

    Pure: no toca state, solo invoca el CLI. Testable mockeando subprocess.
    """
    cli = shutil.which("playwright")
    if not cli:
        return False, "playwright CLI no encontrado en PATH"
    try:
        result = subprocess.run(
            [cli, "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout 180s instalando chromium"
    except OSError as exc:
        return False, f"OSError: {exc}"

    if result.returncode != 0:
        return False, f"returncode={result.returncode} stderr={result.stderr[:200]}"
    return True, result.stdout[:200] or "installed"


async def ensure_chromium_installed() -> None:
    """Boot hook: si Chromium ya está, no-op. Si falta, lanza install
    en thread background y retorna inmediatamente (no bloquea lifespan).

    Llamado desde `app.main.lifespan`. Failure-tolerant — cualquier
    excepción NO bloquea el boot del server.
    """
    try:
        if chromium_installed():
            logger.info(
                "Playwright Chromium presente (%s) — boot continuo",
                _EXPECTED_CHROMIUM_BUILD,
            )
            return

        logger.warning(
            "Playwright Chromium NO encontrado — instalando en background "
            "(REPUVE scrape degrada hasta que termine, ~30-60s)"
        )
        # Dispara en background — no bloquea el lifespan yield.
        # El primer /scan/plate que llegue antes de que termine cae al
        # graceful fallback (queried=False, link manual REPUVE).
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _install_and_log)
    except Exception:  # noqa: BLE001
        logger.exception("Bootstrap Chromium falló (no-bloqueante)")


def _install_and_log() -> None:
    """Sync wrapper para correr en executor + loguear el resultado."""
    success, msg = install_chromium_sync()
    if success:
        logger.info("Chromium auto-install OK: %s", msg)
    else:
        logger.warning(
            "Chromium auto-install FALLÓ — REPUVE seguirá degradado: %s", msg,
        )
