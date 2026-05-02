# Verificarro backend Dockerfile
#
# Image base: python:3.12-slim — ligera (~120 MB), tiene libc + ssl.
# Si tests fallan por playwright en CI, considerar python:3.12 (full).
#
# Build: docker build -t verificarro-backend .
# Run:   docker run -p 3009:3009 --env-file .env verificarro-backend

FROM python:3.12-slim AS runtime

WORKDIR /app

# System deps mínimos:
# - libpq5 para asyncpg (Postgres driver requiere libpq runtime)
# - curl para healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar Python deps primero (mejor cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la app
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Crear non-root user
RUN useradd -m -u 1000 verificarro && chown -R verificarro:verificarro /app
USER verificarro

EXPOSE 3009

# Healthcheck para que Docker / orchestrador detecte si el backend
# responde. /health no requiere auth ni DB.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -f http://localhost:3009/health || exit 1

# Boot script: alembic upgrade head + uvicorn. Si la migración falla,
# el container exits y el orchestrador re-intenta (mismo behavior que
# Render).
CMD alembic upgrade head && \
    uvicorn app.main:app --host 0.0.0.0 --port 3009
