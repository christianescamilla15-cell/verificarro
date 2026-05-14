# Verificarro backend Dockerfile
#
# Base: imagen oficial de Microsoft Playwright para Python. Trae:
# - Python 3.12
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
# Versión pinned a Playwright 1.48 para matchear requirements.txt.
# Si bumpeas Playwright, actualizá el tag aquí también.
#
# Build: docker build -t verificarro-backend .
# Run:   docker run -p 3009:3009 --env-file .env verificarro-backend

FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy AS runtime

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

# Fetch Camoufox Firefox custom (~530 MB binary + 65 MB GeoIP DB +
# uBlock addon). Activa el path USE_CAMOUFOX y el live audio captcha
# endpoint /api/repuve/live con stealth a nivel C++ (mucho mejor que
# stock Playwright para que Google muestre captcha challenge UI).
#
# IMPORTANTE: corre como pwuser para que el binary quede en su
# home dir y sea accesible al runtime sin permission issues.
# Build time adicional: ~30-60s primera vez (después cached por Docker).
# Runtime RAM extra: ~200 MB cuando AsyncCamoufox arranca (Render
# Starter 512 MB RAM puede llegar al límite con Chromium + Firefox
# simultáneos — monitorear OOM, upgrade a Standard si pasa).
RUN python -m camoufox fetch

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
