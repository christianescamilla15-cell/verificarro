"""Tests del despachador multi-marketplace + parsers Vivanuncios/Seminuevos."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.scrapers.multi_marketplace import (
    CrossListing,
    FbMarketplaceProvider,
    KavakProvider,
    OlxMxProvider,
    SeminuevosProvider,
    VivanuncionesProvider,
    _parse_price,
    _parse_seminuevos,
    _parse_vivanuncios,
    _slugify,
    find_cross_listings,
)


# ---------------------------------------------------------------------------
# Helpers


def test_slugify_basic() -> None:
    assert _slugify("Honda Civic") == "honda-civic"
    assert _slugify("HONDA  CIVIC") == "honda-civic"
    assert _slugify("Citroën C3") == "citroen-c3"


def test_slugify_accents() -> None:
    assert _slugify("Peugeot 308") == "peugeot-308"
    assert _slugify("Volkswagen Mañana") == "volkswagen-manana"


def test_parse_price_clean() -> None:
    assert _parse_price("$250,000 MXN") == 250000.0
    assert _parse_price("250000") == 250000.0
    assert _parse_price("$1,234,567") == 1234567.0


def test_parse_price_invalid() -> None:
    assert _parse_price("") is None
    assert _parse_price("$$$") is None
    assert _parse_price("Consultar precio") is None


# ---------------------------------------------------------------------------
# Vivanuncios parser


_VIVA_FIXTURE = """
<html><body>
  <div class="tileV2">
    <a class="title" href="/auto-honda-civic-2018">Honda Civic 2018 EX</a>
    <span class="price">$250,000 MXN</span>
    <span class="location">Coyoacán, CDMX</span>
    <img src="https://img.viva.mx/abc.jpg" />
  </div>
  <div class="tileV2">
    <a class="title" href="/auto-toyota-corolla">Toyota Corolla 2019</a>
    <span class="price">$280,000</span>
  </div>
  <div class="tileV2">
    <a class="title" href="/auto-honda-civic-2020">Honda Civic Sport 2020</a>
    <span class="price">$320,000 MXN</span>
  </div>
</body></html>
"""


def test_parse_vivanuncios_filters_by_make_model() -> None:
    """Sólo retorna cards cuyo título contiene make+model — descarta el Toyota."""
    out = _parse_vivanuncios(_VIVA_FIXTURE, "Honda", "Civic")
    titles = [l.title for l in out]
    assert all("Honda" in t and "Civic" in t for t in titles)
    assert "Toyota Corolla 2019" not in titles


def test_parse_vivanuncios_extracts_fields() -> None:
    out = _parse_vivanuncios(_VIVA_FIXTURE, "Honda", "Civic")
    assert len(out) == 2
    first = out[0]
    assert first.marketplace == "vivanuncios"
    assert first.title == "Honda Civic 2018 EX"
    assert first.price_mxn == 250000.0
    assert first.location == "Coyoacán, CDMX"
    assert first.photos == ["https://img.viva.mx/abc.jpg"]
    assert "vivanuncios.com.mx" in first.url


def test_parse_vivanuncios_empty_html() -> None:
    assert _parse_vivanuncios("<html></html>", "Honda", "Civic") == []


def test_parse_vivanuncios_make_model_case_insensitive() -> None:
    out = _parse_vivanuncios(_VIVA_FIXTURE, "honda", "civic")
    assert len(out) == 2


# ---------------------------------------------------------------------------
# Seminuevos parser


_SEMI_FIXTURE = """
<html><body>
  <article class="vehicle-card">
    <h2>Honda Civic 2018 LX</h2>
    <span class="price">$240,000</span>
    <a href="/auto/honda-civic-2018-lx-12345">ver</a>
  </article>
  <article class="vehicle-card">
    <h2>Mazda 3 2020</h2>
    <span class="price">$310,000</span>
    <a href="/auto/mazda-3-2020-67890">ver</a>
  </article>
</body></html>
"""


def test_parse_seminuevos_filters_and_extracts() -> None:
    out = _parse_seminuevos(_SEMI_FIXTURE, "Honda", "Civic")
    assert len(out) == 1
    item = out[0]
    assert item.marketplace == "seminuevos"
    assert "Honda Civic" in item.title
    assert item.price_mxn == 240000.0
    assert "/auto/honda-civic-2018-lx-12345" in item.url


# ---------------------------------------------------------------------------
# Stubs siguen el contrato


@pytest.mark.asyncio
async def test_olx_stub_returns_empty() -> None:
    out = await OlxMxProvider().search("Honda", "Civic", 2018)
    assert out == []


@pytest.mark.asyncio
async def test_fb_stub_returns_empty() -> None:
    out = await FbMarketplaceProvider().search("Honda", "Civic")
    assert out == []


@pytest.mark.asyncio
async def test_kavak_stub_returns_empty() -> None:
    out = await KavakProvider().search("Honda", "Civic")
    assert out == []


# ---------------------------------------------------------------------------
# Despachador


@pytest.mark.asyncio
async def test_find_cross_listings_aggregates_results() -> None:
    """Despachador combina resultados de varios providers."""
    fake_viva = AsyncMock()
    fake_viva.name = "vivanuncios"
    fake_viva.search = AsyncMock(return_value=[
        CrossListing(marketplace="vivanuncios", title="Honda Civic 2018", price_mxn=250000, url="x"),
    ])
    fake_semi = AsyncMock()
    fake_semi.name = "seminuevos"
    fake_semi.search = AsyncMock(return_value=[
        CrossListing(marketplace="seminuevos", title="Honda Civic 2018 LX", price_mxn=240000, url="y"),
    ])

    result = await find_cross_listings(
        "Honda", "Civic", 2018, providers=[fake_viva, fake_semi]
    )
    assert result.count == 2
    assert {l.marketplace for l in result.listings} == {"vivanuncios", "seminuevos"}


@pytest.mark.asyncio
async def test_find_cross_listings_provider_failure_isolated() -> None:
    """Si un provider lanza excepción, los demás siguen funcionando."""
    bad = AsyncMock()
    bad.name = "vivanuncios"
    bad.search = AsyncMock(side_effect=RuntimeError("HTML changed"))

    good = AsyncMock()
    good.name = "seminuevos"
    good.search = AsyncMock(return_value=[
        CrossListing(marketplace="seminuevos", title="Honda Civic 2018", price_mxn=240000, url="y"),
    ])

    result = await find_cross_listings(
        "Honda", "Civic", providers=[bad, good]
    )
    assert result.count == 1
    assert result.listings[0].marketplace == "seminuevos"


@pytest.mark.asyncio
async def test_find_cross_listings_empty_make_model_returns_empty() -> None:
    result = await find_cross_listings("", "")
    assert result.count == 0


@pytest.mark.asyncio
async def test_find_cross_listings_with_real_providers_returns_result() -> None:
    """Smoke con providers reales pero make falso — debería devolver
    listings=[] sin lanzar excepciones (los providers reales fallan
    limpio con HTML que no parsea o site que retorna 404)."""
    result = await find_cross_listings(
        "MakeQueNoExiste", "ModeloQueNoExiste", 2018
    )
    # Aceptamos lista vacía o resultados mínimos — lo importante es no exception
    assert isinstance(result.count, int)
