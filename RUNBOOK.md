# Runbook · Verificarro

Despliegue real a la fecha (2026-11-19). La guía de alta inicial, paso a paso, está en [`DEPLOY.md`](DEPLOY.md);
la arquitectura de despliegue, en [`docs/arquitectura/README.md`](docs/arquitectura/README.md#5-despliegue).

| Pieza | Plataforma | Recurso | Disparador |
|---|---|---|---|
| API FastAPI | Render · Docker (`backend/Dockerfile`, imagen base de Playwright) | servicio web `verificarro-api` (Oregón, plan Starter), `healthCheckPath: /health` | `autoDeploy: true` en `render.yaml`: cada push a la rama conectada (`master`) |
| PostgreSQL | Render | `verificarro-db` (`basic_256mb`) | Blueprint; las migraciones corren al arrancar el contenedor (`alembic upgrade head && uvicorn ...`) |
| Front | Vercel · Vite (`frontend/vercel.json`, Root Directory `frontend`) | proyecto `verificarro` (verificarro.vercel.app, verificarro.mx) | Integración Git de Vercel en cada push; respaldo manual `cd frontend && vercel --prod` |
| scraper-mx (opcional) | VPS con IP de México · Docker (`backend/scraper-mx.Dockerfile`) | contenedor `verificarro-scraper-mx`, puerto 8080 | Manual (`docker build` + `docker run`, comandos en el encabezado del Dockerfile) |

Variables: las sensibles (`ANTHROPIC_API_KEY`, `MP_*`, `SMTP_*`, `FERNET_KEY`, `REPUVE_SCRAPER_TOKEN`) se cargan
a mano en el panel de Render (`sync: false`); `JWT_SECRET` la genera Render. En Vercel, `VITE_API_BASE`.

## Desplegar

1. Todo cambio entra por PR a `master` con los checks en verde: `ci` (pruebas backend, front) y `seguridad`
   (confidencialidad, gitleaks, CodeQL, Semgrep, Trivy, SBOM).
2. Al fusionar, Render construye la imagen y la publica sólo si `/health` responde; Vercel publica el front.
3. Prueba de humo contra producción (debe salir con 0):

   ```bash
   herramientas/humo.sh https://verificarro-api.onrender.com https://verificarro.mx
   ```

   Revisa `/health` (status y versión), `/api/config`, que `/api/auth/me` sin token dé 401 (contesta la app,
   no un proxy), y que el front sirva la SPA con sus rutas reescritas.
4. Si cambió el esquema: confirma en los logs de Render la línea `Running upgrade ... -> <revisión>`.

**Pendiente (N09):** hoy Render despliega con cada push sin esperar al CI. Conviene cambiar el disparador
del servicio a «después de que pasen los checks» (en el panel o en `render.yaml`) y proteger `master` con
los checks requeridos; no se cambió en esta rama porque altera producción y necesita OK del dueño.

## Revertir (no ensayado todavía)

1. **API:** Render → `verificarro-api` → *Events/Deploys* → último despliegue verde → **Rollback**.
2. **Front:** Vercel → `verificarro` → *Deployments* → despliegue anterior → **Instant Rollback** /
   *Promote to Production*.
3. **Base de datos:** el rollback de Render NO revierte migraciones. Si la versión anterior no es compatible
   con el esquema nuevo: Render → *Shell* → `alembic downgrade -1` (las migraciones del repo traen
   `downgrade`; la de cifrado de PII descifra al bajar). Antes, respaldo: `pg_dump` desde la cadena de
   conexión externa de `verificarro-db`.
4. `herramientas/humo.sh` sobre la versión restaurada.

El ensayo de la reversa (fecha y evidencia) queda pendiente: requiere acceso a los paneles de Render y Vercel.

## Diagnóstico

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El contenedor no arranca: `ValueError: JWT_SECRET ...`, `FERNET_KEY no está set` o `MP_WEBHOOK_SECRET` | Falta un secreto de producción (regla P9 de `docs/reglas.md`) | Cargar la variable en Render; el servicio reinicia solo |
| Pago aprobado en MP pero el reporte no llega | Render Starter dormido cuando llegó el webhook, o reinicio a mitad del pipeline | MP reintenta el webhook; al arrancar, `recover_orphan_paid_payments` re-encola los pagos de los últimos 30 min. Mantener `/health` vigilado (UptimeRobot) |
| Log `transición inválida paid → pending` | Webhook atrasado de otro intento del mismo checkout (p. ej. ficha OXXO) | Esperado: se ignora con 200. No tocar el pago |
| Log `rechazado por amount mismatch` | El monto reportado por MP no es el cobrado (posible fraude) | No acreditar a mano; revisar el pago en el panel de MP |
| `401 Webhook signature inválida` en todos los webhooks | `MP_WEBHOOK_SECRET` distinto al del panel de MP | Copiar de nuevo la clave secreta del webhook a Render |
| Preview siempre «Verificación REPUVE pendiente» | REPUVE pidió captcha o bloqueó la IP (esperado desde Render) | Flujo manual (captura/PDF) o configurar el sidecar `REPUVE_SCRAPER_URL` + `REPUVE_SCRAPER_TOKEN` |
| Log `Playwright Chromium NO encontrado` | La imagen no trae el navegador de la versión fijada | Se instala solo en segundo plano (salvo `PLAYWRIGHT_AUTO_INSTALL=false`); si persiste, reconstruir la imagen |
| `alembic` falla con «ya existe» / índice duplicado | El esquema se creó fuera de Alembic | Render → Shell → `alembic stamp head` |
| El front muestra errores de CORS | `CORS_ORIGINS` sin el dominio del front | Agregar el dominio en Render |

Observabilidad: logs en vivo en Render; errores en Sentry si `SENTRY_DSN` está definido; Vercel Analytics y
Speed Insights en el front; `/health` vigilado por UptimeRobot.
