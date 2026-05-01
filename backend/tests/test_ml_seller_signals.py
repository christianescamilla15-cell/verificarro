"""Tests del extractor de seller signals en ML + reglas de seller_analyzer."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.analyzers import seller_analyzer
from app.models.report import ListingData, Source
from app.scrapers.mercadolibre import (
    _extract_seller_signals,
    _parse_other_listings_count,
    _parse_seller_account_age,
    _parse_seller_profile_url,
    _parse_seller_reputation,
    _parse_seller_sales,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------------------
# _parse_seller_account_age


def test_account_age_years() -> None:
    assert _parse_seller_account_age("lleva 8 años en mercado libre") == 8 * 365


def test_account_age_year_singular() -> None:
    assert _parse_seller_account_age("lleva 1 año en mercado libre") == 365


def test_account_age_months() -> None:
    assert _parse_seller_account_age("lleva 6 meses en mercado libre") == 180


def test_account_age_no_match() -> None:
    assert _parse_seller_account_age("vendedor confiable") is None


# ---------------------------------------------------------------------------
# _parse_seller_sales


def test_sales_k_format() -> None:
    assert _parse_seller_sales("1.2k+ ventas concretadas") == 1200


def test_sales_k_integer() -> None:
    assert _parse_seller_sales("5k+ ventas") == 5000


def test_sales_plain_number() -> None:
    assert _parse_seller_sales("+543 ventas concretadas") == 543


def test_sales_no_match() -> None:
    assert _parse_seller_sales("vendedor desde 2018") is None


# ---------------------------------------------------------------------------
# _parse_seller_reputation


def test_reputation_thermometer_5_green() -> None:
    soup = _soup('<div class="ui-thermometer__bar ui-thermometer__bar--5"></div>')
    assert _parse_seller_reputation(soup) == "green"


def test_reputation_thermometer_4_green() -> None:
    soup = _soup('<div class="ui-thermometer__bar ui-thermometer__bar--4"></div>')
    assert _parse_seller_reputation(soup) == "green"


def test_reputation_thermometer_3_yellow() -> None:
    soup = _soup('<div class="ui-thermometer__bar ui-thermometer__bar--3"></div>')
    assert _parse_seller_reputation(soup) == "yellow"


def test_reputation_thermometer_2_red() -> None:
    soup = _soup('<div class="ui-thermometer__bar ui-thermometer__bar--2"></div>')
    assert _parse_seller_reputation(soup) == "red"


def test_reputation_mercadolider_text() -> None:
    soup = _soup('<div>MercadoLíder Platinum</div>')
    assert _parse_seller_reputation(soup) == "green"


def test_reputation_no_match() -> None:
    soup = _soup('<div>vendedor</div>')
    assert _parse_seller_reputation(soup) is None


# ---------------------------------------------------------------------------
# other listings


def test_other_listings_count_publicaciones() -> None:
    assert _parse_other_listings_count("47 publicaciones del vendedor") == 47


def test_other_listings_count_ver_mas() -> None:
    assert _parse_other_listings_count("ver más anuncios (12)") == 12


def test_other_listings_no_match() -> None:
    assert _parse_other_listings_count("solo este auto") is None


# ---------------------------------------------------------------------------
# profile url


def test_profile_url_absolute() -> None:
    soup = _soup(
        '<a href="https://perfil.mercadolibre.com.mx/JUANP">Juan</a>'
    )
    assert _parse_seller_profile_url(soup) == (
        "https://perfil.mercadolibre.com.mx/JUANP"
    )


def test_profile_url_protocol_relative() -> None:
    soup = _soup(
        '<a href="//perfil.mercadolibre.com.mx/JUANP">Juan</a>'
    )
    assert _parse_seller_profile_url(soup) == (
        "https://perfil.mercadolibre.com.mx/JUANP"
    )


def test_profile_url_no_match() -> None:
    soup = _soup('<a href="/p/MLM-123">listing</a>')
    assert _parse_seller_profile_url(soup) is None


# ---------------------------------------------------------------------------
# _extract_seller_signals integration


def test_extract_seller_signals_full() -> None:
    html = """
    <html><body>
      <div class="ui-pdp-seller">
        <div class="ui-pdp-seller__header__title">Juan Pérez</div>
        <div>Lleva 5 años en Mercado Libre</div>
        <div>1.2k+ ventas concretadas</div>
        <div class="ui-thermometer__bar ui-thermometer__bar--5"></div>
        <div>47 publicaciones del vendedor</div>
        <a href="https://perfil.mercadolibre.com.mx/JUANP">Ver perfil</a>
      </div>
    </body></html>
    """
    soup = _soup(html)
    info = _extract_seller_signals(soup)
    assert info["account_age_days"] == 5 * 365
    assert info["sales_count"] == 1200
    assert info["reputation"] == "green"
    assert info["other_listings_count"] == 47
    assert info["profile_url"] == "https://perfil.mercadolibre.com.mx/JUANP"


def test_extract_seller_signals_empty_html() -> None:
    soup = _soup("<html><body></body></html>")
    info = _extract_seller_signals(soup)
    assert info == {}


def test_extract_seller_signals_partial() -> None:
    """Si solo viene la edad, los demás faltantes son None (key omitida)."""
    html = '<div class="ui-pdp-seller">Lleva 3 años en Mercado Libre</div>'
    info = _extract_seller_signals(_soup(html))
    assert info.get("account_age_days") == 3 * 365
    assert "sales_count" not in info
    assert "reputation" not in info


# ---------------------------------------------------------------------------
# seller_analyzer rules with new signals


def _listing(**kwargs) -> ListingData:
    defaults = dict(
        source=Source.MERCADOLIBRE,
        title="Honda Civic 2018",
        price_mxn=300_000.0,
        year=2018,
        make="Honda",
        model="Civic",
        kilometers=50_000,
        location="CDMX",
        seller_name="Juan Pérez",
    )
    defaults.update(kwargs)
    return ListingData(**defaults)


def test_seller_red_reputation_high_alert() -> None:
    listing = _listing(seller_reputation="red")
    findings = seller_analyzer.analyze(listing)
    assert any(f.severity == "high" and "ROJA" in f.note for f in findings)


def test_seller_yellow_reputation_medium_alert() -> None:
    listing = _listing(seller_reputation="yellow")
    findings = seller_analyzer.analyze(listing)
    assert any(f.severity == "medium" and "irregular" in f.note for f in findings)


def test_seller_green_reputation_no_alert() -> None:
    listing = _listing(seller_reputation="green")
    findings = seller_analyzer.analyze(listing)
    assert not any("reputación" in f.note.lower() for f in findings)


def test_seller_zero_sales_old_account_alert() -> None:
    listing = _listing(seller_sales_count=0, seller_account_age_days=400)
    findings = seller_analyzer.analyze(listing)
    assert any(
        f.flag == "no_other_listings" and f.severity == "medium"
        and "sin ninguna venta" in f.note
        for f in findings
    )


def test_seller_zero_sales_new_account_no_double_alert() -> None:
    """Cuenta nueva ya alerta por edad; el zero-sales no debería duplicar."""
    listing = _listing(seller_sales_count=0, seller_account_age_days=15)
    findings = seller_analyzer.analyze(listing)
    # Hay alert de new_account high, pero NO el de cuenta-vieja-sin-ventas
    assert not any("cuenta de" in f.note.lower() and "sin ninguna venta" in f.note for f in findings)


def test_seller_only_one_listing_low_info() -> None:
    listing = _listing(seller_other_listings_count=1)
    findings = seller_analyzer.analyze(listing)
    assert any(
        f.flag == "no_other_listings" and f.severity == "low"
        for f in findings
    )


def test_seller_many_listings_no_alert() -> None:
    listing = _listing(seller_other_listings_count=50)
    findings = seller_analyzer.analyze(listing)
    assert not any(f.flag == "no_other_listings" for f in findings)


def test_seller_pristine_no_alerts() -> None:
    """Vendedor con todo bien: cuenta vieja, ventas, verde, varios listings."""
    listing = _listing(
        seller_account_age_days=5 * 365,
        seller_sales_count=2000,
        seller_reputation="green",
        seller_other_listings_count=30,
    )
    findings = seller_analyzer.analyze(listing)
    # No debe haber alerts high ni medium
    assert not any(f.severity in ("high", "medium") for f in findings)
