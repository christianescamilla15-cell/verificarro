# Arquitectura · Verificarro

Modelo C4: contexto → contenedores → componentes. Los diagramas son texto (Mermaid), se versionan con el
código y nombran módulos que existen en el repo (`backend/app/...`, `frontend/src/...`, `extension/...`).

## 1. Contexto

```mermaid
C4Context
  title Contexto · Verificarro
  Person(comprador, "Comprador de auto usado", "Escanea placa, VIN o factura, o pega el anuncio")
  System(verificarro, "Verificarro", "Reporte de riesgo 0-100 del auto: REPUVE, VIN, precio justo, fotos, vendedor y factura")
  System_Ext(repuve, "REPUVE (gob.mx)", "Registro público vehicular: robo y situación legal")
  System_Ext(nhtsa, "NHTSA vPIC", "Decodificación oficial del VIN")
  System_Ext(sat, "SAT · verificación de CFDI", "Vigencia de la factura del auto")
  System_Ext(market, "Marketplaces", "Mercado Libre Motors, Vivanuncios, Seminuevos")
  System_Ext(claude, "API de Claude", "Visión: OCR de placa/VIN/CFDI, fotos; clasificación previa")
  System_Ext(mp, "Mercado Pago", "Cobro único y suscripciones; webhooks firmados")
  System_Ext(smtp, "Correo SMTP", "Enlace mágico y reporte en PDF")
  Rel(comprador, verificarro, "Usa", "HTTPS")
  Rel(verificarro, repuve, "Consulta placa/NIV", "HTTPS (navegador automatizado)")
  Rel(verificarro, nhtsa, "Decodifica VIN", "HTTPS/JSON")
  Rel(verificarro, sat, "Verifica CFDI", "SOAP")
  Rel(verificarro, market, "Lee anuncio y comparables", "HTTPS")
  Rel(verificarro, claude, "Analiza imágenes", "HTTPS")
  Rel(verificarro, mp, "Crea cobros / recibe webhooks", "HTTPS")
  Rel(verificarro, smtp, "Envía correos", "SMTP")
```

## 2. Contenedores

```mermaid
C4Container
  title Contenedores · Verificarro
  Person(comprador, "Comprador")
  System_Boundary(b, "Verificarro") {
    Container(web, "Front", "React 19 + Vite 8 · Vercel", "Escáner de placa/VIN, preview, paywall, reporte, tablero")
    Container(ext, "Extensión de Chrome", "Manifest V3", "Consulta REPUVE desde el navegador del usuario y entrega el HTML")
    Container(api, "API", "Python 3.12 · FastAPI · Render (Docker)", "Pipeline de análisis, pagos, auth por enlace mágico")
    Container(sidecar, "scraper-mx", "FastAPI · Docker en host con IP de México", "Sólo POST /scrape/repuve con token Bearer")
    ContainerDb(bd, "PostgreSQL", "Render Postgres", "users, payments (PII cifrada), reports, photo_hashes")
    ContainerDb(tele, "Telemetría de scraping", "SQLite local", "Intentos REPUVE por técnica y etapa")
  }
  System_Ext(repuve, "REPUVE")
  System_Ext(mp, "Mercado Pago")
  System_Ext(claude, "API de Claude")
  Rel(comprador, web, "Usa", "HTTPS")
  Rel(web, api, "Llama", "JSON/HTTPS + WebSocket (captcha de audio)")
  Rel(web, ext, "Handshake y encargo", "window.postMessage")
  Rel(ext, repuve, "Llena el formulario", "pestaña del usuario")
  Rel(ext, api, "POST /api/repuve/extension-result", "HTTPS")
  Rel(api, sidecar, "Delegar REPUVE si REPUVE_SCRAPER_URL", "HTTPS + Bearer")
  Rel(sidecar, repuve, "Consulta", "Playwright")
  Rel(api, repuve, "Consulta directa (respaldo)", "Playwright")
  Rel(api, bd, "Lee y escribe", "SQLAlchemy async")
  Rel(api, tele, "Registra intentos", "sqlite3")
  Rel(api, claude, "Visión", "HTTPS")
  Rel(mp, api, "Webhook payment/preapproval", "HTTPS + HMAC")
```

## 3. Componentes de la API (`backend/app`)

```mermaid
C4Component
  title Componentes · API
  Container_Boundary(api, "API FastAPI") {
    Component(routers, "Routers", "app/api/*", "scan, analyze, payments, auth, repuve_{extension,screenshot,live}, health")
    Component(orq, "Orquestador del pipeline", "app/services/pipeline/orchestrator.py", "run_preview_pipeline (sólo REPUVE) y run_pipeline (completo)")
    Component(steps, "Pasos del pipeline", "app/services/pipeline/steps.py, invoice.py, _preview.py", "REPUVE con timeout, precio, fotos, EXIF, cruces, factura + SAT")
    Component(anal, "Analizadores puros", "app/analyzers/*", "vin_decoder, vin_check, scoring, description, seller, invoice_validator, price_estimator, exif, photo")
    Component(scr, "Scrapers", "app/scrapers/*", "mercadolibre, ml_search, multi_marketplace, repuve (+ stealth)")
    Component(ocr, "Escáner inteligente", "app/services/smart_scanner.py, plate_ocr, vin_ocr, repuve_screenshot_ocr", "Clasifica la imagen y extrae placa/VIN/CFDI con Claude")
    Component(pagos, "Pagos", "app/api/payments.py + app/services/mercadopago.py", "Checkout, suscripciones, webhook HMAC, máquina de estados del pago")
    Component(gen, "Generador de reportes", "app/services/report_generator.py", "Desbloqueo preview → unlocked, caché 24 h, recuperación de huérfanos, PDF y correo")
    Component(seg, "Seguridad transversal", "rate_limit.py, services/crypto.py, services/auth.py, photo_fetcher.py", "Límites por IP, PII con Fernet, JWT/enlace mágico, anti-SSRF")
  }
  ContainerDb(bd, "PostgreSQL")
  Rel(routers, orq, "Invoca")
  Rel(orq, steps, "Compone en paralelo")
  Rel(steps, scr, "Usa")
  Rel(orq, anal, "Puntúa y compara")
  Rel(routers, ocr, "Imágenes")
  Rel(routers, pagos, "Checkout / webhook")
  Rel(pagos, gen, "Encola al pasar a paid")
  Rel(gen, orq, "run_pipeline")
  Rel(gen, bd, "ReportRecord")
  Rel(pagos, bd, "Payment")
```

## 4. Estados

Pago único (webhook `topic=payment`, `app/db/models/payment.py::PAYMENT_TRANSITIONS`). Cualquier otra
transición se ignora con 200 (`invalid-transition`) para que Mercado Pago no reintente:

```mermaid
stateDiagram-v2
  [*] --> pending: checkout
  pending --> paid: approved
  pending --> failed: rejected / cancelled
  pending --> refunded: refunded / charged_back
  failed --> pending: reintento (ficha OXXO)
  failed --> paid: reintento aprobado
  paid --> refunded: reembolso / contracargo
  refunded --> [*]
```

Suscripción (`topic=preapproval`, `SUBSCRIPTION_TRANSITIONS`): `pending → paid (authorized) | failed
(cancelled)`, `paid → pending (paused) | failed (cancelled)`; `failed` es terminal.

Reporte (`app/db/models/report.py::ReportStatus`): `preview` (gratis, sólo REPUVE) → `unlocked` (pipeline
completo) cuando el pago está en `paid`; `unlocked` no vuelve a correr el pipeline. Ver ADR 0002.

## 5. Despliegue

| Pieza | Dónde | Cómo se publica |
|---|---|---|
| API | Render, servicio web `verificarro-api` (Docker, `backend/Dockerfile`) | `render.yaml` (Blueprint) con `autoDeploy` en cada push a la rama conectada |
| PostgreSQL | Render, `verificarro-db` | Blueprint; migraciones `alembic upgrade head` al arrancar el contenedor |
| Front | Vercel, raíz `frontend/` (`vercel.json`) | Integración Git de Vercel; también `vercel --prod` manual |
| scraper-mx | VPS con IP de México (`backend/scraper-mx.Dockerfile`) | `docker run` manual; opcional |
| Extensión | Chrome (carga sin empaquetar) | Manual; no publicada en la tienda |

Detalle operativo y reversa en [`RUNBOOK.md`](../../RUNBOOK.md).
