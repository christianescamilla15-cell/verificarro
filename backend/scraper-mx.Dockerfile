# Verificarro scraper-mx sidecar Dockerfile
#
# Microservice independiente del backend principal. Reusa código del
# backend (app/scrapers/repuve.py + captcha_solver) con entrypoint
# diferente (app/scraper_main.py).
#
# Base: python:3.12-slim porque el backend usa `datetime.UTC` (3.11+).
# Microsoft Playwright image v1.48 viene con Python 3.10 → ImportError.
# En Vultr/Hostinger corremos como root → `playwright install-deps`
# funciona sin sudo (a diferencia de Render Starter).
#
# Build:
#   docker build -f scraper-mx.Dockerfile -t verificarro-scraper-mx .
#
# Run (en host MX):
#   docker run -d \
#     --name verificarro-scraper-mx \
#     -p 8080:8080 \
#     -e REPUVE_SCRAPER_TOKEN="<token-compartido-con-backend>" \
#     -e CAPTCHA_SOLVER_API_KEY="<2captcha-key>" \
#     -e PLAYWRIGHT_HEADLESS=true \
#     -e SCRAPE_TIMEOUT_MS=30000 \
#     -e REPUVE_RATE_LIMIT_PER_SEC=1 \
#     --restart unless-stopped \
#     verificarro-scraper-mx
#
# Verificación:
#   curl http://localhost:8080/health
#   curl -X POST http://localhost:8080/scrape/repuve \
#     -H "Authorization: Bearer <token>" \
#     -H "Content-Type: application/json" \
#     -d '{"plate":"PHC9604"}'

FROM python:3.12-slim AS runtime

# Path system-wide para que Chromium quede accesible para todos los
# users (playwright_bootstrap también lo busca aquí en su lista de
# candidatos).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# System deps base: curl para healthcheck + las libs Linux para
# Chromium. `playwright install-deps` necesita corredor con permisos
# apt — corremos como root aquí (build time).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear non-root user temprano para chown selectivo después.
RUN useradd -m -u 1001 pwuser

# Subset de requirements del backend.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + libs Linux (~30 paquetes apt). PLAYWRIGHT_BROWSERS_PATH
# arriba hace que vaya a /ms-playwright en lugar de /root/.cache. Después
# chown para que pwuser tenga acceso.
RUN playwright install --with-deps chromium && \
    chown -R pwuser:pwuser /ms-playwright

# Copiar SOLO los módulos que el sidecar necesita. NO copiamos
# el resto del backend (api/, db/, services/ excepto los necesarios)
# para reducir surface area + tamaño de imagen.
COPY app/__init__.py ./app/__init__.py
COPY app/config.py ./app/config.py
COPY app/scraper_main.py ./app/scraper_main.py
COPY app/models/__init__.py ./app/models/__init__.py
COPY app/models/report.py ./app/models/report.py
COPY app/scrapers/ ./app/scrapers/
COPY app/services/__init__.py ./app/services/__init__.py
COPY app/services/captcha_solver.py ./app/services/captcha_solver.py
COPY app/services/playwright_bootstrap.py ./app/services/playwright_bootstrap.py

RUN chown -R pwuser:pwuser /app
USER pwuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -f http://localhost:8080/health || exit 1

# Entrypoint distinto del backend principal — solo monta scraper_main
# (sin DB, sin auth de usuarios, sin payments).
CMD uvicorn app.scraper_main:app --host 0.0.0.0 --port 8080
