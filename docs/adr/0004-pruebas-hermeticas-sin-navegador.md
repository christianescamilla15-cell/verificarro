# ADR 0004 · Pruebas herméticas: ni red ni navegadores durante las pruebas

- Estado: aceptada · Fecha: 2026-11-19
- Código: `backend/app/services/playwright_bootstrap.py`, `backend/tests/conftest.py`,
  `backend/tests/test_playwright_bootstrap.py`
- Commit: 82d7fb0

## Contexto
El job «Backend pytest» quedó rojo desde el 3-may-2026 (a61f68d) y nadie lo notó porque no había rama
protegida. Reproducido en local con el entorno del runner:

1. Cada prueba que levanta la app con `TestClient` corre el `lifespan`, que llama a
   `ensure_chromium_installed()`. En el runner el CLI `playwright` sí está en el PATH, así que se lanzaba
   `playwright install chromium` real (~150 MB) en segundo plano.
2. La descarga dejaba Chromium en `~/.cache/ms-playwright`, y `chromium_installed()` revisaba ese
   directorio además de `PLAYWRIGHT_BROWSERS_PATH`. Las pruebas que fijan `PLAYWRIGHT_BROWSERS_PATH` a un
   directorio vacío y esperan `False` encontraban el binario del HOME y fallaban.
3. En Windows (donde se desarrollaba) el binario no vive en `chrome-linux/`, así que el defecto no se veía.

Además, desde el 10-may (bb015e0) una prueba esperaba un texto del preview que se había cambiado a
propósito.

## Decisión
- `chromium_installed()` usa la misma regla que Playwright: si `PLAYWRIGHT_BROWSERS_PATH` está definido,
  sólo ese directorio; si no, `$XDG_CACHE_HOME/ms-playwright` o `~/.cache/ms-playwright`. Reportar
  «instalado» por un binario que Playwright no va a usar era también un defecto en producción.
- Nuevo interruptor `PLAYWRIGHT_AUTO_INSTALL` (activo por omisión). `tests/conftest.py` lo apaga: ninguna
  prueba descarga navegadores ni deja archivos fuera de `tmp_path`. El auto-install se prueba con mocks.
- La versión de Chromium esperada se compara contra `browsers.json` del Playwright instalado.
- Las pruebas que sí requieren red y navegador (`test_*_live.py`) siguen marcadas como omitidas a propósito.

## Consecuencias
- Una prueba de regresión (`test_browsers_path_defined_ignores_home_cache`) falla si vuelve a mirarse más
  de un directorio.
- El CI corre en ~1 min sin descargar navegadores.
- Regla general para el repo: una prueba que necesite red se marca y se explica; nunca se descarga nada
  como efecto lateral del arranque.
