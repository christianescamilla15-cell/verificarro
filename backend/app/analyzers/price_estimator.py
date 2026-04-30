"""Price estimator — convierte una lista de comparables en `PriceEstimate`.

Función pura. Estrategia:

1. **Filtro escalonado**: empezamos con tolerancias estrechas
   (year ±2, kms ±30%) y las relajamos si quedan menos de 5
   comparables tras filtrar. Garantiza un estimado siempre que haya
   inventario amplio.
2. **Fair price** = mediana de los comparables (más robusta que el
   promedio frente a outliers).
3. **Rango p10/p90** del set filtrado.
4. **Delta_pct** = (price_anuncio - fair) / fair × 100. Negativo =
   barato vs mercado, positivo = caro.

Notas:

- Si el listing tiene 0 km (auto nuevo), no aplicamos filtro de kms.
- Si no hay comparables tras el filtro más laxo, devolvemos un
  `PriceEstimate` con `comparables_count=0` y `fair_price_mxn=None`.
"""

from __future__ import annotations

from statistics import median
from typing import Iterable

from app.models.report import ListingData, PriceEstimate
from app.scrapers.ml_search import Comparable

_MIN_COMPARABLES = 5
_TOLERANCE_LADDER: tuple[tuple[int, float], ...] = (
    (2, 0.30),  # year ±2, kms ±30%
    (3, 0.50),  # year ±3, kms ±50%
    (5, 1.00),  # year ±5, kms ±100% (sin tope superior)
)


def estimate(
    listing: ListingData,
    comparables: Iterable[Comparable],
    *,
    sources: list[str] | None = None,
) -> PriceEstimate:
    """Convierte comparables crudos en un estimado de precio justo."""
    pool = [c for c in comparables if c.price_mxn > 0 and c.year > 0]
    if not pool:
        return PriceEstimate(comparables_count=0, sources=sources or [])

    filtered = _apply_ladder(listing, pool)
    if len(filtered) < _MIN_COMPARABLES:
        # Si después del último escalón seguimos pobres, usamos lo que haya.
        filtered = filtered or pool

    prices = sorted(c.price_mxn for c in filtered)
    fair = median(prices)
    p10 = _percentile(prices, 10)
    p90 = _percentile(prices, 90)

    delta_pct: float | None = None
    if listing.price_mxn > 0 and fair > 0:
        delta_pct = (listing.price_mxn - fair) / fair * 100

    return PriceEstimate(
        fair_price_mxn=fair,
        range_low_mxn=p10,
        range_high_mxn=p90,
        delta_pct=delta_pct,
        comparables_count=len(filtered),
        sources=sources or ["mercadolibre"],
    )


def _apply_ladder(
    listing: ListingData, pool: list[Comparable]
) -> list[Comparable]:
    """Filtra `pool` con tolerancias crecientes hasta tener ≥ 5 items."""
    for year_band, kms_tolerance in _TOLERANCE_LADDER:
        filtered = [
            c
            for c in pool
            if _year_match(listing.year, c.year, year_band)
            and _kms_match(listing.kilometers, c.kilometers, kms_tolerance)
        ]
        if len(filtered) >= _MIN_COMPARABLES:
            return filtered
    return filtered  # último escalón (puede ser <5)


def _year_match(target: int, candidate: int, band: int) -> bool:
    if target <= 0:
        return True
    return abs(candidate - target) <= band


def _kms_match(target: int, candidate: int, tolerance: float) -> bool:
    if target <= 0:
        # Listing es auto nuevo o sin info. No filtramos por kms.
        return True
    if candidate < 0:
        return False
    diff = abs(candidate - target) / max(target, 1)
    return diff <= tolerance


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Percentil lineal estilo numpy (sin dependencia)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct / 100
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    weight = k - f
    return sorted_values[f] * (1 - weight) + sorted_values[c] * weight
