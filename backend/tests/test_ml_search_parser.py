"""Unit tests para `app.scrapers.ml_search.parse_search_html`.

Función pura sobre HTML guardado. Sin red.
"""

from pathlib import Path

import pytest

from app.scrapers.ml_search import parse_search_html, search_url

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_search_extracts_3_valid_cards() -> None:
    """De 5 cards en la fixture, 2 deben descartarse:
    una sin link MLM y la duplicada por URL.
    """
    comps = parse_search_html(_load("ml_search_civic.html"))
    assert len(comps) == 3
    titles = [c.title for c in comps]
    assert all("Civic" in t for t in titles)


def test_parse_search_card_fields() -> None:
    comps = parse_search_html(_load("ml_search_civic.html"))
    first = comps[0]
    assert first.price_mxn == 230_000.0
    assert first.year == 2018
    assert first.kilometers == 78_500
    assert "Benito Juárez" in first.location
    assert first.url == "https://auto.mercadolibre.com.mx/MLM-1111-honda-civic-lx-_JM"


def test_parse_search_strips_tracking_hash() -> None:
    """El parser quita el `#tracking` del href."""
    comps = parse_search_html(_load("ml_search_civic.html"))
    assert all("#" not in c.url for c in comps)


def test_parse_search_respects_limit() -> None:
    comps = parse_search_html(_load("ml_search_civic.html"), limit=2)
    assert len(comps) == 2


def test_parse_search_empty_html() -> None:
    assert parse_search_html("<html><body></body></html>") == []


# ---------------------------------------------------------------------------
# search_url


@pytest.mark.parametrize(
    ("make", "model", "expected"),
    [
        ("Honda", "Civic", "https://autos.mercadolibre.com.mx/honda-civic"),
        ("Toyota", "Corolla", "https://autos.mercadolibre.com.mx/toyota-corolla"),
        (
            "Mercedes-Benz",
            "C200",
            "https://autos.mercadolibre.com.mx/mercedes-benz-c200",
        ),
        ("VW", "Jetta GLI", "https://autos.mercadolibre.com.mx/vw-jetta-gli"),
        ("", "", "https://autos.mercadolibre.com.mx/"),
    ],
)
def test_search_url(make: str, model: str, expected: str) -> None:
    assert search_url(make, model) == expected
