"""Smoke en vivo del análisis de fotos con Claude Sonnet 4.6.

Toma 3 fotos del listing real que validamos en D2 (Kia Seltos en ML Motors)
y corre `analyze_photos`. Costo aproximado: 3 fotos × ~$0.005 USD = ~$0.015.

Para correr:
    export ANTHROPIC_API_KEY=sk-ant-...
    python smoke_photo.py

Si la key no está, el script termina con mensaje claro sin gastar créditos.
"""

import asyncio
import json
import os
import sys

from app.analyzers.photo_analyzer import analyze_photos


# 3 fotos reales del listing Kia Seltos validadas el 2026-04-30 contra el
# scraper de D2. Si ML quita el listing, hay que sustituir por nuevas URLs.
SAMPLE_PHOTOS = [
    "https://http2.mlstatic.com/D_NQ_NP_2X_635750-MLM111039976343_042026-R-kia-seltos-15-sx-at.webp",
    "https://http2.mlstatic.com/D_NQ_NP_2X_603313-MLM110122586518_042026-R-kia-seltos-15-sx-at.webp",
    "https://http2.mlstatic.com/D_NQ_NP_2X_904882-MLM111039945745_042026-R-kia-seltos-15-sx-at.webp",
]


async def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "[smoke] ANTHROPIC_API_KEY no exportada. Skip.\n"
            "Para correr: export ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        return 0  # exit clean — no es un fallo, es un skip explícito

    print(f"[smoke] Analizando {len(SAMPLE_PHOTOS)} fotos del Kia Seltos…", flush=True)
    findings = await analyze_photos(SAMPLE_PHOTOS, max_photos=len(SAMPLE_PHOTOS))

    print(f"[smoke] Hallazgos totales: {len(findings)}", flush=True)
    if findings:
        print(json.dumps(
            [f.model_dump(mode="json") for f in findings],
            indent=2, ensure_ascii=False,
        ))
    else:
        print("[smoke] Cero hallazgos — Claude considera las fotos limpias.")

    by_index = {}
    for f in findings:
        by_index.setdefault(f.photo_index, []).append(f)
    print("\n--- Resumen por foto ---")
    for i in range(len(SAMPLE_PHOTOS)):
        items = by_index.get(i, [])
        summary = ", ".join(f"{f.issue}/{f.severity}" for f in items) or "limpia"
        print(f"  Foto #{i}: {summary}")

    print("\n[smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
