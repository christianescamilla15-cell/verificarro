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


_SYSTEM_PROMPT = """Eres un experto en leer documentos del portal de \
consulta ciudadana REPUVE (Registro Publico Vehicular de Mexico, \
https://www2.repuve.gob.mx:8443/ciudadania/).

El usuario te puede enviar el resultado de una consulta REPUVE en \
DOS formatos diferentes — ambos validos:

(A) CAPTURA DE PANTALLA del modal de resultado (JPG/PNG/WebP):
    Aparece como un recuadro pop-up sobre el portal con:
    - Titulo tipo "Resultado de la consulta" o similar
    - Texto del estatus del vehiculo
    - Datos basicos del auto

(B) PDF EXPORTADO desde el boton "Exportar a PDF" del portal:
    Es un documento oficial con:
    - Header con escudo nacional MX y "REPUVE" o "Secretariado \
      Ejecutivo del SNSP"
    - Seccion de "Resultado de la consulta" o "Datos del vehiculo"
    - Texto del estatus
    - Footer con fecha de consulta y datos legales

Tu tarea es leer el documento (sea cual sea el formato) y extraer \
el contenido textual del bloque PRINCIPAL con el resultado de la \
consulta vehicular.

CONTENIDO QUE DEBES EXTRAER (cualquier formato):
- "Sin reportes" / "No presenta reportes" / "Sin reporte de robo"
- "Vehiculo robado" / "Reporte de robo activo" / "Reporte de robo \
  vigente" / "Reportado como robado"
- "No se encontro" / "Sin informacion" / "No existe registro" / \
  "Vehiculo no inscrito"
- "Situacion legal: Regular" / "Vigente" / "Irregular"
- Marca, modelo, anio, placa, NIV/serie del vehiculo

REGLAS:
1. Si el documento NO es de REPUVE (es otro sitio, otro PDF, foto \
random, pantalla en blanco) → found_modal=false, text="", explica \
en notes que NO viste contenido REPUVE.
2. Si el documento ES de REPUVE — sea screenshot del modal O PDF \
exportado — found_modal=true. NO importa el formato, solo importa \
que el contenido sea de REPUVE.
3. Conserva acentos y mayusculas originales.
4. NO inventes datos. Si un campo no esta visible, no lo agregues.
5. Si esta cortado o ilegible, found_modal=true pero confidence=low \
y describe el problema en notes.
6. El field `found_modal` es heredado del nombre original — \
interpretarlo como "este documento ES un resultado REPUVE valido", \
no literalmente "vi un modal pop-up".

Output: JSON exactamente con este shape:
{
  "text": "contenido textual del resultado REPUVE",
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
    """OCR del modal REPUVE desde imagen base64 O PDF.

    Acepta tanto imagenes (image/jpeg, image/png, image/webp) como
    PDFs (application/pdf) — REPUVE bloquea screenshots con
    FLAG_SECURE pero ofrece export a PDF que sirve cuando funciona.
    Claude API soporta PDFs nativamente con bloque content type
    'document' (mismo flow que image, mismo prompt, mismo schema).

    Costo: ~$0.005 USD (image) o ~$0.005-0.015 USD (PDF, depende
    de paginas — el PDF de REPUVE suele ser 1-2 paginas).
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada para OCR")

    import anthropic

    # Construir el bloque de contenido segun tipo. PDF usa el bloque
    # 'document' (Claude lo procesa pagina-por-pagina con vision).
    if media_type == "application/pdf":
        content_block: dict = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": image_base64,
            },
        }
        # Para PDFs reforzamos el output JSON en el prompt porque
        # output_config.json_schema NO se respeta consistentemente
        # con bloques `type: "document"`.
        prompt_text = (
            "Lee el PDF (es un reporte de REPUVE descargado por el "
            "usuario) y extrae el texto del bloque principal con el "
            "resultado de la consulta vehicular.\n\n"
            "RESPONDE SOLAMENTE CON UN JSON valido (sin markdown, "
            "sin ```, sin texto introductorio). El JSON DEBE tener "
            "exactamente este shape:\n"
            '{"text":"contenido textual del resultado", '
            '"found_modal":true, '
            '"confidence":"high", '
            '"notes":"explicacion corta"}\n\n'
            "Recuerda: found_modal=true si el PDF es de REPUVE "
            "(sin importar que sea PDF y no modal pop-up). "
            "found_modal=false SOLO si no es de REPUVE."
        )
    else:
        content_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_base64,
            },
        }
        prompt_text = (
            "Lee el modal de resultado REPUVE en esta captura y "
            "extrae su contenido textual."
        )

    # NOTA: para bloques `type: "document"` (PDFs) Anthropic no
    # respeta `output_config.json_schema` consistentemente — Claude
    # devuelve texto plano con markdown wrapper. Para imagenes
    # (`type: "image"`) si lo respeta. Por eso solo aplicamos
    # output_config para imagenes; para PDFs reforzamos el prompt
    # para que devuelva JSON puro y dejamos que parse_screenshot_response
    # extraiga el JSON tolerando markdown code blocks.
    is_pdf = media_type == "application/pdf"
    create_kwargs: dict = {
        "model": settings.claude_vision_model,
        "max_tokens": 800,
        "system": _SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    content_block,
                    {"type": "text", "text": prompt_text},
                ],
            }
        ],
    }
    if not is_pdf:
        create_kwargs["output_config"] = {
            "format": {
                "type": "json_schema",
                "schema": _RESPONSE_SCHEMA,
            }
        }

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(**create_kwargs)

    text_blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
    if not text_blocks:
        raise RuntimeError("Claude no devolvio texto")
    # Concatenar todos los text blocks — Claude puede separar la
    # explicacion del PDF en multiples bloques antes del JSON final.
    raw = "\n".join(getattr(b, "text", "") for b in text_blocks)

    # Log defensivo para diagnostico futuro: primeros 300 chars del raw
    logger.info(
        "scan_repuve_screenshot raw response (first 300 chars): %r",
        raw[:300],
    )

    return parse_screenshot_response(raw)


def _extract_json(raw: str) -> str | None:
    """Extrae el bloque JSON de una respuesta de Claude que puede traer
    wrappers markdown o texto introductorio.

    Para PDFs Claude no respeta `output_config.json_schema` consistentemente
    y devuelve algo tipo:

        Aqui esta el JSON solicitado:
        ```json
        {"text": "...", ...}
        ```

    Estrategias en cascada:
      1. Parsear el raw entero (ideal — funciona para imagenes con schema)
      2. Buscar bloque ```json ... ``` o ``` ... ```
      3. Buscar el primer `{` y el ultimo `}` y extraer ese substring
      4. None si nada parece JSON
    """
    if not raw or not raw.strip():
        return None

    # 1: tal cual
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # 2: markdown code block ```json ... ``` o ``` ... ```
    fence_match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    if fence_match:
        candidate = fence_match.group(1)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 3: primer { hasta ultimo } (greedy para acomodar JSON anidado)
    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidate = raw[first : last + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    return None


def parse_screenshot_response(raw_json: str) -> RepuveScreenshotResult:
    """JSON de Claude → RepuveScreenshotResult. Pure, testable.

    Defensivo contra:
    - JSON malformado (devuelve found_modal=false, low confidence)
    - confidence fuera del enum (downgrade a low)
    - text excesivamente largo (truncamos a 8KB)
    - Markdown code blocks alrededor del JSON (Claude PDFs)
    - Texto introductorio antes del JSON ("Aqui esta el JSON:")
    """
    extracted = _extract_json(raw_json)
    if extracted is None:
        # Devolver el raw truncado en notes para que veamos en logs
        # que respondio Claude exactamente cuando ningun JSON se extrae
        sample = (raw_json or "").strip()[:200]
        return RepuveScreenshotResult(
            text="", found_modal=False, confidence="low",
            notes=f"Claude no devolvio JSON parseable. Sample: {sample!r}",
        )

    try:
        data = json.loads(extracted)
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
