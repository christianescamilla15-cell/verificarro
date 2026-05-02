"""Invoice / CFDI helpers para el pipeline.

Tres fases:
- **A** (declarativa): el comprador escribe el `invoice_number` que el
  vendedor le dijo. Reporte muestra "pídela y compárala con este folio".
- **B** (smart scanner): si el smart scanner extrajo `invoice_extra`
  del CFDI, se enriquece el `InvoiceData` con folio_fiscal_uuid, RFCs,
  fecha, total. Cross-validación contra listing detecta discrepancias.
- **C** (SAT verify): si hay UUID + RFCs + total, se llama al portal
  oficial SAT y se guarda `sat_status` (vigente / cancelado /
  no_encontrado). Findings de gravedad alta cuando aplica.
"""

import logging
import re
from datetime import UTC, datetime

from app.models.report import AnalyzeRequest, InvoiceData
from app.services.sat_verify import verify_cfdi

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def build_invoice_data(req: AnalyzeRequest) -> InvoiceData | None:
    """Construye `InvoiceData` desde el AnalyzeRequest (Fases A + B).

    Devuelve None si no hay invoice_number ni invoice_extra (caso normal
    cuando el comprador no declaró factura).
    """
    invoice_number = req.invoice_number.strip() if req.invoice_number else None
    invoice_extra = req.invoice_extra or {}

    if not invoice_number and not invoice_extra:
        return None

    # Si invoice_extra tiene folio_fiscal_uuid, lo preferimos como
    # invoice_number (es el campo más autoritativo).
    extra_uuid = invoice_extra.get("folio_fiscal_uuid")
    if extra_uuid and not invoice_number:
        invoice_number = extra_uuid

    # Detección rudimentaria: si parece UUID v4, lo marcamos como folio
    # fiscal CFDI; si no, como invoice_number genérico.
    folio_fiscal_uuid = None
    if invoice_number and _UUID_RE.match(invoice_number):
        folio_fiscal_uuid = invoice_number
    if not folio_fiscal_uuid and extra_uuid:
        folio_fiscal_uuid = extra_uuid

    fecha_dt = None
    fecha_raw = invoice_extra.get("fecha")
    if fecha_raw:
        try:
            fecha_dt = datetime.fromisoformat(str(fecha_raw))
        except (ValueError, TypeError):
            pass

    total_raw = invoice_extra.get("total")
    total_mxn = None
    if total_raw is not None:
        try:
            total_mxn = float(total_raw)
        except (TypeError, ValueError):
            pass

    return InvoiceData(
        invoice_number=invoice_number,
        folio_fiscal_uuid=folio_fiscal_uuid,
        rfc_emisor=invoice_extra.get("rfc_emisor"),
        rfc_receptor=invoice_extra.get("rfc_receptor"),
        fecha=fecha_dt,
        total_mxn=total_mxn,
        notes=(
            "Pídele al vendedor la factura ORIGINAL (impresa o XML CFDI). "
            "Verifica que el folio coincida con el que aquí declaraste, que "
            "los datos del auto (marca/modelo/año/NIV) matcheen el anuncio, "
            "y que el RFC del receptor sea el del vendedor actual. Si no "
            "tiene factura o el folio no coincide, NO COMPRES."
        ),
    )


async def build_invoice_data_with_verification(
    req: AnalyzeRequest,
) -> InvoiceData | None:
    """Construye `InvoiceData` y, si hay datos suficientes, consulta SAT (Fase C).

    Si el invoice_extra trae folio_fiscal_uuid + RFCs + total, dispara
    SAT verify y enriquece el InvoiceData con `sat_status` y
    `sat_checked_at`.

    Failure tolerant: SAT no responde → seguimos con sat_status=None
    (educativo en lugar de validado).
    """
    invoice_data = build_invoice_data(req)
    if not invoice_data:
        return None

    extra = req.invoice_extra or {}
    uuid_val = invoice_data.folio_fiscal_uuid
    rfc_emisor = invoice_data.rfc_emisor or extra.get("rfc_emisor")
    rfc_receptor = invoice_data.rfc_receptor or extra.get("rfc_receptor")
    total = invoice_data.total_mxn

    if not (uuid_val and rfc_emisor and rfc_receptor and total):
        return invoice_data

    try:
        sat = await verify_cfdi(uuid_val, rfc_emisor, rfc_receptor, float(total))
    except Exception:  # noqa: BLE001
        logger.exception("SAT verify falló")
        return invoice_data

    if not sat.queried or sat.status in (None, "error"):
        return invoice_data

    return invoice_data.model_copy(update={
        "sat_status": sat.status if sat.status in ("vigente", "cancelado", "no_encontrado") else None,
        "sat_checked_at": datetime.now(UTC),
    })


def build_questions_for_seller(
    invoice_data: InvoiceData | None,
) -> list[str]:
    """3-4 preguntas clave que el comprador debe hacer al vendedor.

    Si el comprador conoce el invoice_number, lo incluimos en una pregunta
    específica para que pida ver la factura física y compare folio.
    """
    base = [
        "¿Tienes la factura original y el endoso completo? Quiero verla "
        "antes de pagar cualquier cosa.",
        "¿Me dejas verificarlo en una agencia o con mi mecánico de confianza?",
        "¿Por qué lo vendes y desde cuándo lo tienes? "
        "(Si la respuesta es vaga o cambian la historia → bandera)",
    ]
    if invoice_data and invoice_data.invoice_number:
        base.insert(0, (
            f"Necesito ver la factura original con folio "
            f"{invoice_data.invoice_number}. Si no coincide, no compro."
        ))
    return base
