"""Análisis de red flags del vendedor.

Mira `ListingData.seller_name` y `seller_account_age_days` (cuando esté
disponible) y devuelve `SellerFinding[]`.

## Limitación al cierre del MVP

El scraper de D2 hoy NO captura `seller_account_age_days` (queda `None`)
para listings de concesionarios — para particulares se podría obtener
navegando al perfil pero eso suma 1 request extra de Playwright por
reporte. Diferido a post-MVP.

Mientras tanto, este analyzer hace lo que puede con lo que tiene:
- Si `seller_name` viene vacío → flag `other` low (informativo, no
  necesariamente malo)
- Si `seller_account_age_days` está disponible y < 30 → `new_account`
  high
- Si `seller_account_age_days` < 90 → `new_account` medium

Cuando D6.5 (futuro) capture más datos del vendedor, este módulo crece
sin tocar el pipeline.
"""

from __future__ import annotations

import re
from typing import Literal

from app.models.report import ListingData, SellerFinding


def analyze(listing: ListingData) -> list[SellerFinding]:
    """Devuelve red flags del vendedor. Función pura."""
    findings: list[SellerFinding] = []

    seller = (listing.seller_name or "").strip()
    age = listing.seller_account_age_days

    if age is not None:
        if age < 30:
            findings.append(
                SellerFinding(
                    flag="new_account",
                    severity="high",
                    note=f"Cuenta del vendedor tiene {age} días — riesgo alto",
                )
            )
        elif age < 90:
            findings.append(
                SellerFinding(
                    flag="new_account",
                    severity="medium",
                    note=f"Cuenta del vendedor tiene {age} días — relativamente nueva",
                )
            )

    if not seller:
        # Cuando ML no expone vendedor (común en concesionarios) lo
        # registramos como informativo, no como red flag fuerte.
        findings.append(
            SellerFinding(
                flag="other",
                severity="low",
                note="No se pudo extraer el nombre del vendedor del anuncio",
            )
        )
    elif _looks_throwaway(seller):
        findings.append(
            SellerFinding(
                flag="new_account",
                severity="medium",
                note=f"Nombre de vendedor genérico/aleatorio: '{seller}'",
            )
        )

    return findings


_THROWAWAY_PATTERNS = (
    re.compile(r"^[a-z]{1,3}\d{3,}$", re.IGNORECASE),  # x123, abc4567
    re.compile(r"^user\d+$", re.IGNORECASE),
    re.compile(r"^[a-z]+_[a-z]+\d{3,}$", re.IGNORECASE),  # foo_bar1234
)


def _looks_throwaway(name: str) -> bool:
    """Heurística MUY conservadora: solo nombres claramente generados.

    Falsos positivos de "Juan2024" no me preocupan tanto como cazar
    "user12345" o "abc1234" que son patrones clásicos de cuenta de un
    solo uso.
    """
    n = name.strip().lower()
    return any(p.match(n) for p in _THROWAWAY_PATTERNS)
