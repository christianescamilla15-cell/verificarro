"""Análisis de red flags del vendedor.

Mira `ListingData.seller_*` y devuelve `SellerFinding[]`. Los signals
que consume:

- `seller_name` (str): obvio
- `seller_account_age_days` (int|None): "Lleva X años en Mercado Libre"
- `seller_sales_count` (int|None): "1.2k+ ventas concretadas"
- `seller_reputation` ("green"|"yellow"|"red"|None): termómetro ML
- `seller_other_listings_count` (int|None): "X publicaciones"
- `seller_profile_url` (str|None): link a perfil

## Reglas de scoring

| Signal                                    | Severidad | Razón |
|-------------------------------------------|-----------|-------|
| `account_age_days < 30`                   | high      | Cuenta recién creada para esta venta |
| `account_age_days < 90`                   | medium    | Cuenta nueva |
| `seller_reputation == "red"`              | high      | Historial de quejas confirmado |
| `seller_reputation == "yellow"`           | medium    | Reputación irregular |
| `sales_count == 0` AND age >= 90          | medium    | Cuenta vieja sin ventas (atípico) |
| `sales_count is None` (no expuesto)       | low       | Concesionario / privado oculto |
| `other_listings_count == 1` (solo este)   | low       | Cuenta one-shot (no necesariamente malo) |
| `seller_name` parece throwaway            | medium    | Patrón regex de cuenta generada |
| `seller_name` vacío                       | low       | ML no expuso vendedor |

Estas reglas son conservadoras: preferimos falsos negativos a falsos
positivos en un dominio donde una alerta high indebida puede tirar
una venta legítima.
"""

from __future__ import annotations

import re

from app.models.report import ListingData, SellerFinding


def analyze(listing: ListingData) -> list[SellerFinding]:
    """Devuelve red flags del vendedor. Función pura."""
    findings: list[SellerFinding] = []

    seller = (listing.seller_name or "").strip()
    age = listing.seller_account_age_days
    sales = listing.seller_sales_count
    reputation = listing.seller_reputation
    other_listings = listing.seller_other_listings_count

    # Edad de la cuenta
    if age is not None:
        if age < 30:
            findings.append(SellerFinding(
                flag="new_account",
                severity="high",
                note=f"Cuenta del vendedor tiene {age} días — riesgo alto",
            ))
        elif age < 90:
            findings.append(SellerFinding(
                flag="new_account",
                severity="medium",
                note=f"Cuenta del vendedor tiene {age} días — relativamente nueva",
            ))

    # Reputación ML (termómetro)
    if reputation == "red":
        findings.append(SellerFinding(
            flag="other",
            severity="high",
            note=(
                "Reputación ML del vendedor está en zona ROJA — historial "
                "de quejas/reclamos. Verifica antes de pagar."
            ),
        ))
    elif reputation == "yellow":
        findings.append(SellerFinding(
            flag="other",
            severity="medium",
            note="Reputación ML del vendedor irregular — algunas quejas reportadas.",
        ))

    # Ventas concretadas
    if sales is not None and sales == 0 and age is not None and age >= 90:
        findings.append(SellerFinding(
            flag="no_other_listings",
            severity="medium",
            note=(
                f"Cuenta de {age} días sin ninguna venta concretada — "
                "atípico, podría ser cuenta dormida reactivada para esta venta."
            ),
        ))

    # Otros listings (one-shot)
    if other_listings is not None and other_listings <= 1:
        findings.append(SellerFinding(
            flag="no_other_listings",
            severity="low",
            note=(
                "Vendedor solo tiene este anuncio activo — cuenta de uso "
                "único común en autos particulares pero también en "
                "estafadores."
            ),
        ))

    # Nombre del vendedor
    if not seller:
        findings.append(SellerFinding(
            flag="other",
            severity="low",
            note="No se pudo extraer el nombre del vendedor del anuncio",
        ))
    elif _looks_throwaway(seller):
        findings.append(SellerFinding(
            flag="new_account",
            severity="medium",
            note=f"Nombre de vendedor genérico/aleatorio: '{seller}'",
        ))

    return findings


_THROWAWAY_PATTERNS = (
    re.compile(r"^[a-z]{1,3}\d{3,}$", re.IGNORECASE),  # x123, abc4567
    re.compile(r"^user\d+$", re.IGNORECASE),
    re.compile(r"^[a-z]+_[a-z]+\d{3,}$", re.IGNORECASE),  # foo_bar1234
)


def _looks_throwaway(name: str) -> bool:
    """Heurística MUY conservadora: solo nombres claramente generados."""
    n = name.strip().lower()
    return any(p.match(n) for p in _THROWAWAY_PATTERNS)
