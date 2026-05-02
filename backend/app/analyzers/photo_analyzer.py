"""Análisis de fotos del anuncio con Claude Sonnet 4.6 visión.

Por foto, llama al endpoint `messages.create` con la imagen como `image`
de tipo `url` (Anthropic la jala directo del CDN de ML — no necesitamos
descargar ni base64). La respuesta está restringida a un JSON schema
estricto con los tipos de hallazgo que `PhotoFinding` acepta.

## Concurrencia y límites

- Hasta 6 fotos por reporte (rendimientos decrecientes pasando ese punto)
- 3 llamadas en vuelo simultáneas vía `asyncio.Semaphore` para no
  pisar rate limits de Anthropic
- Errores por foto se silencian: una URL muerta no debe tumbar todo el
  reporte. Solo se loguea y la foto contribuye 0 hallazgos.

## Costo

Claude Sonnet 4.6 visión: ~$3/MTok input, ~$15/MTok output. Una foto
toma ~1500 tokens de imagen + ~250 tokens de prompt + ~100 tokens de
respuesta = ~$0.005 USD por foto. 6 fotos = ~$0.03 USD por reporte.

Prompt caching no se usa: el system prompt mide ~250 tokens y el mínimo
cacheable en Sonnet 4.6 es 2048 tokens — no cachearía aunque lo
marcáramos. Cuando el prompt crezca lo agregamos.
"""

from __future__ import annotations

import asyncio
import json
import logging

from pydantic import ValidationError

from app.config import get_settings
from app.models.report import PhotoFinding

logger = logging.getLogger(__name__)

_MAX_PHOTOS = 6
_CONCURRENT_REQUESTS = 3
_MAX_TOKENS_RESPONSE = 600
_NOTE_MAX_LEN = 200


_SYSTEM_PROMPT = """Eres un mecánico mexicano experto revisando fotos de un \
auto usado en venta online (Mercado Libre, Marketplace).

Tu tarea: analizar la foto y reportar SOLO problemas visibles que indiquen \
daño, reparación previa o calidad muy baja del anuncio.

Tipos de hallazgos válidos:
- paint_mismatch: tonos de pintura distintos entre paneles adyacentes
- panel_gap: separación irregular o desalineación entre cofre/puertas/cajuela
- rust: óxido visible en carrocería
- prior_repair: signos claros de reparación, repintado o golpe arreglado
- low_quality: foto muy borrosa/oscura/lejana para evaluar bien
- watermark_or_stock: marca de agua de otro vendedor o foto stock evidente
- other: cualquier otro problema relevante (descríbelo en `note`)

Severidad:
- low: cosmético (rayón pequeño, polvo, foto regular pero usable)
- medium: afecta valor de reventa (golpe arreglado, óxido moderado)
- high: red flag de compra (choque mayor, óxido estructural, foto fake)

Reglas estrictas:
- Si la foto se ve limpia y normal, regresa {"issues": []}
- Sé conservador: solo reporta lo que VES con claridad
- "note" en español de México, máximo 100 caracteres, sin floritura
- NO inventes problemas. Mejor un falso negativo que un falso positivo."""


_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {
                        "type": "string",
                        "enum": [
                            "paint_mismatch",
                            "panel_gap",
                            "rust",
                            "prior_repair",
                            "low_quality",
                            "watermark_or_stock",
                            "other",
                        ],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "note": {"type": "string"},
                },
                "required": ["issue", "severity", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}


async def analyze_photos(
    photo_urls: list[str], max_photos: int = _MAX_PHOTOS
) -> list[PhotoFinding]:
    """Analiza hasta `max_photos` fotos en paralelo y consolida los hallazgos.

    Cada foto se procesa con Claude visión y devuelve 0+ `PhotoFinding`. El
    `photo_index` se sincroniza al orden de entrada para que el reporte
    pueda enlazar el hallazgo con la foto correspondiente.

    ### M-8 SSRF allowlist

    Las URLs se pasan directo al SDK de Anthropic (Anthropic hace el fetch),
    así que el SSRF clásico (acceso a 169.254.169.254 desde nuestro server)
    no aplica. PERO si `manual_listing.photo_urls` viene de user input,
    podríamos ser proxy oracle hacia hosts internos (e.g., un atacante
    apunta una URL pública a su CNAME hacia un endpoint privado de su
    target, y observa lo que Anthropic les responde). Filtramos con el
    mismo `_check_url_safe` de `photo_fetcher` antes de mandar a Claude.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY ausente — skip análisis de fotos")
        return []

    # M-8: filtrar URLs por allowlist SSRF antes de mandar a Anthropic.
    from app.services.photo_fetcher import _check_url_safe
    safe_urls: list[str] = []
    for u in photo_urls[:max_photos]:
        ok, reason = _check_url_safe(u)
        if ok:
            safe_urls.append(u)
        else:
            logger.warning("Foto rechazada (%s) en photo_analyzer: %s", reason, u)

    photos = safe_urls
    if not photos:
        return []

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    semaphore = asyncio.Semaphore(_CONCURRENT_REQUESTS)

    async def _bounded(idx: int, url: str) -> list[PhotoFinding]:
        async with semaphore:
            return await _analyze_one(client, idx, url)

    results = await asyncio.gather(
        *(_bounded(i, u) for i, u in enumerate(photos)),
        return_exceptions=True,
    )

    findings: list[PhotoFinding] = []
    for r in results:
        if isinstance(r, BaseException):
            logger.warning("Análisis de foto falló: %s", r)
            continue
        findings.extend(r)
    return findings


async def _analyze_one(client, photo_index: int, photo_url: str) -> list[PhotoFinding]:
    """Llama a Claude para una foto y parsea la respuesta."""
    settings = get_settings()
    try:
        response = await client.messages.create(
            model=settings.claude_vision_model,
            max_tokens=_MAX_TOKENS_RESPONSE,
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
                            "source": {"type": "url", "url": photo_url},
                        },
                        {
                            "type": "text",
                            "text": "Analiza esta foto del anuncio.",
                        },
                    ],
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Claude vision falló para foto #%d (%s): %s",
            photo_index,
            photo_url,
            exc,
        )
        return []

    text_blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
    if not text_blocks:
        return []
    raw = getattr(text_blocks[0], "text", "")
    return parse_findings(raw, photo_index=photo_index)


def parse_findings(raw_json: str, *, photo_index: int) -> list[PhotoFinding]:
    """HTML→struct puro: JSON crudo de Claude → lista de `PhotoFinding`.

    Resiliente: JSON malformado, items con campos faltantes o enum
    inválido se descartan silenciosamente. Los items válidos se
    truncan en `note` a `_NOTE_MAX_LEN` caracteres.
    """
    if not raw_json:
        return []
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.debug("Respuesta no-JSON para foto #%d: %r", photo_index, raw_json[:200])
        return []

    issues = data.get("issues") if isinstance(data, dict) else None
    if not isinstance(issues, list):
        return []

    findings: list[PhotoFinding] = []
    for raw_issue in issues:
        if not isinstance(raw_issue, dict):
            continue
        try:
            note = str(raw_issue.get("note", "")).strip()[:_NOTE_MAX_LEN]
            findings.append(
                PhotoFinding(
                    photo_index=photo_index,
                    issue=raw_issue["issue"],
                    severity=raw_issue["severity"],
                    note=note,
                )
            )
        except (KeyError, TypeError, ValidationError) as exc:
            logger.debug("Issue mal formado para foto #%d: %s", photo_index, exc)
            continue
    return findings
