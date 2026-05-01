"""OCR de VIN desde foto del tablero/marco de puerta vía Claude visión.

Costo: ~$0.005 USD por escaneo (1 foto × Sonnet 4.6 visión). El
prompt está endurecido contra el problema clásico del OCR de VINs:
confusión entre `0/O`, `1/I`, `8/B`, `5/S`. ISO 3779 prohíbe I/O/Q
así que cualquier "I", "O" o "Q" extraído por el OCR es muy probable
una mala lectura — Claude lo sabe por el prompt y debe corregir.

## Output structured

Pedimos JSON con:
- `vin`: 17 chars normalizados, sin espacios/guiones
- `confidence`: low | medium | high — Claude estima qué tan claro
  era el texto en la foto
- `notes`: cualquier observación (ej. "VIN parcialmente bloqueado por
  reflejo del parabrisas")

Si no se ve VIN en la foto, devolvemos `vin=""` y `notes` lo explica.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.config import get_settings

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """Eres un experto en lectura de VIN (Número de \
Identificación Vehicular ISO 3779) en fotos de autos.

Tu tarea: extraer EXACTAMENTE los 17 caracteres del VIN visible en la \
foto. El VIN puede estar en:
- El tablero del piloto (visible por el parabrisas)
- El marco de la puerta del chofer (sticker)
- El compartimento del motor
- Una factura o tarjeta de circulación

REGLAS CRÍTICAS:
1. ISO 3779 PROHÍBE las letras I, O, Q. Si crees ver una "I", es una "1". \
Si crees ver una "O", es un "0". Si crees ver una "Q", probablemente es \
"O" mal leído (o sea "0").
2. El VIN tiene EXACTAMENTE 17 caracteres alfanuméricos. Si cuentas más \
o menos, sigue mirando con cuidado.
3. Confusiones comunes que debes resolver: 8↔B, 5↔S, 2↔Z, 6↔G.
4. Si no ves el VIN o la foto está demasiado borrosa para leer, devuelve \
vin="" y explica en notes.

Output: JSON exactamente con este shape:
{
  "vin": "17 caracteres o cadena vacía",
  "confidence": "low" | "medium" | "high",
  "notes": "explicación corta en español"
}"""


_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "vin": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "notes": {"type": "string"},
    },
    "required": ["vin", "confidence", "notes"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class VinScanResult:
    vin: str  # 17 chars o "" si no se pudo extraer
    confidence: Literal["low", "medium", "high"]
    notes: str


async def scan_vin_from_image(image_base64: str, media_type: str = "image/jpeg") -> VinScanResult:
    """OCR del VIN desde una imagen base64. Costo: ~$0.005 USD."""
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
                        "text": "Extrae el VIN visible en esta foto.",
                    },
                ],
            }
        ],
    )

    text_blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
    if not text_blocks:
        raise RuntimeError("Claude no devolvió texto")
    raw = getattr(text_blocks[0], "text", "")

    return parse_scan_response(raw)


def parse_scan_response(raw_json: str) -> VinScanResult:
    """JSON de Claude → VinScanResult. Pure, testable.

    Sanitiza el VIN: uppercase, remueve espacios/guiones, valida que
    no contenga I/O/Q (Claude debería haberlos corregido, pero
    defendemos contra alucinaciones).
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return VinScanResult(
            vin="", confidence="low",
            notes="Claude devolvió respuesta no-JSON",
        )

    raw_vin = (data.get("vin") or "").upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", raw_vin)

    confidence = data.get("confidence", "low")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"

    notes = str(data.get("notes", ""))[:500]

    # Si Claude colocó I/O/Q en el VIN (debería haberlos corregido),
    # bajamos la confianza y agregamos al note.
    if cleaned and re.search(r"[IOQ]", cleaned):
        notes = (
            f"{notes} | Verificarro detectó I/O/Q en el VIN extraído — "
            "el OCR probablemente confundió 1/0 con I/O. Re-escanea con "
            "mejor luz."
        ).strip(" |")
        confidence = "low"

    if cleaned and len(cleaned) != 17:
        notes = (
            f"{notes} | VIN extraído tiene {len(cleaned)} caracteres "
            "(esperaban 17). Re-escanea con la foto más enfocada."
        ).strip(" |")
        confidence = "low"

    return VinScanResult(
        vin=cleaned,
        confidence=confidence,  # type: ignore[arg-type]
        notes=notes,
    )
