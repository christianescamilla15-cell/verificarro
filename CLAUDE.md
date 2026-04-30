# Verificarro — MVP

## Qué es
Verificador de auto usado para Mercado Libre Motors y Facebook Marketplace.
Pega URL del anuncio → reporte en 60s con score 0-100, validación REPUVE,
estimación de precio justo, análisis de fotos (visión IA), red flags del
vendedor y preguntas para hacerle.

Pago único $49 MXN básico / $99 MXN premium vía Mercado Pago (OXXO/SPEI/tarjeta).

## Mercado y GTM
- Audiencia: comprador de auto usado en MX (ticket de decisión $80-200K MXN)
- Canal: orgánico en r/mexico, r/Cdmx, r/Monterrey, r/MexicoFinanciero +
  comentarios en Marketplace mismo. Cero ads pagados al inicio.
- Hook: "pásalo por Verificarro antes de soltar el cash"

## Stack
- Backend: Python 3.12 + FastAPI + Playwright + Anthropic SDK
- Frontend: React 18 + Vite 5
- Visión IA: Claude Sonnet 4.6 (`claude-sonnet-4-6`) para análisis de fotos
- Scraping: Playwright (REPUVE público, ML Motors, Kavak/Seminuevos comparables)
- Pagos: Mercado Pago (Phase 2)
- DB: PostgreSQL (Phase 2 — D9+)
- Deploy: Render (backend) + Vercel (frontend)

## Pipeline de análisis
1. **Scrape del anuncio** → precio, marca/modelo/año, kms, ubicación, vendedor, fotos, descripción
2. **REPUVE** (placa/NIV) → estatus de robo + situación legal
3. **Estimador de precio justo** → comparar contra Kavak/Seminuevos
4. **Análisis de fotos con Claude visión** → inconsistencias de pintura, reparaciones, óxido
5. **Análisis de descripción** → red flags lingüísticos (urgencia, "estoy en el extranjero", no ver auto)
6. **Análisis del vendedor** → cuenta nueva, fotos repetidas en otros anuncios
7. **Score 0-100 + reporte PDF** con recomendaciones y preguntas para el vendedor

## Scope MVP (14 días)
**Semana 1 — Motor**
- D1 ✅: Scaffold backend + frontend
- D2: Scraper Mercado Libre Motors (Playwright)
- D3: Scraper REPUVE (gob.mx público)
- D4: Estimador de precio (Kavak/Seminuevos scrape)
- D5: Análisis de fotos con Claude visión
- D6: Análisis de descripción + vendedor
- D7: Pipeline de scoring + reporte PDF (reportlab)

**Semana 2 — Lanzamiento**
- D8-9: Mercado Pago + Postgres
- D10: Auth simple (magic link)
- D11: Landing
- D12: 5 reportes seed para Reddit
- D13: Lanzamiento r/mexico + r/Cdmx + r/Monterrey
- D14: Iterar

## Comandos
- `cd backend && uvicorn app.main:app --reload` — dev backend (puerto 3009)
- `cd backend && pytest` — tests
- `cd frontend && npm run dev` — dev frontend (puerto 5173)
- `cd frontend && npm run build` — build prod

## Convenciones
- Español para UI / mensajes al usuario / commits del producto
- Inglés para código (variables, funciones, módulos)
- Pydantic v2 para todos los modelos
- Type hints en todas las funciones
- Tono mexicano natural en copy del producto, sin spanglish forzado

## Reglas críticas
- NUNCA scrapear con cuenta personal (FB Marketplace requiere login → flujo
  manual: usuario pega texto + sube fotos)
- REPUVE: respetar throttle, info pública pero no abusar (1 req/seg max)
- Claude visión: ~$0.03 USD por reporte de 6 fotos. Cobrar mínimo 10x el costo.
- Cachear reportes por URL hash 24h (Redis cuando exista)
- Privacidad: no almacenar fotos del anuncio más allá de la sesión salvo
  consentimiento explícito (LFPDPPP)

## Costos económicos por reporte
- Claude Sonnet 4.6 visión: ~$0.05 USD
- REPUVE scraping: ~$0.001 USD
- Infra prorrateada: ~$0.01 USD
- **Total**: ~$0.06 USD = $1.10 MXN
- Precio: $49 MXN básico → ~95% margen bruto

## Riesgos conocidos
- **Facebook Marketplace** requiere login → flujo manual (URL no funciona)
- **REPUVE captcha** se actualiza cada tanto → mantenimiento periódico
- **ML Motors** puede agregar bot detection → headed Playwright + user-agent
  rotation si pasa
- **Reverse image search** caro → empezar con pHash propio sobre nuestra
  base, agregar TinEye solo si justificado por volumen
