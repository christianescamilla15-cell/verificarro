# Verificarro backend Dockerfile
#
# Base: imagen oficial de Microsoft Playwright para Python (Ubuntu 24.04 «noble»). Trae:
# - Python 3.12 (la variante «jammy» trae 3.10: con ella el CI —que prueba en 3.12— pasaba en verde y
#   producción no podía instalar dependencias que exigen 3.11+. El job «imagen» del CI ahora lo detecta.)
# - Chromium + Firefox + WebKit pre-instalados (~600 MB total)
# - Todas las dependencias linux que los browsers necesitan (libnss3,
#   libxss1, libasound2, etc. — 30+ libs que normalmente requieren
#   `playwright install-deps` con sudo)
#
# Por qué esto vs python:3.12-slim:
# Render Starter NO permite sudo, así que `playwright install-deps`
# falla y los browsers crashean en runtime aunque el binario exista.
# La imagen oficial Playwright ya tiene todo. Trade-off: imagen ~700 MB
# vs ~120 MB del slim. Para Render Starter (512 MB RAM, no limit de
# disco) es aceptable — el cold start solo agrega ~10s al pull.
#
# La etiqueta de la imagen NO tiene que coincidir con la playwright de requirements.txt: la imagen aporta
# Ubuntu 24.04, Python 3.12 y las librerías de sistema de los navegadores, y `playwright install chromium`
# (abajo) baja el Chromium de la versión instalada por pip. Lo que sí debe coincidir es el Python con el del
# CI (3.12): el job «imagen» lo comprueba. Mantener la variante «noble» (Ubuntu 24.04).
#
# Build: docker build -t verificarro-backend .
# Run:   docker run -p 3009:3009 --env-file .env verificarro-backend

FROM mcr.microsoft.com/playwright/python:v1.65.2-noble AS runtime

WORKDIR /app

# System deps adicionales:
# - libpq5 para asyncpg (Postgres driver requiere libpq runtime)
# - curl para healthcheck
# Playwright base ya trae todo lo demás (libnss3, libdrm, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar Python deps primero (mejor cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Re-confirmar Chromium instalado (no-op si la imagen base ya lo tiene,
# defensivo si Microsoft cambia el layout). El playwright_bootstrap
# del lifespan también checa al boot — doble red de seguridad.
RUN playwright install chromium

# Copiar código de la app
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Crear non-root user. La imagen Playwright ya tiene un user `pwuser`
# (uid 1001) preconfigurado para correr browsers sin sandbox issues.
# Aseguramos que tenga home dir y cache dir para Camoufox antes del switch.
RUN chown -R pwuser:pwuser /app && \
    mkdir -p /home/pwuser/.cache && \
    chown -R pwuser:pwuser /home/pwuser
USER pwuser

# NOTA 2026-05-14: Camoufox fetch DESHABILITADO en Render.
#
# Razones empíricas del smoke 09:22-09:26:
#   1. Camoufox descargó a /home/pwuser/.cache/camoufox/ durante build,
#      pero Render runtime usa /opt/render/.cache/ → cache miss, lo
#      re-descarga en runtime (713MB extra, ~30s).
#   2. Aún descargado correcto, Firefox custom de Camoufox necesita
#      `glxtest` binary + libs OpenGL que la imagen Playwright base
#      NO incluye. Camoufox crash con "FireTestProcess failed", luego
#      timeout 180000ms en launch_persistent_context.
#   3. Stock Playwright fallback DEL endpoint /api/repuve/live YA
#      funciona (logs muestran [audio-live] solver invocado tras el
#      fallback). Camoufox solo agregaba 4 minutos de latencia + crash.
#
# Si en el futuro necesitamos Camoufox en Render:
#   - Cambiar base image a una con OpenGL libs (e.g., python:3.12 +
#     apt install libgtk-3-0 libgl1 libegl1 libgles2)
#   - Setear XDG_CACHE_HOME=/opt/render/.cache antes del fetch
#   - O usar runtime download (no Dockerfile) + esperar 35s first request
#
# Camoufox sigue disponible para DEV local (Christian's machine) donde
# el binary se descarga manualmente con `python -m camoufox fetch`.
# El código en repuve_live.py auto-detecta y hace fallback en runtime.
# RUN python -m camoufox fetch

EXPOSE 3009

# Healthcheck para que Docker / orchestrador detecte si el backend
# responde. /health no requiere auth ni DB.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -f http://localhost:3009/health || exit 1

# Boot script: alembic upgrade head + uvicorn. Si la migración falla,
# el container exits y el orchestrador re-intenta (mismo behavior que
# Render).
CMD alembic upgrade head && \
    uvicorn app.main:app --host 0.0.0.0 --port 3009
