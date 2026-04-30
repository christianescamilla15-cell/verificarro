"""Unit tests para `app.analyzers.price_estimator`.

Función pura: comparables → PriceEstimate. Sin red.
"""

import pytest

from app.analyzers.price_estimator import _percentile, estimate
from app.models.report import ListingData, Source
from app.scrapers.ml_search import Comparable


def _listing(year: int = 2018, kms: int = 80_000, price: float = 230_000) -> ListingData:
    return ListingData(
        source=Source.MERCADOLIBRE,
        title="Honda Civic LX",
        price_mxn=price,
        year=year,
        make="Honda",
        model="Civic",
        kilometers=kms,
        location="CDMX",
    )


def _comp(price: float, year: int, kms: int, url: str | None = None) -> Comparable:
    return Comparable(
        title=f"Civic {year}",
        price_mxn=price,
        year=year,
        kilometers=kms,
        location="CDMX",
        url=url or f"https://auto.mercadolibre.com.mx/MLM-{int(price)}",
    )


# ---------------------------------------------------------------------------
# Happy paths


def test_estimate_returns_median_within_tolerance() -> None:
    listing = _listing(year=2018, kms=80_000, price=230_000)
    comps = [
        _comp(210_000, 2018, 75_000),
        _comp(220_000, 2018, 80_000),
        _comp(230_000, 2018, 85_000),
        _comp(240_000, 2017, 90_000),
        _comp(250_000, 2019, 70_000),
    ]
    est = estimate(listing, comps)
    assert est.fair_price_mxn == 230_000.0
    assert est.range_low_mxn is not None and est.range_low_mxn < est.fair_price_mxn
    assert est.range_high_mxn is not None and est.range_high_mxn > est.fair_price_mxn
    assert est.comparables_count == 5
    assert est.sources == ["mercadolibre"]
    # 230k vs fair 230k → delta 0
    assert est.delta_pct == pytest.approx(0.0, abs=0.01)


def test_estimate_overpriced_listing_positive_delta() -> None:
    listing = _listing(year=2018, kms=80_000, price=300_000)
    comps = [_comp(220_000, 2018, 80_000)] * 5
    est = estimate(listing, comps)
    assert est.fair_price_mxn == 220_000
    assert est.delta_pct is not None and est.delta_pct > 30


def test_estimate_underpriced_listing_negative_delta() -> None:
    listing = _listing(year=2018, kms=80_000, price=180_000)
    comps = [_comp(230_000, 2018, 80_000)] * 5
    est = estimate(listing, comps)
    assert est.fair_price_mxn == 230_000
    assert est.delta_pct is not None and est.delta_pct < -20


def test_estimate_relaxes_tolerance_when_strict_filter_empty() -> None:
    """Si la tolerancia estrecha deja <5 comparables, escala el escalón."""
    listing = _listing(year=2018, kms=80_000)
    # En escalón 1 (year ±2, kms ±30%) solo 1 califica.
    # En escalón 2 (year ±3, kms ±50%) los 5 son válidos:
    # year 2015-2021 ✓, kms |c.kms - 80k| / 80k ≤ 0.5 ⇔ kms en [40k, 120k].
    comps = [
        _comp(220_000, 2018, 80_000, url="https://x/1"),
        _comp(220_000, 2015, 110_000, url="https://x/2"),
        _comp(220_000, 2015, 115_000, url="https://x/3"),
        _comp(220_000, 2021, 45_000, url="https://x/4"),
        _comp(220_000, 2021, 50_000, url="https://x/5"),
    ]
    est = estimate(listing, comps)
    assert est.comparables_count >= 5
    assert est.fair_price_mxn == 220_000


def test_estimate_no_year_filter_when_listing_year_unknown() -> None:
    """Si el anuncio no trae año (year=0), no se filtra por año."""
    listing = _listing(year=0, kms=80_000)
    comps = [_comp(p, 2010 + i, 80_000) for i, p in enumerate([200_000, 220_000, 240_000, 260_000, 280_000])]
    est = estimate(listing, comps)
    assert est.comparables_count == 5
    assert est.fair_price_mxn == 240_000


def test_estimate_no_kms_filter_when_listing_is_new() -> None:
    """Auto nuevo (kms=0) no filtra por kms."""
    listing = _listing(year=2025, kms=0, price=500_000)
    comps = [_comp(p, 2025, 100) for p in [490_000, 500_000, 510_000, 520_000, 530_000]]
    est = estimate(listing, comps)
    assert est.comparables_count == 5
    assert est.fair_price_mxn == 510_000


def test_estimate_empty_pool() -> None:
    est = estimate(_listing(), [])
    assert est.fair_price_mxn is None
    assert est.comparables_count == 0


def test_estimate_drops_invalid_comparables() -> None:
    listing = _listing()
    comps = [
        _comp(0, 2018, 80_000),  # price 0 → drop
        _comp(220_000, 0, 80_000),  # year 0 → drop
        _comp(230_000, 2018, 80_000),
    ]
    est = estimate(listing, comps)
    assert est.comparables_count == 1
    assert est.fair_price_mxn == 230_000


# ---------------------------------------------------------------------------
# _percentile


@pytest.mark.parametrize(
    ("values", "pct", "expected"),
    [
        ([100, 200, 300, 400, 500], 50, 300),
        ([100, 200, 300, 400, 500], 0, 100),
        ([100, 200, 300, 400, 500], 100, 500),
        ([100, 200], 50, 150),
        ([100], 50, 100),
        ([], 50, 0.0),
    ],
)
def test_percentile(values: list[int], pct: float, expected: float) -> None:
    assert _percentile([float(v) for v in values], pct) == expected
