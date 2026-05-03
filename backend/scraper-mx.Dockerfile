# Verificarro scraper-mx sidecar Dockerfile
#
# Microservice independiente del backend principal. Misma imagen base
# (Playwright con Chromium pre-baked), mismo código (reusa
# app/scrapers/repuve.py y app/services/captcha_solver.py), pero
# entrypoint diferente (app/scraper_main.py).
#
# El propósito: deployar este contenedor en un host con IP mexicana
# (Vultr CDMX, Hostinger MX, etc.) para evitar el WAF de gob.mx que
# bloquea IPs no-mexicanas. El backend principal (Render Oregon) le
# llama via HTTP cuando REPUVE_SCRAPER_URL está set.
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

FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy AS runtime

WORKDIR /app

# System deps: solo curl para healthcheck (Postgres NO necesario, este
# sidecar es stateless — no toca DB).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Solo las deps de Python que necesita el scraper. Subset del
# requirements.txt principal para imagen más liviana.
# httpx + playwright + cryptography vienen de aquí; agregar solo lo
# que el código del scraper realmente importa.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Re-confirmar Chromium (no-op si la imagen base ya lo tiene).
RUN playwright install chromium

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

# El user pwuser ya viene en la imagen base de Playwright.
RUN chown -R pwuser:pwuser /app
USER pwuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -f http://localhost:8080/health || exit 1

# Entrypoint distinto del backend principal — solo monta scraper_main
# (sin DB, sin auth de usuarios, sin payments).
CMD uvicorn app.scraper_main:app --host 0.0.0.0 --port 8080
