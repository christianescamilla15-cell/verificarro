"""OCR de placa vehicular MX desde foto vía Claude visión.

A diferencia del VIN (17 chars, ISO estricto), las placas mexicanas
varían por estado y por época:

- Federal carga / particulares CDMX modernos: 3 letras + 3 dígitos +
  1 letra (`ABC-123-D`).
- Estados con 7 chars sin sufijo: `ABC-1234`.
- Placas viejas: 6 chars `ABC-123`.
- Algunas comerciales: `1234567` (todo dígitos) o variantes con 2 letras.

Por eso aceptamos 5–7 caracteres alfanuméricos. La validación final la
hace REPUVE: si la placa es inválida, REPUVE responde "no encontrado".

Costo: ~$0.005 USD por escaneo (Sonnet 4.6 visión, 1 foto).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.config import get_settings

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """Eres un experto en lectura de placas vehiculares de \
México (todos los estados) en fotos.

Tu tarea: extraer EXACTAMENTE los caracteres alfanuméricos visibles en \
la placa, sin guiones ni espacios. La placa puede estar:

- Adelante o atrás del auto (frontales en algunos estados, traseras \
siempre)
- Sucia, parcialmente reflejada, o con sombra
- Fotografiada de costado (perspectiva)

REGLAS CRÍTICAS:
1. Las placas mexicanas tienen entre 5 y 7 caracteres alfanuméricos. \
NO incluyas guiones, puntos ni espacios en el output.
2. Confusiones comunes que debes resolver con cuidado: 0↔O, 1↔I, \
8↔B, 5↔S, 2↔Z, 6↔G. Si dudas entre letra y número, mira el contexto \
de la posición (las placas suelen tener patrón letras-números).
3. Si la foto no tiene placa visible o está demasiado borrosa para \
leer, devuelve plate="" y explica en notes.
4. NO inventes caracteres. Si solo ves 5 caracteres claros, devuelve \
5 caracteres — REPUVE manejará la validación.

Output: JSON exactamente con este shape:
{
  "plate": "5-7 caracteres alfanuméricos sin guiones, o cadena vacía",
  "confidence": "low" | "medium" | "high",
  "notes": "explicación corta en español"
}"""


_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "plate": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "notes": {"type": "string"},
    },
    "required": ["plate", "confidence", "notes"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class PlateScanResult:
    plate: str  # 5-7 chars alfanuméricos o "" si no se pudo extraer
    confidence: Literal["low", "medium", "high"]
    notes: str


async def scan_plate_from_image(
    image_base64: str, media_type: str = "image/jpeg"
) -> PlateScanResult:
    """OCR de la placa desde una imagen base64. Costo: ~$0.005 USD."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada para OCR")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.claude_vision_model,
        max_tokens=300,
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
                        "text": "Extrae la placa visible en esta foto.",
                    },
                ],
            }
        ],
    )

    text_blocks = [
        b for b in response.content if getattr(b, "type", "") == "text"
    ]
    if not text_blocks:
        raise RuntimeError("Claude no devolvió texto")
    raw = getattr(text_blocks[0], "text", "")

    return parse_scan_response(raw)


def parse_scan_response(raw_json: str) -> PlateScanResult:
    """JSON de Claude → PlateScanResult. Pure, testable."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return PlateScanResult(
            plate="", confidence="low",
            notes="Claude devolvió respuesta no-JSON",
        )

    raw_plate = (data.get("plate") or "").upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", raw_plate)

    confidence = data.get("confidence", "low")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"

    notes = str(data.get("notes", ""))[:500]

    if cleaned and not (5 <= len(cleaned) <= 7):
        notes = (
            f"{notes} | Placa extraída tiene {len(cleaned)} caracteres "
            "(esperaba entre 5 y 7). Re-escanea con mejor luz o ingresa "
            "manualmente."
        ).strip(" |")
        confidence = "low"

    return PlateScanResult(
        plate=cleaned,
        confidence=confidence,  # type: ignore[arg-type]
        notes=notes,
    )
