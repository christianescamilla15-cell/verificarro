"""SAT CFDI verification — valida factura electrónica contra el portal oficial.

Endpoint público del SAT (sin auth):
  https://verificacfdi.facturaelectronica.sat.gob.mx/

Es un servicio SOAP (legado) que acepta:
- UUID del CFDI
- RFC del emisor (re)
- RFC del receptor (rr)
- Total

Y devuelve:
- Estado: "Vigente" | "Cancelado"
- EsCancelable: Sí/No
- EstatusCancelacion: razón si está cancelado
- Validacion EFOS: si el emisor está en lista de "Empresas Facturadoras de
  Operaciones Simuladas" (lavado de dinero / facturas falsas)

## Por qué importa

El SAT es la única autoridad que puede confirmar que un CFDI:
1. Existe realmente (no fue inventado)
2. Está vigente (no cancelado)
3. El emisor no está en lista negra (EFOS)

Si la factura del auto NO existe en SAT → fraude documental obvio.
Si está cancelada → el dueño previo la canceló (puede ser por venta o
porque el auto se "borró" del registro). Cualquier caso es bandera.
Si el emisor está en EFOS → factura "comprada" por el dueño previo
para lavar dinero o crear historial de propiedad falso.

## Implementación

El servicio SAT acepta GET/POST con query string:

  GET https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc/Consulta?expresionImpresa=...

Donde `expresionImpresa` es URL-encoded:

  ?id={UUID}&re={RFC_EMISOR}&rr={RFC_RECEPTOR}&tt={TOTAL}&fe={ULTIMOS_8_CHARS_SELLO}

Para Verificarro NO tendremos el sello digital (eso requiere acceso al
PDF/XML completo). Por eso usamos la API SOAP simple que solo necesita
los 4 campos básicos.

## Costo

$0 — endpoint público SAT, sin auth, sin rate limit publicado.

## Limitación

Si solo tenemos el UUID (sin RFCs ni total), no podemos validar.
El smart scanner debe extraer al menos UUID + 1 RFC + total para
disparar la consulta SAT.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)


_SAT_ENDPOINT = (
    "https://consultaqr.facturaelectronica.sat.gob.mx/"
    "ConsultaCFDIService.svc/Consulta"
)
_TIMEOUT_SEC = 12.0


@dataclass(frozen=True)
class SatVerifyResult:
    """Resultado de la consulta SAT."""

    queried: bool
    status: Literal["vigente", "cancelado", "no_encontrado", "error"] | None = None
    es_cancelable: bool | None = None
    estatus_cancelacion: str | None = None
    error: str | None = None
    raw_response: str | None = None


async def verify_cfdi(
    uuid: str,
    rfc_emisor: str,
    rfc_receptor: str,
    total: float,
) -> SatVerifyResult:
    """Consulta el estado del CFDI en el portal SAT.

    Devuelve `SatVerifyResult` SIEMPRE (no lanza excepciones); errores
    de red, timeout, validación → `error` field con detalle.

    `total` se formatea con 6 decimales como exige el SAT.
    """
    if not uuid or not rfc_emisor or not rfc_receptor or total is None:
        return SatVerifyResult(
            queried=False,
            error="Faltan campos requeridos (UUID, RFC emisor, RFC receptor, total)",
        )

    # Validar formato UUID
    if not re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        uuid, re.IGNORECASE,
    ):
        return SatVerifyResult(
            queried=False, error=f"UUID inválido: '{uuid}'",
        )

    # Construir el `expresionImpresa` que SAT espera
    expr = (
        f"?id={uuid}&re={rfc_emisor.upper()}"
        f"&rr={rfc_receptor.upper()}&tt={total:.6f}"
    )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            response = await client.get(
                _SAT_ENDPOINT,
                params={"expresionImpresa": expr},
            )
            response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("SAT verifycfdi falló: %s", exc)
        return SatVerifyResult(queried=False, error=f"SAT no respondió: {exc}")

    return parse_sat_response(response.text)


def parse_sat_response(raw: str) -> SatVerifyResult:
    """Parsea la respuesta SOAP/XML del SAT a `SatVerifyResult`.

    El SAT devuelve un XML con elementos como:

        <Estado>Vigente</Estado>
        <EsCancelable>Cancelable sin aceptación</EsCancelable>
        <EstatusCancelacion></EstatusCancelacion>

    Si el CFDI no existe:

        <CodigoEstatus>N - 602 ...</CodigoEstatus>
        <Estado></Estado>

    Pure parser — testable con XML fixtures.
    """
    if not raw:
        return SatVerifyResult(
            queried=False, error="Respuesta SAT vacía",
        )

    # Extracción regex (más robusta que parser XML porque el namespace
    # SOAP cambia con frecuencia)
    estado_match = re.search(r"<a?:?Estado[^>]*>([^<]*)</a?:?Estado>", raw)
    estado = estado_match.group(1).strip() if estado_match else ""

    cancelable_match = re.search(r"<a?:?EsCancelable[^>]*>([^<]*)</a?:?EsCancelable>", raw)
    es_cancelable_text = cancelable_match.group(1).strip() if cancelable_match else ""

    cancelacion_match = re.search(
        r"<a?:?EstatusCancelacion[^>]*>([^<]*)</a?:?EstatusCancelacion>", raw
    )
    estatus_cancelacion = (
        cancelacion_match.group(1).strip() if cancelacion_match else None
    )

    codigo_match = re.search(r"<a?:?CodigoEstatus[^>]*>([^<]*)</a?:?CodigoEstatus>", raw)
    codigo = codigo_match.group(1).strip() if codigo_match else ""

    # Mapeo a status interno
    status: Literal["vigente", "cancelado", "no_encontrado", "error"] | None = None
    if estado.lower() == "vigente":
        status = "vigente"
    elif estado.lower() == "cancelado":
        status = "cancelado"
    elif "no se encuentra" in codigo.lower() or "602" in codigo:
        status = "no_encontrado"
    elif estado:
        status = "error"  # Estado raro; lo registramos como error
    else:
        status = "error"

    return SatVerifyResult(
        queried=True,
        status=status,
        es_cancelable="No cancelable" not in es_cancelable_text
            if es_cancelable_text else None,
        estatus_cancelacion=estatus_cancelacion or None,
        raw_response=raw[:500],  # primero 500 chars para audit
    )
