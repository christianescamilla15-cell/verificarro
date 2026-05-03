"""Smart scanner — auto-detecta el tipo de documento/objeto en la foto.

El usuario apunta la cámara a CUALQUIER cosa relevante del auto:
- Placa metálica
- Etiqueta del NIV/VIN (en marco de puerta o tablero)
- Factura impresa o XML CFDI mostrado en pantalla

Y el scanner clasifica + extrae lo correcto. Esto permite que el
flujo del usuario sea "apunta y dispara" sin pre-seleccionar tipo.

## Costo

Una sola llamada a Claude Sonnet vision: ~$0.005-0.008 USD.
Ahorra UX (no hay que preguntar "¿qué tipo es?") sin agregar costo.

## Precheck (TIER 3 auto-capture)

`precheck_image()` es una pasada barata con Claude Haiku 4.5
(~$0.0003 / call) que SOLO clasifica el tipo sin extraer valores.
El scanner del frontend lo invoca cuando las heurísticas client-side
detectan "frame listo" — si Haiku confirma que es plate/vin/invoice
real (no un libro/tarjeta/cualquier rectángulo), recién entonces se
dispara el smart_scan completo con Sonnet. Reduce ~30% los falsos
positivos del TIER 1 sin necesitar dataset etiquetado.

## Output schema

```json
{
  "type": "plate" | "vin" | "invoice" | "unknown",
  "value": "<el dato principal extraído>",
  "extra": {<campos adicionales según tipo>},
  "confidence": "low" | "medium" | "high",
  "notes": "explicación corta"
}
```

Para `type=invoice`, `extra` incluye:
- `folio_fiscal_uuid`: UUID del CFDI si visible
- `rfc_emisor`: RFC del emisor
- `rfc_receptor`: RFC del receptor
- `fecha`: ISO format si se ve
- `total`: monto total si se ve
- `marca`, `modelo`, `año`: del auto si la factura los muestra
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from app.config import get_settings

logger = logging.getLogger(__name__)


ScanType = Literal["plate", "vin", "invoice", "unknown"]


@dataclass(frozen=True)
class SmartScanResult:
    type: ScanType
    value: str
    confidence: Literal["low", "medium", "high"]
    notes: str
    extra: dict = field(default_factory=dict)


_SYSTEM_PROMPT = """Eres un asistente experto que clasifica fotos \
relacionadas con la compra de un auto usado en México.

Tu trabajo: ver la foto y decir EXACTAMENTE qué muestra, devolviendo \
JSON estructurado.

Tipos posibles (campo "type"):

- "plate": placa vehicular mexicana (rectángulo metálico/plástico, \
5-7 caracteres alfanuméricos típicamente con guion). Puede estar \
adelante o atrás del auto, sucia, con sombras.

- "vin": Número de Identificación Vehicular = 17 caracteres \
alfanuméricos sin I/O/Q, en sticker del marco de puerta del chofer, \
en el tablero del piloto (visible por el parabrisas), o grabado.

- "invoice": factura del auto (CFDI). Documento de papel con header \
del SAT, secciones de emisor/receptor con RFC, datos del vehículo, \
folio fiscal (UUID), fecha, total. Puede estar impresa o ser \
captura de PDF/XML.

- "unknown": no puedes determinar qué es, foto borrosa, o muestra \
algo distinto a los anteriores.

REGLAS por tipo:

Para PLATE:
- "value": los 5-7 chars alfanuméricos sin guiones ni espacios
- "extra": {} (vacío)
- "confidence": qué tan claro se ven los caracteres

Para VIN:
- "value": exactamente 17 caracteres. Si cuentas más o menos, "low" \
y devuelve lo que ves.
- ISO 3779 PROHÍBE I, O, Q. Si crees ver "I" → "1", "O" → "0", \
"Q" → debe ser O (que es 0). Confusiones comunes: 8↔B, 5↔S, 2↔Z.
- "extra": {} (vacío)

Para INVOICE:
- "value": el folio fiscal UUID si se ve (formato \
XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX), si no, el folio interno
- "extra": objeto con tantos como puedas extraer:
    folio_fiscal_uuid, rfc_emisor, rfc_receptor, fecha (YYYY-MM-DD), \
    total (número), marca, modelo, año, niv (si aparece en factura)
- "confidence": qué tan legible está el documento

Para UNKNOWN:
- "value": "" (cadena vacía)
- "extra": {}
- "notes": explica qué ves

Output JSON estricto, exactamente con este shape:
{
  "type": "plate" | "vin" | "invoice" | "unknown",
  "value": "string",
  "confidence": "low" | "medium" | "high",
  "notes": "explicación corta en español, max 200 chars",
  "extra": {}
}"""


_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["plate", "vin", "invoice", "unknown"],
        },
        "value": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "notes": {"type": "string"},
        "extra": {"type": "object"},
    },
    "required": ["type", "value", "confidence", "notes", "extra"],
    "additionalProperties": False,
}


async def smart_scan(
    image_base64: str, media_type: str = "image/jpeg"
) -> SmartScanResult:
    """Clasifica + extrae datos de una imagen usando Claude vision.

    Latencia: ~3-7s (single shot Claude Sonnet vision).
    Costo: ~$0.005-0.008 USD por scan.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada para smart scan")

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
                        "text": "Clasifica esta foto y extrae los datos.",
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


_PRECHECK_PROMPT = """Tu única tarea: ver esta foto y responder con UNA \
sola palabra:

- "plate" si ves una placa vehicular (rectángulo metálico con caracteres)
- "vin" si ves el NIV/VIN del auto (sticker con 17 caracteres)
- "invoice" si ves una factura del auto (papel con SAT/CFDI/RFC)
- "none" si la foto NO muestra ninguno de los 3 anteriores
- "unclear" si está demasiado borroso/oscuro para decidir

Solo la palabra. Nada más."""


_PRECHECK_TYPES = {"plate", "vin", "invoice", "none", "unclear"}


@dataclass(frozen=True)
class PrecheckResult:
    """Output de `precheck_image()` — solo clasificación, sin valores."""
    type: Literal["plate", "vin", "invoice", "none", "unclear"]
    raw: str  # respuesta literal del modelo, para debug


async def precheck_image(
    image_base64: str, media_type: str = "image/jpeg"
) -> PrecheckResult:
    """Pre-clasificación barata con Haiku 4.5 (~$0.0003/call).

    Usado por el frontend antes de gastar smart_scan completo:
    si esto devuelve `none` o `unclear`, no vale la pena correr Sonnet.

    Latencia típica: 500-900ms.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        # Fail open — si no hay key, dejamos pasar al smart_scan que
        # ya tiene su propio error handling.
        return PrecheckResult(type="unclear", raw="no-api-key")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=20,
            system=_PRECHECK_PROMPT,
            messages=[{
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
                    {"type": "text", "text": "Clasifica."},
                ],
            }],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Precheck Haiku falló (no-bloqueante): %s", exc)
        return PrecheckResult(type="unclear", raw=f"error: {exc}")

    text_blocks = [
        b for b in response.content if getattr(b, "type", "") == "text"
    ]
    raw = (text_blocks[0].text if text_blocks else "").strip().lower()

    # Tomamos la primera palabra de la respuesta — Haiku a veces
    # agrega explicación pese al prompt, e.g. "plate (placa visible)".
    first_word = re.split(r"[^a-z]+", raw, maxsplit=1)[0] if raw else ""
    if first_word not in _PRECHECK_TYPES:
        first_word = "unclear"

    return PrecheckResult(type=first_word, raw=raw[:200])  # type: ignore[arg-type]


def parse_scan_response(raw_json: str) -> SmartScanResult:
    """JSON de Claude → SmartScanResult. Pure, testable."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return SmartScanResult(
            type="unknown",
            value="",
            confidence="low",
            notes="Claude devolvió respuesta no-JSON",
        )

    type_value = data.get("type", "unknown")
    if type_value not in ("plate", "vin", "invoice", "unknown"):
        type_value = "unknown"

    value = str(data.get("value", "") or "").strip()
    if type_value in ("plate", "vin"):
        # Sanitizar: uppercase, sin chars no alfanuméricos
        value = re.sub(r"[^A-Z0-9]", "", value.upper())

    confidence = data.get("confidence", "low")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"

    notes = str(data.get("notes", ""))[:300]
    extra = data.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}

    # Validaciones por tipo (degradación a low si algo no cuadra)
    if type_value == "vin" and value and len(value) != 17:
        confidence = "low"
        notes = f"{notes} | VIN extraído tiene {len(value)} chars (esperaban 17)".strip(" |")
    if type_value == "plate" and value and not (5 <= len(value) <= 7):
        confidence = "low"
        notes = f"{notes} | Placa extraída tiene {len(value)} chars (esperaban 5-7)".strip(" |")

    return SmartScanResult(
        type=type_value,  # type: ignore[arg-type]
        value=value,
        confidence=confidence,  # type: ignore[arg-type]
        notes=notes,
        extra=extra,
    )
