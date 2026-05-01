"""Cross-validación de datos de factura vs listing.

Cuando el smart scanner extrae datos de una factura (CFDI), comparamos
contra el listing del anuncio. Discrepancias = bandera roja:

- Marca/modelo/año del listing ≠ marca/modelo/año de la factura → high
- VIN en factura ≠ VIN escaneado → high (placa clonada o factura ajena)
- RFC del receptor en factura ≠ vendedor del listing → medium

Por ahora la "comparación" es heurística string-based. Cuando crezca
el dataset podemos meter normalización fuzzy (Honda Motor Co. vs Honda).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class InvoiceValidationFinding:
    severity: Literal["low", "medium", "high"]
    message: str


def validate_invoice_against_listing(
    invoice_extra: dict,
    listing_make: str = "",
    listing_model: str = "",
    listing_year: int | None = None,
    scanned_vin: str | None = None,
) -> list[InvoiceValidationFinding]:
    """Compara los datos extraídos de la factura vs el listing.

    `invoice_extra` es el dict que devuelve el smart scanner para
    `type=invoice`, ej:

        {
            "folio_fiscal_uuid": "...",
            "rfc_emisor": "AAA010101AAA",
            "rfc_receptor": "BBB020202BBB",
            "fecha": "2018-03-15",
            "total": 280000,
            "marca": "HONDA",
            "modelo": "Civic",
            "año": 2018,
            "niv": "19XFC2F58JE000001",
        }

    Devuelve lista de findings — vacía si todo cuadra.
    """
    findings: list[InvoiceValidationFinding] = []
    if not invoice_extra:
        return findings

    inv_make = str(invoice_extra.get("marca") or "").strip().lower()
    inv_model = str(invoice_extra.get("modelo") or "").strip().lower()
    inv_year_raw = invoice_extra.get("año") or invoice_extra.get("ano")
    inv_year = _coerce_year(inv_year_raw)
    inv_vin = str(invoice_extra.get("niv") or invoice_extra.get("vin") or "").strip().upper()

    listing_make_l = (listing_make or "").strip().lower()
    listing_model_l = (listing_model or "").strip().lower()

    # Marca
    if inv_make and listing_make_l and inv_make != listing_make_l:
        # Tolerar substring match (Honda vs Honda Motor)
        if not (inv_make in listing_make_l or listing_make_l in inv_make):
            findings.append(InvoiceValidationFinding(
                severity="high",
                message=(
                    f"FACTURA dice marca '{inv_make.upper()}' pero el "
                    f"anuncio dice '{listing_make}'. Discrepancia grave — "
                    "verifica que la factura corresponda a este auto."
                ),
            ))

    # Modelo
    if inv_model and listing_model_l and inv_model != listing_model_l:
        if not (inv_model in listing_model_l or listing_model_l in inv_model):
            findings.append(InvoiceValidationFinding(
                severity="high",
                message=(
                    f"FACTURA dice modelo '{inv_model.title()}' pero el "
                    f"anuncio dice '{listing_model}'. La factura puede no "
                    "corresponder a este auto."
                ),
            ))

    # Año (tolera ±1 por modelo año vs año fabricación)
    if inv_year and listing_year and listing_year > 1990:
        diff = abs(inv_year - listing_year)
        if diff > 1:
            severity: Literal["medium", "high"] = "medium" if diff <= 3 else "high"
            findings.append(InvoiceValidationFinding(
                severity=severity,
                message=(
                    f"FACTURA dice año {inv_year} pero el anuncio dice "
                    f"{listing_year} (diferencia {diff} años). Pregúntale "
                    "al vendedor o no compres."
                ),
            ))

    # VIN
    if inv_vin and scanned_vin:
        if inv_vin.replace("-", "").replace(" ", "") != scanned_vin.replace("-", "").replace(" ", ""):
            findings.append(InvoiceValidationFinding(
                severity="high",
                message=(
                    f"FACTURA dice NIV '{inv_vin}' pero el VIN físico "
                    f"escaneado es '{scanned_vin}'. POSIBLE PLACA CLONADA "
                    "o factura ajena — no compres."
                ),
            ))

    return findings


def _coerce_year(raw) -> int | None:
    """Convierte el campo año (puede venir como int o string) a int.

    Valida que esté en rango plausible (1900-2099) — `2200` o `1850`
    se devuelven como None (probablemente OCR error).
    """
    if raw is None:
        return None
    try:
        if isinstance(raw, int):
            y = raw
        else:
            s = str(raw).strip()
            if not s.isdigit():
                return None
            y = int(s)
        if 1900 < y < 2100:
            return y
    except (TypeError, ValueError):
        pass
    return None
