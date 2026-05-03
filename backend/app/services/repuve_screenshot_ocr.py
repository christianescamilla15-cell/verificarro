"""OCR del modal de resultado REPUVE desde una foto/screenshot.

El usuario abre repuve.gob.mx en su celular, hace la consulta manual
(resuelve el reCAPTCHA visible en 5s), ve el modal con el resultado y
toma una captura. Ese screenshot llega aqui — Claude Vision lee el
texto del modal, lo entregamos al parser canonico
(`app.scrapers.repuve.parse_response`) y devolvemos un `RepuveResult`.

## Por que asi en lugar de extension Chrome

Verificarro vive en mobile. Las extensiones Chrome no existen en
Chrome mobile. Pedirle al user que tome una foto del modal es
universal (Android + iOS + desktop), no requiere instalacion, y el
costo marginal es ~$0.005 USD por consulta en Claude Vision.

## Reuso del parser

Claude solo extrae el texto plano del modal. La logica de "sin
reportes" / "robado" / "no encontrado" / "situacion legal regular"
sigue en `parse_response()` — una unica fuente de verdad para todos
los flows REPUVE (sidecar, extension futura, screenshot OCR).

## Output JSON

Pedimos a Claude que devuelva:
- `text`: contenido textual del modal (lo que el usuario ve renderizado)
- `found_modal`: bool — true si efectivamente vio un modal de
  resultado REPUVE; false si la foto era irrelevante (otro sitio,
  pantalla negra, etc.)
- `confidence`: low | medium | high
- `notes`: comentarios o warnings del OCR
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.config import get_settings

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """Eres un experto en leer capturas de pantalla \
(screenshots) del portal de consulta ciudadana REPUVE \
(Registro Publico Vehicular de Mexico).

El portal vive en https://www2.repuve.gob.mx:8443/ciudadania/ y, \
despues de que el usuario consulta una placa o NIV, muestra un \
modal de resultado con informacion del vehiculo. Tu tarea es leer \
ese modal y extraer su contenido textual completo.

LO QUE DEBES BUSCAR EN EL SCREENSHOT:

- Un modal o recuadro con el resultado de la consulta REPUVE
- Posibles textos clave:
  * "Sin reportes" / "No presenta reportes" / "Sin reporte de robo"
  * "Vehiculo robado" / "Reporte de robo activo" / "Reporte de robo \
    vigente"
  * "No se encontro" / "Sin informacion" / "No existe registro"
  * "Situacion legal: Regular" / "Vigente" / "Irregular"
  * Marca, modelo, anio, placa, NIV/serie del vehiculo

REGLAS:
1. Si la foto NO es de un modal de REPUVE (es otro sitio, pantalla \
en blanco, pagina cargando, etc.) → found_modal=false, text="" y \
explica en notes.
2. Conserva los acentos y mayusculas originales del modal.
3. NO inventes datos. Si un campo no esta visible, no lo agregues.
4. Si el modal esta cortado o ilegible, found_modal=true pero \
confidence=low y describe el problema en notes.

Output: JSON exactamente con este shape:
{
  "text": "contenido textual del modal",
  "found_modal": true | false,
  "confidence": "low" | "medium" | "high",
  "notes": "explicacion corta en espanol"
}"""


_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "found_modal": {"type": "boolean"},
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "notes": {"type": "string"},
    },
    "required": ["text", "found_modal", "confidence", "notes"],
    "additionalProperties": False,
}

_MAX_TEXT_BYTES = 8_000  # modal real suele ser <500 chars, margen 16x


@dataclass(frozen=True)
class RepuveScreenshotResult:
    text: str
    found_modal: bool
    confidence: Literal["low", "medium", "high"]
    notes: str


async def scan_repuve_screenshot(
    image_base64: str,
    media_type: str = "image/jpeg",
) -> RepuveScreenshotResult:
    """OCR del modal REPUVE desde imagen base64. Costo: ~$0.005 USD."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada para OCR")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.claude_vision_model,
        max_tokens=600,
        system=_SYSTEM_PROMPT,
        output_config={
            "format": {
                "type": "json_schema",
                "schema": _RESPONSE_SCHEMA,
            }
        },
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Lee el modal de resultado REPUVE en esta "
                            "captura y extrae su contenido textual."
                        ),
                    },
                ],
            }
        ],
    )

    text_blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
    if not text_blocks:
        raise RuntimeError("Claude no devolvio texto")
    raw = getattr(text_blocks[0], "text", "")

    return parse_screenshot_response(raw)


def parse_screenshot_response(raw_json: str) -> RepuveScreenshotResult:
    """JSON de Claude → RepuveScreenshotResult. Pure, testable.

    Defensivo contra:
    - JSON malformado (devuelve found_modal=false, low confidence)
    - confidence fuera del enum (downgrade a low)
    - text excesivamente largo (truncamos a 8KB)
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return RepuveScreenshotResult(
            text="", found_modal=False, confidence="low",
            notes="Claude devolvio respuesta no-JSON",
        )

    text = str(data.get("text", ""))
    if len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
        text = text[: _MAX_TEXT_BYTES // 2]

    found_modal = bool(data.get("found_modal", False))

    confidence = data.get("confidence", "low")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"

    notes = str(data.get("notes", ""))[:500]

    # Sanity: si dijo found_modal=true pero text esta vacio, downgrade
    if found_modal and not text.strip():
        found_modal = False
        notes = (
            f"{notes} | Claude marco found_modal=true pero text vacio — "
            "tratado como no encontrado."
        ).strip(" |")
        confidence = "low"

    return RepuveScreenshotResult(
        text=text,
        found_modal=found_modal,
        confidence=confidence,  # type: ignore[arg-type]
        notes=notes,
    )


# Helpers para reusar marker logic del parser canonico sin importar
# el modulo de scrapers (que arrastra dependencias de Playwright).

_NOT_FOUND_MARKERS = (
    "no se encontr",
    "no se encuentra",
    "sin informacion",
    "sin información",
    "no existe registro",
)


def looks_like_repuve_text(text: str) -> bool:
    """Heuristica defensiva: el texto debe contener al menos UN marker
    REPUVE (no_encontrado | sin_reportes | robado | situacion legal).

    Si el OCR extrajo algo random pero dijo found_modal=true, lo
    descartamos antes de pasarselo al parser canonico para evitar
    falsos negativos como `is_stolen=True` por la palabra "robo" en
    cualquier UI.
    """
    if not text:
        return False
    lowered = re.sub(r"\s+", " ", text).lower()
    repuve_markers = (
        *_NOT_FOUND_MARKERS,
        "sin reportes",
        "no presenta reportes",
        "no se reporta",
        "vehiculo robado",
        "vehículo robado",
        "reporte de robo",
        "situacion legal",
        "situación legal",
        "repuve",
    )
    return any(m in lowered for m in repuve_markers)
