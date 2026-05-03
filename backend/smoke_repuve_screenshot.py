"""Smoke E2E del flow `POST /api/repuve/screenshot`.

Toma una foto/captura real del modal de resultado REPUVE (la que un
usuario subiria desde su celular), corre el OCR contra Claude Vision
y pasa el resultado al parser canonico. Imprime cada paso para que
puedas ver donde fallaria si algo no anda.

NO testea la subida del archivo via HTTP — invoca el servicio
directo, asi te ahorras correr el backend completo.

## Uso

```bash
# Con path explicito
ANTHROPIC_API_KEY=sk-ant-... python smoke_repuve_screenshot.py path/a/captura.jpg

# Con env var
ANTHROPIC_API_KEY=sk-ant-... \\
SMOKE_REPUVE_IMAGE=path/a/captura.jpg \\
python smoke_repuve_screenshot.py
```

## Como obtener una captura real

1. Abre https://www2.repuve.gob.mx:8443/ciudadania/ en tu celular
2. Pega cualquier placa MX (ej. una propia)
3. Resuelve el reCAPTCHA visual
4. Cuando aparezca el modal con el resultado, toma una captura
   (boton fisico de screenshot del celular)
5. Pasa esa imagen a este script

## Que valida

- ANTHROPIC_API_KEY esta seteado y funcionando
- claude_vision_model en config produce JSON parseable
- El prompt de OCR identifica correctamente:
    * texto del modal
    * found_modal=true cuando hay modal real
    * confidence apropiado
- looks_like_repuve_text() acepta el texto extraido
- parse_response() canonico produce un RepuveResult sano

## Costo

~$0.005 USD por corrida (1 imagen × Claude Vision Sonnet).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path


def _load_image_b64(path: Path) -> tuple[str, str]:
    """Lee la imagen y devuelve (base64, media_type)."""
    if not path.exists():
        raise SystemExit(f"❌ No existe el archivo: {path}")
    if not path.is_file():
        raise SystemExit(f"❌ No es un archivo regular: {path}")

    suffix = path.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix)
    if not media_type:
        raise SystemExit(
            f"❌ Formato no soportado: {suffix}. Usa jpg, png o webp."
        )

    raw = path.read_bytes()
    if len(raw) == 0:
        raise SystemExit(f"❌ Archivo vacio: {path}")
    if len(raw) > 3 * 1024 * 1024:
        print(
            f"⚠️  Imagen grande ({len(raw) / 1024 / 1024:.1f} MB). "
            "Mobile capturas suelen ser <1MB.",
        )
    return base64.b64encode(raw).decode(), media_type


def _resolve_image_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser().resolve()
    env_path = os.environ.get("SMOKE_REPUVE_IMAGE")
    if env_path:
        return Path(env_path).expanduser().resolve()
    raise SystemExit(
        "❌ Sin imagen para procesar.\n\n"
        "Uso:\n"
        "  python smoke_repuve_screenshot.py <path/a/captura.jpg>\n\n"
        "O setea SMOKE_REPUVE_IMAGE en el env.\n\n"
        "Como obtener una captura: ver docstring de este script.",
    )


def _print_section(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)


async def main() -> int:
    image_path = _resolve_image_path()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "❌ ANTHROPIC_API_KEY no esta seteada.\n"
            "   export ANTHROPIC_API_KEY=sk-ant-...",
        )

    _print_section("0. Setup")
    print(f"  Imagen:    {image_path}")
    image_b64, media_type = _load_image_b64(image_path)
    print(f"  Tamano:    {len(image_b64):,} chars base64 ({media_type})")

    # Imports tardios para que el SystemExit por args llegue rapido
    from app.config import get_settings
    from app.scrapers.repuve import parse_response
    from app.services.repuve_screenshot_ocr import (
        looks_like_repuve_text,
        scan_repuve_screenshot,
    )

    settings = get_settings()
    print(f"  Modelo:    {settings.claude_vision_model}")

    _print_section("1. Claude Vision OCR")
    try:
        ocr = await scan_repuve_screenshot(image_b64, media_type=media_type)
    except RuntimeError as exc:
        print(f"  ❌ OCR fallo: {exc}")
        return 2

    print(f"  found_modal:  {ocr.found_modal}")
    print(f"  confidence:   {ocr.confidence}")
    print(f"  notes:        {ocr.notes[:200]}")
    print("  text extraido:")
    for line in (ocr.text or "(vacio)").splitlines()[:20]:
        print(f"    │ {line}")
    if len(ocr.text.splitlines()) > 20:
        print(f"    │ ... ({len(ocr.text.splitlines()) - 20} lineas mas)")

    if not ocr.found_modal:
        print(
            "\n  ⚠️  Claude no detecto un modal REPUVE. "
            "Verifica que la captura sea del modal de resultado, no de "
            "la pantalla de busqueda inicial.",
        )
        return 1

    _print_section("2. Heuristica looks_like_repuve_text()")
    matches_repuve = looks_like_repuve_text(ocr.text)
    print(f"  matches_repuve: {matches_repuve}")
    if not matches_repuve:
        print(
            "  ⚠️  El texto no contiene markers REPUVE conocidos. "
            "Si la consulta es valida pero el OCR no detecta los markers, "
            "agregar el nuevo wording al set _NOT_FOUND_MARKERS / "
            "looks_like_repuve_text en repuve_screenshot_ocr.py.",
        )
        return 1

    _print_section("3. Parser canonico (parse_response)")
    result = parse_response(ocr.text, plate=None, vin=None, captcha_used=False)
    summary = {
        "queried": result.queried,
        "is_stolen": result.is_stolen,
        "has_legal_status": result.has_legal_status,
        "raw_status": result.raw_status,
        "error": result.error,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    _print_section("4. Veredicto")
    if result.queried:
        verdict = "ROBADO 🚨" if result.is_stolen else "Sin reportes ✅"
        print(f"  ✅ Flow E2E exitoso → {verdict}")
        if result.has_legal_status is True:
            print("     Situacion legal: Regular")
        elif result.has_legal_status is False:
            print("     ⚠️  Situacion legal: Irregular")
    elif result.raw_status == "no_encontrado":
        print("  ✅ Flow E2E exitoso → REPUVE dice 'no encontrado'")
        print(
            "     (resultado valido del parser; el frontend lo trata "
            "como informativo, no error)",
        )
    else:
        print(f"  ⚠️  Flow funciono pero parser no concluyo: {result.error}")
        print(
            "     Posible causa: el modal tiene wording que no esta en "
            "los markers actuales de parse_response. Revisar el texto "
            "extraido arriba y ajustar markers en scrapers/repuve.py.",
        )
        return 1

    print("\n[smoke] OK — Plan A (screenshot OCR) funcional end-to-end")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
