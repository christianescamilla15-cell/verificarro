# Verificarro — Guía de deploy a producción

Pasos para llevar Verificarro de código local a `verificarro.mx` en
vivo. Tiempo estimado: **1.5–2h** la primera vez, después cada cambio
es auto-deploy.

## Stack final

| Componente | Servicio | Costo/mes |
|------------|----------|-----------|
| Backend (FastAPI) | Render Web Service Starter | $7 |
| Postgres | Render Postgres Starter | $7 |
| Frontend (React/Vite) | Vercel Hobby | $0 |
| Pagos | Mercado Pago (3.49% + IVA por venta) | variable |
| Email | SendGrid Free (100 emails/día) o Resend Free (3000/mes) | $0 |
| Dominio | NIC México `.mx` | ~$300/año |
| **Fijo** | | **$14/mes + dominio** |

Break-even: ~30 ventas básicas/mes ($49 × 30 = $1,470 MXN ≈ $80 USD).

---

## Paso 1 — GitHub repo

1. Ve a [github.com/new](https://github.com/new) (logueado como
   `christianescamilla15-cell`).
2. Repo name: `verificarro`. **Privado**. Sin README/gitignore (ya
   están en local).
3. Desde tu Git Bash en `c:/.../09-verificarro/`:
   ```bash
   git remote add origin git@github.com:christianescamilla15-cell/verificarro.git
   # o https si no tienes SSH:
   # git remote add origin https://github.com/christianescamilla15-cell/verificarro.git
   git branch -M main
   git push -u origin main
   ```

> **Importante**: el repo debe quedar privado. El `.gitignore` ya
> excluye `.env`, `*.db`, `seeds/output/` y demás. Si por error
> commiteas un secret, [rotálo inmediatamente](https://docs.github.com/code-security/secret-scanning/about-secret-scanning).

---

## Paso 2 — Render (backend + Postgres)

### 2.1 Crear cuenta y conectar GitHub

1. [render.com](https://render.com) → Sign up con GitHub.
2. Authorize Render para leer el repo `verificarro`.

### 2.2 Deploy via Blueprint

1. Dashboard → **New +** → **Blueprint**.
2. Selecciona el repo `verificarro`.
3. Render detecta `render.yaml` y muestra los recursos a crear:
   - `verificarro-db` (Postgres Starter, $7/mo)
   - `verificarro-api` (Web Service Starter, $7/mo)
4. Click **Apply**.

### 2.3 Setear secrets

Mientras el primer build corre (~5 min), ve al dashboard del Web
Service `verificarro-api` → **Environment** y configura los env vars
marcados como `sync: false` en `render.yaml`:

| Var | Valor |
|-----|-------|
| `ANTHROPIC_API_KEY` | tu key de Anthropic Console |
| `MP_ACCESS_TOKEN` | (paso 4) |
| `MP_PUBLIC_KEY` | (paso 4) |
| `MP_WEBHOOK_SECRET` | (paso 4, opcional) |
| `SMTP_HOST` | `smtp.sendgrid.net` (o Resend) |
| `SMTP_USER` | `apikey` (literal, así lo pide SendGrid) |
| `SMTP_PASSWORD` | tu API key de SendGrid |

Después de cada cambio, Render reinicia el servicio automáticamente.

### 2.4 Verifica health

Cuando el deploy esté en verde:
```
curl https://verificarro-api.onrender.com/health
# {"status":"ok","version":"0.1.0","service":"verificarro"}
```

> **Build OOM en Starter**: si Render falla con OOM al instalar
> Playwright + Chromium, sube a **Standard** ($25/mo) por una sola
> build, vuelve a Starter después. O quita `playwright install` del
> build y muévelo a un endpoint admin separado.

---

## Paso 3 — Vercel (frontend)

### 3.1 Crear proyecto

1. [vercel.com/new](https://vercel.com/new) → Import Git Repository
   → selecciona `verificarro`.
2. **Framework Preset**: Vite (debería auto-detectar).
3. **Root Directory**: `frontend`.
4. **Build Command**: `npm run build` (default).
5. **Output Directory**: `dist` (default).

### 3.2 Environment Variables

Antes de hacer deploy, agrega:

| Var | Valor |
|-----|-------|
| `VITE_API_BASE` | `https://verificarro-api.onrender.com` |

(Sin trailing slash; el frontend concatena los paths.)

### 3.3 Deploy

Click **Deploy**. Tras 1–2 min tendrás `verificarro.vercel.app` en
vivo. Ya en este punto puedes navegar a la landing y ver la home.

### 3.4 Actualiza CORS_ORIGINS en Render

Ve al dashboard de `verificarro-api` → Environment → edita
`CORS_ORIGINS`:

```
https://verificarro.vercel.app,https://verificarro.mx,https://www.verificarro.mx
```

(Quita el último si todavía no compras el dominio.)

---

## Paso 4 — Mercado Pago

### 4.1 Cuenta vendedor

1. [mercadopago.com.mx](https://www.mercadopago.com.mx) → Crear cuenta
   con tu RFC o como persona física.
2. Habilita **Modo desarrollador** (opcional pero recomendado para
   sandbox primero).

### 4.2 Credentials sandbox

1. Ve a [mercadopago.com.mx/developers/panel/credentials](https://www.mercadopago.com.mx/developers/panel/credentials).
2. Selecciona **Test credentials**.
3. Copia:
   - `Public Key` → `MP_PUBLIC_KEY`
   - `Access Token` (empieza con `TEST-`) → `MP_ACCESS_TOKEN`
4. Pégalos en Render dashboard → `verificarro-api` → Environment.

### 4.3 Webhook

1. En el panel MP → **Webhooks** → **Configurar notificaciones**.
2. URL: `https://verificarro-api.onrender.com/api/payments/webhook`
3. Eventos: marca **Pagos** (payment).
4. Guarda la **Secret signature** que MP te muestra → `MP_WEBHOOK_SECRET`
   (en código todavía no validamos firma, pero la guardamos para D9.5+).

### 4.4 Smoke test sandbox

1. Visita tu landing en `verificarro.vercel.app`.
2. Pega una URL de ML Motors + tier basic.
3. En el checkout MP usa una de las **tarjetas de prueba**:
   - Visa: `4509 9535 6623 3704`
   - CVV: `123`, vencimiento: cualquier fecha futura
   - Nombre: `APRO` (aprueba) o `OTHE` (rechaza)
4. Tras el pago, MP te redirige a `/checkout/success` con el polling.
5. Revisa los logs de Render — debería aparecer:
   ```
   Payment <id> confirmado — generación de reporte encolada
   Corriendo pipeline para payment <id>
   Reporte <id> generado para payment <id>
   ```
6. El frontend muestra el reporte completo.

### 4.5 Production credentials

Cuando estés listo para cobrar de verdad:

1. Mismo panel MP → **Production credentials**.
2. Reemplaza `MP_ACCESS_TOKEN` y `MP_PUBLIC_KEY` en Render con los
   valores de producción (empiezan con `APP_USR-`).
3. Render reinicia el servicio. Listo.

---

## Paso 5 — Dominio (opcional para MVP)

### 5.1 Comprar `verificarro.mx`

1. [nic.mx](https://www.nic.mx) → busca disponibilidad.
2. Costo: ~$300 MXN/año, paga con tarjeta o transferencia.
3. Tras la compra, ve a **Mis dominios** → Verificarro → **DNS**.

### 5.2 Apuntar al frontend (Vercel)

En el panel DNS de NIC México agrega:

| Tipo | Nombre | Valor |
|------|--------|-------|
| A | `@` | `76.76.21.21` (IP estable de Vercel) |
| CNAME | `www` | `cname.vercel-dns.com` |

En Vercel dashboard → `verificarro` → Settings → Domains → agrega
`verificarro.mx` y `www.verificarro.mx`. Vercel valida los DNS y
emite cert SSL automático.

### 5.3 Backend en `api.verificarro.mx` (opcional)

Si quieres `api.verificarro.mx` en lugar de `*.onrender.com`:

| Tipo | Nombre | Valor |
|------|--------|-------|
| CNAME | `api` | `verificarro-api.onrender.com` |

En Render → `verificarro-api` → Settings → Custom Domains → agrega
`api.verificarro.mx`. Actualiza `VITE_API_BASE` en Vercel y el
`CORS_ORIGINS` en Render.

### 5.4 Update Magic Link URL

Cuando el dominio esté listo, en Render edita
`MAGIC_LINK_BASE_URL=https://verificarro.mx/auth/verify`. Idem
para `MP_SUCCESS_URL`, `MP_FAILURE_URL`, `MP_PENDING_URL`.

---

## Paso 6 — Email (SendGrid o Resend)

### Opción A: SendGrid (más establecida)

1. [sendgrid.com](https://sendgrid.com) → Free tier (100 emails/día).
2. **Settings** → **API Keys** → **Create API Key** → "Full Access".
3. Copia el API key (solo se muestra una vez).
4. En Render env vars:
   - `SMTP_HOST=smtp.sendgrid.net`
   - `SMTP_PORT=587`
   - `SMTP_USER=apikey` (literal)
   - `SMTP_PASSWORD=<tu API key>`
5. **Sender Authentication** → verifica el dominio o al menos un
   sender verificado (`hola@verificarro.mx`).

### Opción B: Resend (más moderno, mejor DX)

1. [resend.com](https://resend.com) → Free tier (3000 emails/mes).
2. **API Keys** → genera una key.
3. En Render:
   - `SMTP_HOST=smtp.resend.com`
   - `SMTP_PORT=465`
   - `SMTP_USER=resend`
   - `SMTP_PASSWORD=<tu API key>`

> **Tip MVP**: si todavía no quieres configurar email, deja
> `SMTP_HOST` vacío. El código degrada a stdout — el "email" aparece
> en los logs de Render. Útil para los primeros días mientras
> validas el flow.

---

## Paso 7 — Smoke test end-to-end

Checklist completo:

- [ ] `curl https://verificarro-api.onrender.com/health` → 200 OK
- [ ] Landing carga en `verificarro.vercel.app` (o `verificarro.mx`)
- [ ] Login con email → recibes magic link en email (o lo ves en
      logs de Render si SMTP no configurado)
- [ ] Click en link → te loguea, ves tu email en el header
- [ ] Pegas URL de ML Motors → click "Verificar este auto" → te
      redirige a Mercado Pago
- [ ] Pagas con tarjeta de prueba → MP te regresa a
      `/checkout/success?external_reference=...`
- [ ] Polling muestra "Confirmando pago…" → "Generando reporte…"
- [ ] Aparece el reporte completo: score chip, summary, KV tables,
      findings
- [ ] Click "Descargar PDF" → descarga `verificarro-<año>-<score>.pdf`
- [ ] Click "Escanear VIN" → cámara abre (en dispositivo móvil) →
      capturas foto → recibes resultado VIN
- [ ] Logs de Render no muestran errores

---

## Operaciones del día a día

### Auto-deploy

Cualquier push a `main` dispara deploys nuevos:
- **Render**: rebuild backend + corre `alembic upgrade head` + restart.
- **Vercel**: rebuild frontend + atomic swap.

Si introduces una migration de DB nueva, push y Render la aplica
sola. Si rompe (typo, constraint imposible), el deploy queda en
**failed** y el servicio sigue corriendo la versión anterior.

### Logs

- Render → `verificarro-api` → **Logs** (stream en vivo).
- Vercel → `verificarro` → **Deployments** → último → **Function Logs**
  (no aplica para Vite SPA — sería server functions; aquí solo
  estáticos).

### Rollback

- Render: dashboard → **Deploys** → encuentra el último verde →
  **Rollback**.
- Vercel: dashboard → **Deployments** → click en uno anterior →
  **Promote to Production**.

### Variables sensitivas

NUNCA commitees:
- `ANTHROPIC_API_KEY`, `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`,
  `SMTP_PASSWORD`, `JWT_SECRET`.

Si por error commiteas alguno: rótalo inmediatamente en su servicio
y haz `git push --force` solo si el commit no se ha distribuido
(arriesgado en repo con colaboradores).

---

## Troubleshooting

### "Pago confirmado en MP pero el reporte nunca llega"

Causa típica: backend no recibió el webhook (Render dormido tras
inactividad — Starter duerme tras 15min sin tráfico).

Fix:
- **Mantener despierto**: agregar [cron job de UptimeRobot](https://uptimerobot.com)
  haciendo `GET /health` cada 5min ($0).
- **O subir a Standard** ($25/mo, no duerme).

Mientras tanto, MP reintenta el webhook hasta 5 veces. Si el primer
intento fue mientras Render dormía, los siguientes deberían
disparar la generación.

### "ALTER TABLE ya existe" o "duplicate index"

Causa: migration corrió 2 veces o el schema fue creado con
`Base.metadata.create_all()` antes que con Alembic.

Fix: en Render shell:
```bash
alembic stamp head  # marca la DB como ya migrada al estado actual
```

### "VIN scanner no funciona en mi celular"

- Browser necesita HTTPS para `getUserMedia`. Vercel siempre da
  HTTPS, así que esto solo aplica si pruebas en LAN local.
- iOS Safari pide permiso explícito. Si el usuario lo niega, el
  scanner cae al modo manual.
- Algunas versiones viejas de Android/Chrome no soportan
  `facingMode: 'environment'` — usan cámara frontal por default.
  El crop guide visual sigue funcionando.

### "Mercado Pago dice 'cuenta no apta para recibir pagos'"

Tu cuenta MP necesita estar verificada (RFC + CURP + datos
bancarios). En MX esto puede tardar 24-48h tras la primera carga
de docs.

---

## Costos por reporte (recordatorio)

| Componente | USD |
|------------|-----|
| ML scrape | $0.001 |
| Comparables ML | $0.005 |
| Photo analysis (6 fotos × Claude Sonnet visión) | $0.030 |
| VIN OCR (1 escaneo, opcional) | $0.005 |
| **Total** | **~$0.04 USD = ~$0.73 MXN** |

Comisión MP: 3.49% + IVA = ~$2.00 MXN sobre $49 MXN. Margen neto
por reporte: **~$46 MXN ≈ 94%**.

Cache hit: 2do comprador del mismo anuncio en 24h cuesta solo
~$0.001 (CPU del lookup en DB). Comisión MP igual.

---

## Próximos pasos post-deploy

1. **Monitor analytics**: Vercel + Render dan métricas básicas. Para
   conversión por sub de Reddit, agrega Plausible o Umami (~$5/mo).
2. **Backups Postgres**: Render Starter tiene point-in-time restore
   automático 7 días. Para más historial, agendar un job
   `pg_dump` semanal a S3 manual.
3. **2Captcha para REPUVE auto**: cuando el volumen justifique
   (~5,000 reportes/mes), integrar.
4. **Dominio + email pro**: cuando facturas, mover SMTP a tu propio
   dominio (`hola@verificarro.mx` con SendGrid sender verificado).
