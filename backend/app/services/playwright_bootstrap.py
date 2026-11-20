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
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# Build de Chromium que trae la versión de Playwright fijada en
# requirements.txt (playwright==1.52.0 → chromium-1169). Si subes
# Playwright, actualiza este número: `test_expected_build_matches_installed_playwright`
# lo compara contra el browsers.json del paquete instalado.
_EXPECTED_CHROMIUM_BUILD = "chromium-1169"

# Interruptor del auto-install. En pruebas se apaga (tests/conftest.py):
# una prueba no debe descargar ~150 MB de navegador como efecto lateral
# del lifespan, ni dejar un binario en el HOME que cambie el resultado
# de otras pruebas.
_AUTO_INSTALL_ENV = "PLAYWRIGHT_AUTO_INSTALL"

# Nombre del directorio del binario según la versión de Playwright
# (≤1.5x usa chrome-linux; las más nuevas, chrome-linux64).
_CHROME_LINUX_DIRS = ("chrome-linux", "chrome-linux64")


def _candidate_chromium_paths() -> list[Path]:
    """Directorio donde Playwright buscará Chromium, con su misma regla.

    Playwright resuelve UN solo directorio de navegadores:
    - si `PLAYWRIGHT_BROWSERS_PATH` está definido, sólo ése (la imagen
      oficial de Playwright lo define como `/ms-playwright`, y
      `scraper-mx.Dockerfile` también);
    - si no, `$XDG_CACHE_HOME/ms-playwright` o `~/.cache/ms-playwright`.

    Antes se revisaban los tres a la vez; eso podía reportar «instalado»
    por un binario que Playwright nunca va a usar y hacía que las pruebas
    dependieran del HOME de la máquina (causa del CI rojo desde mayo).
    El valor especial "0" (navegadores dentro del paquete) no se usa en
    este proyecto y se trata como no definido.
    """
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if custom and custom != "0":
        return [Path(custom)]

    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        cache = Path(xdg)
    else:
        home = os.environ.get("HOME") or os.path.expanduser("~")
        cache = Path(home) / ".cache"
    return [cache / "ms-playwright"]


def chromium_installed() -> bool:
    """True si encontramos el binario chrome ejecutable en el directorio
    que Playwright va a usar. False si no hay binario.
    """
    for base in _candidate_chromium_paths():
        if not base.exists():
            continue
        for child in base.iterdir():
            if not child.is_dir() or not child.name.startswith("chromium-"):
                continue
            for linux_dir in _CHROME_LINUX_DIRS:
                if (child / linux_dir / "chrome").is_file():
                    return True
    return False


def auto_install_enabled() -> bool:
    """El auto-install está activo salvo `PLAYWRIGHT_AUTO_INSTALL=false|0|no`."""
    valor = os.environ.get(_AUTO_INSTALL_ENV, "true").strip().lower()
    return valor not in {"false", "0", "no", "off"}


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

        if not auto_install_enabled():
            logger.info(
                "Playwright Chromium NO encontrado y %s=false — no se "
                "instala (REPUVE degrada al flujo manual)",
                _AUTO_INSTALL_ENV,
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
