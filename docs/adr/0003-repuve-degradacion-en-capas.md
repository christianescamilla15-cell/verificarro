# ADR 0003 · REPUVE con degradación en capas, nunca bloqueante

- Estado: aceptada · Fecha: 2026-05-02 a 2026-05-14 (registrada el 2026-11-19 a partir del código)
- Código: `backend/app/scrapers/repuve.py`, `backend/app/scraper_main.py`, `backend/scraper-mx.Dockerfile`,
  `extension/`, `backend/app/api/repuve_{extension,screenshot,live}.py`,
  `backend/app/services/pipeline/_preview.py::run_repuve_preview`
- Commits: 86e1009 (sidecar), 07297f7 y 5baa9d5 (captura/PDF + OCR), 32cd3ba (captcha de audio en vivo)

## Contexto
REPUVE es un sitio público protegido por reCAPTCHA y un WAF que bloquea IPs de centros de datos fuera de
México. La telemetría propia (`scrape_telemetry`) midió tasas de éxito muy bajas desde Render (Oregón).
Esperar al scraper bloqueaba al usuario hasta 2 minutos para terminar igual en «captcha».

## Decisión
La consulta automática es una mejora, no un requisito. Se intenta en este orden y cada capa degrada a la
siguiente sin error para el usuario:

1. Scraper con navegador automatizado en la API o, si `REPUVE_SCRAPER_URL` está definido, en el sidecar
   `scraper-mx` con IP de México (token Bearer compartido). En el preview, con timeout de 8 s.
2. Extensión de Chrome: la consulta sale del navegador del propio usuario y el HTML se parsea en la API
   (`POST /api/repuve/extension-result`), sin duplicar el parser en JS.
3. Captura de pantalla o PDF del resultado oficial, leído con OCR de visión (`POST /api/repuve/screenshot`).
4. Captcha de audio resuelto por el usuario en vivo (`WS /api/repuve/live`) cuando REPUVE lo ofrece.

Si ninguna da resultado, el reporte queda con `queried=False` y el preview se topa en 50/amarillo
(ADR 0002); el resumen lo dice como paso pendiente, no como error.

## Alternativas
- Sólo resolvedores de captcha de terceros (2Captcha): costo por consulta y tasa baja con IP de centro de
  datos; queda como opción configurable (`CAPTCHA_SOLVER_API_KEY`).
- Bloquear el reporte hasta tener REPUVE: el usuario se va.

## Consecuencias
- Varias rutas de entrada para el mismo dato, todas normalizadas a `RepuveResult` por el mismo parser.
- Mantenimiento periódico cuando REPUVE cambia su página o su captcha.
- El robo detectado por cualquier capa es interruptor terminal: el reporte va a rojo (`scoring.py`).
