# Verificarro

[![ci](https://github.com/christianescamilla15-cell/verificarro/actions/workflows/ci.yml/badge.svg)](https://github.com/christianescamilla15-cell/verificarro/actions/workflows/ci.yml)
[![seguridad](https://github.com/christianescamilla15-cell/verificarro/actions/workflows/seguridad.yml/badge.svg)](https://github.com/christianescamilla15-cell/verificarro/actions/workflows/seguridad.yml)
[![licencia: MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)

> Verificador de auto usado para Marketplace MX. Pega el anuncio o
> escanea la placa con tu cámara → reporte en 60s con score 0-100,
> REPUVE oficial, precio justo de mercado, análisis de fotos con IA,
> red flags del vendedor y preguntas para hacerle.

**Live**: [verificarro.mx](https://verificarro.mx) · [verificarro.vercel.app](https://verificarro.vercel.app)

---

## Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy 2 async + Alembic + Postgres
- **Frontend**: React 18 + Vite 5 + Radix Colors + React Router 7
- **AI**: Claude Sonnet 4.6 (visión OCR placa/VIN/CFDI)
- **Pagos**: Mercado Pago (Preference + Preapproval)
- **Email**: Resend SMTP
- **Hosting**: Render (backend) + Vercel (frontend)
- **Observability**: Sentry + UptimeRobot + Vercel Analytics

## Arquitectura

Front React (Vercel) → API FastAPI (Render, Docker) → PostgreSQL, con consultas a REPUVE, NHTSA vPIC, SAT,
marketplaces y visión de Claude; extensión de Chrome y sidecar `scraper-mx` como rutas alternas a REPUVE.

- C4 (contexto, contenedores, componentes) y estados: [`docs/arquitectura/README.md`](docs/arquitectura/README.md)
- Decisiones: [`docs/adr/`](docs/adr/) — scan-first con preview gratuito, REPUVE con degradación en capas,
  pruebas herméticas
- Reglas de negocio y la prueba que cubre cada una: [`docs/reglas.md`](docs/reglas.md)

## Quick start (development)

### Pre-requisitos

- Python 3.12+
- Node 20+
- Docker (opcional, recomendado para Postgres local)
- Cuenta MP Developer (TEST credentials)

### Setup backend

```bash
cd backend
cp env.example .env
# Editar .env con tus credenciales (al menos ANTHROPIC_API_KEY y MP_ACCESS_TOKEN TEST)

python -m venv .venv
.venv/Scripts/activate    # Windows
# source .venv/bin/activate  # Mac/Linux

pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head

uvicorn app.main:app --reload --port 3009
# → http://localhost:3009/docs (FastAPI auto docs)
```

### Setup frontend

```bash
cd frontend
cp env.example .env.local
npm install
npm run dev
# → http://localhost:5173
```

### Setup con Docker (alternativa)

```bash
docker compose up -d
# Levanta: backend (port 3009), Postgres (port 5432).
# Frontend correr aparte con `cd frontend && npm run dev`
```

## Pruebas

```bash
# Backend: 723 pruebas + 2 en vivo (omitidas salvo RUN_LIVE_REPUVE=1 / RUN_LIVE_ML=1), ~30 s, sin red
cd backend && python -m pytest -q --cov=app

# Frontend: vitest (46 pruebas) + build
cd frontend && npm run test:run && npm run build
```

La compuerta no es el % de cobertura (≈71 %) sino **una prueba por regla de negocio**: VIN e ISO 3779,
consultas a REPUVE/SAT/NHTSA, puntaje, máquinas de estado de pago y reporte (incluidas las transiciones
inválidas). La tabla vive en [`docs/reglas.md`](docs/reglas.md) y una prueba verifica que cada referencia
exista. Las pruebas no descargan navegadores ni salen a internet ([ADR 0004](docs/adr/0004-pruebas-hermeticas-sin-navegador.md)).

## Deploy

- **Backend**: auto-deploy de Render en cada push a `master`
- **Frontend**: manual `cd frontend && vercel --prod`

CI/CD GitHub Actions corre `ci` (pytest + vitest + build) y `seguridad` en cada PR y push a `master`.
Checks a marcar como requeridos al proteger `master`: los jobs de `ci.yml` y `seguridad.yml`.
Operación, prueba de humo (`herramientas/humo.sh`) y reversa: [`RUNBOOK.md`](RUNBOOK.md).

## Seguridad

CodeQL, Semgrep, Trivy (dependencias y Dockerfiles), gitleaks, SBOM y filtro de confidencialidad en cada
cambio; Dependabot semanal. Webhooks con HMAC y máquina de estados, PII cifrada, límites por IP y anti-SSRF.
Cómo reportar una vulnerabilidad y cómo se gestionan las excepciones: [`SECURITY.md`](SECURITY.md).

## Documentación interna

Para Christian + agentes Claude Code trabajando en el proyecto:

- `CLAUDE.md` — contexto público committed
- `.claude/agents/` — 8 agentes Claude Code invocables (Engineering,
  Design, Marketing, Finance, CS, Data, Legal, Orchestrator)
- `BACKUP_CHRIS/memoria-proyectos/verificarro/` — memoria local
  (NEVER PUSH) con credenciales, runbook, decisiones, pendientes

## Privacidad y términos

- [/privacidad](https://verificarro.mx/privacidad) — Aviso de Privacidad LFPDPPP
- [/terminos](https://verificarro.mx/terminos) — Términos y Condiciones

## Licencia

[MIT](LICENSE) · Christian Hernández Escamilla · 2026
