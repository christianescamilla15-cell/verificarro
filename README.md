# Verificarro

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

## Quick start (development)

### Pre-requisitos

- Python 3.12+
- Node 20+
- Docker (opcional, recomendado para Postgres local)
- Cuenta MP Developer (TEST credentials)

### Setup backend

```bash
cd backend
cp .env.example .env
# Editar .env con tus credenciales (al menos ANTHROPIC_API_KEY y MP_ACCESS_TOKEN TEST)

python -m venv .venv
.venv/Scripts/activate    # Windows
# source .venv/bin/activate  # Mac/Linux

pip install -r requirements.txt
alembic upgrade head

uvicorn app.main:app --reload --port 3009
# → http://localhost:3009/docs (FastAPI auto docs)
```

### Setup frontend

```bash
cd frontend
cp .env.example .env.local
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

## Tests

```bash
# Backend (~491 tests, ~45s)
cd backend && .venv/Scripts/python.exe -m pytest --tb=line -q

# Frontend (no tests JS configurados aún — vitest pendiente)
cd frontend && npx vite build  # solo build smoke
```

## Deploy

- **Backend**: auto-deploy de Render en cada push a `master`
- **Frontend**: manual `cd frontend && vercel --prod`

CI/CD GitHub Actions corre `pytest` + `vite build` en cada PR + push a master.
Branch protection en `master` requiere ambos checks verde antes de merge.

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

## License

Propietario · Christian Hernández Escamilla · 2026
