"""Análisis de la descripción del anuncio buscando red flags de estafa.

100% local — sin red, sin Claude API. Es regex + diccionarios sobre la
descripción del listing. Diseñado para correr en milisegundos por
reporte (cero costo marginal).

## Categorías de red flag (matchean el Literal de `DescriptionFinding`)

| Flag                     | Qué busca                                                    |
| ------------------------ | ------------------------------------------------------------ |
| urgency                  | "urge", "vendo hoy", "necesito venderlo ya"                  |
| seller_abroad            | "estoy en el extranjero", "vivo en USA", "me mudo a..."      |
| advance_payment_request  | "depósito", "anticipo", "transferencia primero", "garantía"  |
| no_inspection_allowed    | "no permito ver", "no se puede revisar", "solo whatsapp"     |
| vague_history            | "no recuerdo", "no sé cuántos dueños", "fue de mi compadre"  |
| other                    | flags adicionales genéricos                                  |

## Severidad

- `high`: combinación clara de estafa (vendedor en extranjero +
  pago por adelantado, no permite revisión)
- `medium`: flag aislado pero relevante (urgencia + descripción vaga)
- `low`: indicio leve (urgencia sola en auto barato puede ser legítimo)

## False positives

Los patrones son intencionalmente conservadores. Frases como "no recuerdo
si tiene aire" no caen en `vague_history` porque el patrón requiere
contexto sobre dueños/historial. Cuando dudo prefiero falso negativo —
mejor que el reporte no asuste por nada.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.models.report import DescriptionFinding


@dataclass(frozen=True)
class _Pattern:
    """Patrón compilado con metadata."""

    flag: Literal[
        "urgency",
        "no_inspection_allowed",
        "seller_abroad",
        "advance_payment_request",
        "vague_history",
        "other",
    ]
    severity: Literal["low", "medium", "high"]
    regex: re.Pattern[str]
    excerpt_label: str


# El input se normaliza con `_normalize` (lowercase + sin acentos) antes de
# matchear, así que los patrones aquí asumen ASCII lowercase.
_PATTERNS: tuple[_Pattern, ...] = (
    # --- Urgencia ---
    _Pattern(
        "urgency", "medium",
        re.compile(r"\b(urge\s+vender|urge\s+venderlo|urge\s+venta)\b"),
        "vendedor expresa urgencia",
    ),
    _Pattern(
        "urgency", "low",
        re.compile(r"\b(urge|urgente|hoy\s+mismo|cuanto\s+antes)\b"),
        "lenguaje de urgencia",
    ),
    _Pattern(
        "urgency", "medium",
        re.compile(r"\b(necesito\s+(?:venderlo|venderla|el\s+dinero|liquidar))\b"),
        "necesidad financiera explícita",
    ),
    _Pattern(
        "urgency", "low",
        re.compile(r"\b(no\s+puedo\s+esperar|tengo\s+que\s+viajar|me\s+voy\s+(?:del\s+pais|del\s+país|maniana|manana))\b"),
        "presión por tiempo",
    ),
    # --- Vendedor en el extranjero ---
    _Pattern(
        "seller_abroad", "high",
        re.compile(r"\b(estoy\s+en\s+(?:el\s+)?extranjero|vivo\s+en\s+(?:usa|estados\s+unidos|canada|espana|espana))\b"),
        "vendedor declara residir en el extranjero",
    ),
    _Pattern(
        "seller_abroad", "high",
        re.compile(r"\b(me\s+mude\s+a|me\s+mudo\s+a)\s+(?:usa|texas|california|chicago|miami|nueva\s+york|canada|espana)\b"),
        "vendedor se mudó al extranjero",
    ),
    _Pattern(
        "seller_abroad", "high",
        re.compile(r"\b(envio|enviare|mandare)\s+(?:el\s+)?(?:auto|carro|vehiculo)\s+(?:desde|por)\b"),
        "ofrece envío desde otra ubicación",
    ),
    # --- Pago por adelantado ---
    _Pattern(
        "advance_payment_request", "high",
        re.compile(r"\b(deposito|anticipo|enganche)\s+(?:de\s+\$?\s*\d|por\s+adelantado|para\s+apartar)\b"),
        "pide depósito o anticipo",
    ),
    _Pattern(
        "advance_payment_request", "high",
        re.compile(r"\b(transferencia|deposita)\s+(?:primero|antes|para\s+apartar)\b"),
        "transferencia antes de ver el auto",
    ),
    _Pattern(
        "advance_payment_request", "high",
        re.compile(
            r"\bcuando\s+(?:me\s+|tu\s+|usted\s+)?"
            r"(?:deposites|deposite|transfieras|transfiera|pagues|pague|hagas\s+el\s+pago)\b"
        ),
        "envío condicionado al pago previo",
    ),
    _Pattern(
        "advance_payment_request", "high",
        re.compile(r"\b(senal|garantia)\s+de\s+\$?\s*\d"),
        "señal o garantía monetaria",
    ),
    _Pattern(
        "advance_payment_request", "medium",
        re.compile(r"\b(western\s+union|paypal\s+amigos|moneygram|bitcoin|cripto)\b"),
        "método de pago de alto riesgo",
    ),
    # --- No permite inspección ---
    _Pattern(
        "no_inspection_allowed", "high",
        re.compile(r"\b(no\s+(?:se\s+)?(?:permite|permitido|aceptan)\s+(?:revisi(?:o|ó)n|verificaci(?:o|ó)n|mecanico|inspecci(?:o|ó)n))\b"),
        "no permite revisión mecánica",
    ),
    _Pattern(
        "no_inspection_allowed", "medium",
        re.compile(r"\b(solo\s+whatsapp|no\s+llamadas|sin\s+llamadas)\b"),
        "limita el contacto a chat",
    ),
    _Pattern(
        "no_inspection_allowed", "high",
        re.compile(r"\b(no\s+se\s+entrega\s+antes\s+de|sin\s+ver(?:lo)?\s+antes)\b"),
        "rechaza inspección previa",
    ),
    # --- Historial vago ---
    _Pattern(
        "vague_history", "medium",
        re.compile(r"\b(no\s+(?:s(?:e|é)|recuerdo))\s+(?:cu(?:a|á)ntos\s+due(?:n|ñ)os|el\s+kilometraje\s+real)\b"),
        "no sabe historial básico",
    ),
    _Pattern(
        "vague_history", "low",
        re.compile(r"\b(lo\s+compre\s+(?:usado|asi)|fue\s+(?:de\s+)?mi\s+(?:compadre|primo|amigo))\b"),
        "historial poco trazable",
    ),
    _Pattern(
        "vague_history", "medium",
        re.compile(r"\b(sin\s+factura|no\s+tengo\s+factura|sin\s+papeles)\b"),
        "sin factura original",
    ),
    # --- Otros flags genéricos pero importantes ---
    _Pattern(
        "other", "high",
        re.compile(r"\b(no\s+es\s+robado|no\s+tiene\s+adeudo|sin\s+adeudo)\b"),
        "afirmación defensiva sobre legalidad",
    ),
    _Pattern(
        "other", "medium",
        re.compile(r"\b(precio\s+negociable\s+pero|acepto\s+cambio\s+de\s+(?:menor\s+valor|cualquier\s+cosa))\b"),
        "negociación inusualmente flexible",
    ),
)


def analyze(description: str) -> list[DescriptionFinding]:
    """Devuelve los red flags detectados en la descripción.

    Función pura: sin estado, sin red, sin I/O. Idempotente.
    """
    if not description or not description.strip():
        return []

    normalized = _normalize(description)
    seen: set[tuple[str, str]] = set()
    findings: list[DescriptionFinding] = []

    for pat in _PATTERNS:
        match = pat.regex.search(normalized)
        if not match:
            continue
        # Dedup: una sola finding por (flag, severity).
        key = (pat.flag, pat.severity)
        if key in seen:
            continue
        seen.add(key)
        excerpt = _build_excerpt(description, normalized, match.span(), pat.excerpt_label)
        findings.append(
            DescriptionFinding(
                flag=pat.flag,
                severity=pat.severity,
                excerpt=excerpt,
            )
        )

    return findings


def _normalize(text: str) -> str:
    """Lowercase + remueve acentos para matching consistente."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_accents)


def _build_excerpt(
    original: str, normalized: str, span: tuple[int, int], label: str
) -> str:
    """Devuelve `<label>: '<fragment>'` con ~30 caracteres antes y después.

    El excerpt se toma del `original` para que conserve mayúsculas y
    acentos al mostrarlo en el reporte.
    """
    # `normalized` puede tener distinto length que `original` por colapso
    # de whitespace; aplicamos un mapeo conservador usando el rango.
    start, end = span
    # Buscamos el fragmento en el original (case-insensitive) como
    # aproximación: tomamos las palabras matched y las localizamos.
    matched_text = normalized[start:end].strip()
    pivot = original.lower().find(matched_text[:20]) if matched_text else -1
    if pivot < 0:
        # Fallback: usa el normalizado.
        return f"{label}: '{matched_text}'"[:200]
    pad = 30
    s = max(0, pivot - pad)
    e = min(len(original), pivot + len(matched_text) + pad)
    fragment = original[s:e].strip()
    if s > 0:
        fragment = "…" + fragment
    if e < len(original):
        fragment = fragment + "…"
    fragment = re.sub(r"\s+", " ", fragment)
    return f"{label}: '{fragment}'"[:200]
