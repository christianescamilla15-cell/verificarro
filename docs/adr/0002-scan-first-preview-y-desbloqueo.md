# ADR 0002 · Scan-first: preview gratuito y desbloqueo por pago sobre el mismo registro

- Estado: aceptada · Fecha: 2026-05-01 (registrada el 2026-11-19 a partir del código)
- Código: `backend/app/api/scan.py`, `backend/app/services/pipeline/orchestrator.py::run_preview_pipeline`,
  `backend/app/services/report_generator.py::unlock_report_for_payment`, `backend/app/db/models/report.py`
- Commits: 5eec1ec, c8056fe, 5c131bc

## Contexto
El flujo original pedía pegar la URL del anuncio y pagar antes de ver nada. En Facebook Marketplace la URL
no sirve (requiere sesión) y el comprador no sabía qué compraba. La pieza más valiosa y barata es REPUVE
(robo y situación legal), que sólo necesita la placa.

## Decisión
- La entrada es la placa (foto o texto). `POST /api/scan/plate` corre un pipeline ligero que sólo consulta
  REPUVE y crea un `ReportRecord` con `status=preview` y puntaje visible.
- El checkout recibe ese `report_id`; cuando Mercado Pago confirma el pago, `unlock_report_for_payment`
  corre el pipeline completo y reescribe el MISMO registro a `status=unlocked`. La URL `/preview/{id}` no
  cambia.
- Sin respuesta de REPUVE el preview no puede ser verde: se topa en 50/amarillo para no dar falsa confianza.

## Alternativas
- Reporte nuevo al pagar: rompe la URL que el usuario ya tiene y duplica registros.
- Preview sin puntaje: menos conversión; el puntaje con REPUVE ya es útil por sí solo.

## Consecuencias
- El reporte tiene dos estados y una sola transición válida (`preview → unlocked`, sólo con pago en `paid`);
  `unlocked` es idempotente y no vuelve a gastar el análisis IA (`tests/test_estados.py`).
- El checkout rechaza (409) un reporte ya desbloqueado.
- La calidad del preview depende de REPUVE, que bloquea bots (ver ADR 0003).
