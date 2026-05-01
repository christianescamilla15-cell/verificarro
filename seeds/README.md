# Verificarro — Seed reports para Reddit

Esta carpeta tiene la maquinaria para generar reportes seed que vamos a
usar en threads de Reddit (r/mexico, r/Cdmx, r/Monterrey, r/MexicoFinanciero).

## Estructura

```
seeds/
├── README.md             ← este archivo
├── urls.txt              ← lista de URLs ML Motors a procesar
├── templates/
│   ├── green.md          ← thread para reportes con score ≥70
│   ├── yellow.md         ← reportes con banderas medias
│   └── red.md            ← reportes con banderas graves
└── output/               ← reportes generados (gitignored)
    └── MLM<id>-<slug>/
        ├── report.json   ← Report completo (Pydantic)
        ├── report.pdf    ← PDF descargable
        └── reddit_thread.md  ← borrador listo para copiar a Reddit
```

## Generar reportes

Desde el backend con la venv activada:

```bash
cd backend
source .venv/Scripts/activate

# 1) Pasa URLs como args (rápido para 1-2):
python scripts/seed_reports.py \
    https://auto.mercadolibre.com.mx/MLM-2899141087-kia-seltos-15-sx-at-_JM

# 2) O con un archivo de URLs (recomendado para batch):
python scripts/seed_reports.py --file ../seeds/urls.txt
```

Cada URL genera:
- `output/<slug>/report.json` (4-15 KB)
- `output/<slug>/report.pdf` (4-8 KB)
- `output/<slug>/reddit_thread.md` (borrador con tono mexicano)

Tiempo: ~30s por URL (scraping ML + ML search comparables + Claude
visión si hay API key + scoring).

## Costos

Si `ANTHROPIC_API_KEY` está exportada:
- ~$0.04 USD por reporte (mayoría es Claude visión sobre fotos)
- 5 reportes ≈ $0.20 USD = ~$3.70 MXN

Sin API key: $0 (graceful degradation, `photo_findings` queda vacío).

## Cómo elegir las 5 URLs

Mix recomendado para conversión orgánica en Reddit:

1. **1 limpio** (score ≥80, green): auto serio de concesionario.
   Genera credibilidad — "no todos son estafas, esta herramienta también
   te dice cuando SÍ está bien".

2. **2 amarillos** (score 40-69): anuncios con banderas medias.
   Genera engagement — "¿ustedes le entrarían?".

3. **2 rojos** (score <40): sospechosos por precio (-30%) o descripción
   con seller_abroad / advance_payment_request. Estos son los que
   viralizan — la gente comparte por su utilidad pública.

### Búsqueda manual

```
https://listado.mercadolibre.com.mx/autos
→ Filtra por modelo popular: Civic, Sentra, Jetta, Aveo, Versa
→ Ordena por precio ASC para encontrar sospechosamente baratos
→ Ordena por precio DESC para concesionarios premium
→ Lee descripciones largas para cazar patrones de estafa
```

Toma la URL del card (formato `auto.mercadolibre.com.mx/MLM-...`) y
pégala en `urls.txt`.

## Cómo lanzar en Reddit

1. Genera el reporte con el script.
2. Lee `reddit_thread.md` y ajusta el tono si suena demasiado AI-generated.
   Christian conoce mejor los sub. Especialmente:
   - Cambia palabras técnicas si suenan raras
   - Agrega 1-2 detalles personales ("estaba viendo carros para mi compa")
3. Copia el texto, abre Reddit con cuenta personal (no nueva).
4. Subreddits target ordenados por probabilidad de tracción:
   - **r/mexico** — más tráfico, más dispersión
   - **r/Cdmx** — autos urbanos, segmento alto
   - **r/Monterrey** — autos premium, gente con plata para auto usado
   - **r/MexicoFinanciero** — gente que valida antes de gastar
   - **r/AskMexico** — preguntas, mejor para amarillos ("¿le entrarían?")
5. Postea **uno por día** (Reddit penaliza spam multi-sub mismo día).
6. Si alguien comenta hostil ("eres bot", "publicidad encubierta"),
   responde con datos del reporte específico — no defiendas la
   herramienta, defiende el caso real.

## Templates

Los 3 templates en `templates/` son MARKDOWN con placeholders Python
`{var}`. El script `seed_reports.py` selecciona el template según
`risk_level`. Si quieres tunear el tono:

- Edita `templates/{green,yellow,red}.md`
- Re-corre el script para regenerar todos los `reddit_thread.md`

Variables disponibles:
- `{title}` — header del thread
- `{year}`, `{make}`, `{model}`, `{price_mxn}`, `{kilometers}`,
  `{location}`, `{source_url}`
- `{score}`, `{fair_price_mxn}`, `{delta_pct}`
- `{photo_summary}`, `{repuve_line}`, `{price_line}`, `{flags_block}`
- `{top_alert_count}` (solo en red.md)
