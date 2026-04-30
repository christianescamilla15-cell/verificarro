"""Unit tests for the Mercado Libre Motors parser.

Pure-function tests against saved HTML fixtures. No network, no Playwright.
"""

from pathlib import Path

import pytest

from app.scrapers.mercadolibre import (
    _is_listing_photo,
    _is_valid_ml_url,
    _make_model_from_title,
    _upgrade_to_hd,
    _year_from_text,
    parse_listing,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Full-listing parsing


def test_parse_listing_with_jsonld() -> None:
    html = _load("ml_listing_jsonld.html")
    url = "https://articulo.mercadolibre.com.mx/MLM-1234567890-honda-civic-2018"
    listing = parse_listing(html, url)

    assert listing.source.value == "mercadolibre"
    assert listing.title == "Honda Civic Lx 2018 4p Aut"
    assert listing.price_mxn == 230000.0
    assert listing.year == 2018
    assert listing.make == "Honda"
    assert listing.model == "Civic"
    assert listing.trim == "LX"
    assert listing.kilometers == 78500
    assert "Benito Juárez" in listing.location
    assert listing.seller_name == "Juan Pérez"
    assert "factura de agencia" in listing.description.lower()

    # Las 3 fotos deben estar (JSON-LD + galería) y dedup; deben venir en HD.
    assert len(listing.photo_urls) >= 2
    assert all("D_NQ_NP_2X_" in u for u in listing.photo_urls)


def test_parse_listing_without_jsonld_falls_back() -> None:
    html = _load("ml_listing_no_jsonld.html")
    url = "https://articulo.mercadolibre.com.mx/MLM-9999999-toyota-corolla-2020"
    listing = parse_listing(html, url)

    assert listing.title == "Toyota Corolla SE 2020 Sedán"
    assert listing.price_mxn == 345000.0
    assert listing.year == 2020
    assert listing.kilometers == 42300
    assert listing.make == "Toyota"
    assert listing.model == "Corolla"
    assert "Auto Mart MX" in listing.seller_name
    assert "Miguel Hidalgo" in listing.location
    # CSS upgrade D_Q_NP_ → D_NQ_NP_2X_
    assert listing.photo_urls
    assert "D_NQ_NP_2X_" in listing.photo_urls[0]


def test_parse_listing_handles_empty_html() -> None:
    listing = parse_listing(
        "<html><body></body></html>",
        "https://articulo.mercadolibre.com.mx/MLM-foo",
    )
    assert listing.title == ""
    assert listing.price_mxn == 0.0
    assert listing.year == 0
    assert listing.make == ""
    assert listing.kilometers == 0


# ---------------------------------------------------------------------------
# Helpers


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://articulo.mercadolibre.com.mx/MLM-1234", True),
        ("https://carro.mercadolibre.com.mx/MLM-1234", True),
        ("https://www.mercadolibre.com.mx/", False),
        ("https://example.com/MLM-1234", False),
        ("https://mercadolibre.com.ar/MLA-1234", False),
    ],
)
def test_is_valid_ml_url(url: str, expected: bool) -> None:
    assert _is_valid_ml_url(url) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Honda Civic 2018", 2018),
        ("Toyota 2020 SE", 2020),
        ("Sin año aquí", 0),
        ("", 0),
        ("Año 1995 modelo viejito", 1995),
    ],
)
def test_year_from_text(text: str, expected: int) -> None:
    assert _year_from_text(text) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Honda Civic LX 2018", ("Honda", "Civic")),
        ("Toyota Corolla SE 2020", ("Toyota", "Corolla")),
        ("VW Jetta 2019", ("Vw", "Jetta")),
        ("Mercedes-Benz C200 2017", ("Mercedes-Benz", "C200")),
        ("Sin marca conocida 2018", ("", "")),
        ("", ("", "")),
    ],
)
def test_make_model_from_title(title: str, expected: tuple[str, str]) -> None:
    assert _make_model_from_title(title) == expected


# ---------------------------------------------------------------------------
# Photo filters / HD upgrade


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://http2.mlstatic.com/D_NQ_NP_111-MLM-civic.jpg", True),
        ("https://http2.mlstatic.com/D_NQ_NP_2X_111-MLM-civic.jpg", True),
        (
            "https://http2.mlstatic.com/storage/catalog-technical-specs/"
            "images/assets/vectorial/color.svg",
            False,
        ),
        ("https://example.com/icon.svg", False),
        ("", False),
    ],
)
def test_is_listing_photo(url: str, expected: bool) -> None:
    assert _is_listing_photo(url) is expected


def test_upgrade_to_hd_is_idempotent() -> None:
    already_hd = "https://http2.mlstatic.com/D_NQ_NP_2X_111-MLM-civic.jpg"
    assert _upgrade_to_hd(already_hd) == already_hd
    sd = "https://http2.mlstatic.com/D_NQ_NP_111-MLM-civic.jpg"
    upgraded = _upgrade_to_hd(sd)
    assert "D_NQ_NP_2X_" in upgraded
    # Y aplicarlo dos veces no duplica el "_2X_".
    assert _upgrade_to_hd(upgraded) == upgraded


@pytest.mark.parametrize(
    ("raw", "expected_substr"),
    [
        ("https://http2.mlstatic.com/D_NQ_NP_111-MLM.jpg", "/D_NQ_NP_2X_111"),
        ("https://http2.mlstatic.com/D_Q_NP_111-MLM.jpg", "/D_NQ_NP_2X_111"),
        ("https://http2.mlstatic.com/D_Q_NP_2X_111-MLM.jpg", "/D_NQ_NP_2X_111"),
        ("https://http2.mlstatic.com/D_NQ_NP_2X_111-MLM.jpg", "/D_NQ_NP_2X_111"),
    ],
)
def test_upgrade_to_hd_handles_ml_prefix_variants(
    raw: str, expected_substr: str
) -> None:
    out = _upgrade_to_hd(raw)
    assert expected_substr in out
    # Nunca debe quedar el prefijo doblado.
    assert "/D_NQ_NP_2X_2X_" not in out


# ---------------------------------------------------------------------------
# Pipeline integration via the analyze endpoint requires a full mock of
# Playwright; that lives in test_analyze_stub.py with manual_listing.
# A live network smoke test is in test_mercadolibre_live.py (skipped by default).
