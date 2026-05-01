"""Tests del cliente NHTSA vPIC + integración con vin_check.

No hace red real: usa httpx_mock o patch sobre `httpx.AsyncClient.get`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.analyzers import vin_check
from app.models.report import ListingData, Source
from app.services.nhtsa import (
    NhtsaDecodeResult,
    decode_vin,
    parse_response,
)


# ---------------------------------------------------------------------------
# parse_response


def _vpic_payload(variables: dict[str, str]) -> dict:
    """Construye un payload vPIC desde un dict {Variable: Value}."""
    return {
        "Count": len(variables),
        "Message": "Results returned successfully",
        "Results": [
            {"Variable": var, "Value": val, "ValueId": ""}
            for var, val in variables.items()
        ],
    }


def test_parse_response_full_honda_civic() -> None:
    payload = _vpic_payload({
        "Make": "HONDA",
        "Model": "Civic",
        "Model Year": "2018",
        "Body Class": "Sedan/Saloon",
        "Vehicle Type": "PASSENGER CAR",
        "Trim": "EX",
        "Engine Number of Cylinders": "4",
        "Displacement (L)": "1.5",
        "Fuel Type - Primary": "Gasoline",
        "Transmission Style": "Continuously Variable Transmission (CVT)",
        "Drive Type": "FWD/Front-Wheel Drive",
        "Doors": "4",
        "Plant Country": "MEXICO",
        "Plant City": "EL SALTO",
    })
    out = parse_response("19XFC2F58JE000001", payload)
    assert out.found is True
    assert out.make == "HONDA"
    assert out.model == "Civic"
    assert out.model_year == 2018
    assert out.body_class == "Sedan/Saloon"
    assert out.engine_cylinders == 4
    assert out.engine_displacement_l == 1.5
    assert out.doors == 4
    assert out.plant_country == "MEXICO"
    assert out.plant_city == "EL SALTO"


def test_parse_response_partial_returns_not_found() -> None:
    """Si vPIC no resuelve make/model/year, found=False."""
    payload = _vpic_payload({
        "Error Code": "1",
        "Error Text": "Check Digit (9th position) does not calculate properly",
    })
    out = parse_response("INVALIDVIN0000000", payload)
    assert out.found is False
    assert out.make is None
    assert out.error_code == "1"


def test_parse_response_skips_not_applicable() -> None:
    payload = _vpic_payload({
        "Make": "TOYOTA",
        "Model": "Corolla",
        "Model Year": "2020",
        "Engine Number of Cylinders": "Not Applicable",
        "Displacement (L)": "",
    })
    out = parse_response("JTDEPRAE9LJ000001", payload)
    assert out.found is True
    assert out.make == "TOYOTA"
    assert out.engine_cylinders is None
    assert out.engine_displacement_l is None


def test_parse_response_coerces_numeric_strings() -> None:
    payload = _vpic_payload({
        "Make": "HONDA",
        "Model": "Civic",
        "Model Year": "2018",
        "Doors": "4.0",  # Algunos fields vienen como float string
        "Engine Power (kW)": "117.0",
    })
    out = parse_response("V" * 17, payload)
    assert out.doors == 4
    assert out.engine_kw == 117.0


# ---------------------------------------------------------------------------
# decode_vin (HTTP)


@pytest.mark.asyncio
async def test_decode_vin_returns_none_on_invalid_length() -> None:
    """Sin red — VIN inválido devuelve None sin llamar a NHTSA."""
    out = await decode_vin("ABC123")
    assert out is None


@pytest.mark.asyncio
async def test_decode_vin_calls_nhtsa_and_parses() -> None:
    payload = _vpic_payload({
        "Make": "HONDA",
        "Model": "Civic",
        "Model Year": "2018",
        "Body Class": "Sedan/Saloon",
    })

    async def _mock_get(self, url):  # noqa: ARG001
        return httpx.Response(
            200, json=payload, request=httpx.Request("GET", url)
        )

    with patch.object(httpx.AsyncClient, "get", _mock_get):
        out = await decode_vin("19XFC2F58JE000001")

    assert out is not None
    assert out.found is True
    assert out.make == "HONDA"
    assert out.body_class == "Sedan/Saloon"


@pytest.mark.asyncio
async def test_decode_vin_returns_none_on_timeout() -> None:
    """Si NHTSA tarda más del timeout, devolvemos None (graceful degrade)."""
    async def _raise_timeout(self, url):  # noqa: ARG001
        raise httpx.TimeoutException("simulated")

    with patch.object(httpx.AsyncClient, "get", _raise_timeout):
        out = await decode_vin("19XFC2F58JE000001")
    assert out is None


@pytest.mark.asyncio
async def test_decode_vin_returns_none_on_http_error() -> None:
    async def _raise_500(self, url):  # noqa: ARG001
        return httpx.Response(
            500, text="server error", request=httpx.Request("GET", url)
        )

    with patch.object(httpx.AsyncClient, "get", _raise_500):
        out = await decode_vin("19XFC2F58JE000001")
    assert out is None


# ---------------------------------------------------------------------------
# Integración con vin_check.check_with_enrichment


def _listing(make: str, year: int, title: str = "") -> ListingData:
    return ListingData(
        source=Source.MERCADOLIBRE,
        title=title or f"{make} 2018",
        price_mxn=300_000,
        year=year,
        make=make,
        model="Civic",
        kilometers=50_000,
        location="CDMX",
    )


@pytest.mark.asyncio
async def test_check_with_enrichment_no_nhtsa_falls_back() -> None:
    """Si NHTSA falla, el check sync sigue funcionando."""
    listing = _listing("Honda", 2018, "Honda Civic 2018 EX")
    with patch(
        "app.analyzers.vin_check.nhtsa_decode",
        new=AsyncMock(return_value=None),
    ):
        result = await vin_check.check_with_enrichment(
            raw_vin="19XFC2F58JE000001", listing=listing
        )
    assert result.nhtsa is None
    assert result.matches_listing is True


@pytest.mark.asyncio
async def test_check_with_enrichment_body_class_mismatch_alerts() -> None:
    """VIN dice 'SUV' pero anuncio dice 'sedán' → high alert."""
    listing = _listing("Honda", 2018, "Honda CR-V SUV 2018 — todo terreno")
    fake_nhtsa = NhtsaDecodeResult(
        raw_vin="V" * 17,
        found=True,
        make="HONDA",
        model="Civic",
        model_year=2018,
        body_class="Sedan/Saloon",  # ← VIN físico es sedán
    )
    with patch(
        "app.analyzers.vin_check.nhtsa_decode",
        new=AsyncMock(return_value=fake_nhtsa),
    ):
        result = await vin_check.check_with_enrichment(
            raw_vin="19XFC2F58JE000001", listing=listing
        )
    assert result.nhtsa is not None
    assert any(
        a.severity == "high" and "carrocería" in a.message.lower()
        for a in result.alerts
    )
    assert result.matches_listing is False


@pytest.mark.asyncio
async def test_check_with_enrichment_make_mismatch_via_nhtsa() -> None:
    """Listing dice Honda, NHTSA dice TOYOTA → high alert."""
    listing = _listing("Honda", 2018, "Honda Civic 2018")
    fake_nhtsa = NhtsaDecodeResult(
        raw_vin="V" * 17,
        found=True,
        make="TOYOTA",
        model="Corolla",
        model_year=2018,
    )
    with patch(
        "app.analyzers.vin_check.nhtsa_decode",
        new=AsyncMock(return_value=fake_nhtsa),
    ):
        result = await vin_check.check_with_enrichment(
            raw_vin="JTDEPRAE9LJ000001", listing=listing
        )
    # Debe haber al menos una alert high con NHTSA en el mensaje
    assert any(
        a.severity == "high" and "NHTSA" in a.message
        for a in result.alerts
    )


@pytest.mark.asyncio
async def test_check_with_enrichment_make_alias_no_alert() -> None:
    """NHTSA 'MERCEDES-BENZ' vs listing 'Mercedes Benz' no debería alertar."""
    listing = _listing("Mercedes Benz", 2018, "Mercedes Benz C-Class 2018")
    fake_nhtsa = NhtsaDecodeResult(
        raw_vin="V" * 17,
        found=True,
        make="MERCEDES-BENZ",
        model="C-Class",
        model_year=2018,
    )
    with patch(
        "app.analyzers.vin_check.nhtsa_decode",
        new=AsyncMock(return_value=fake_nhtsa),
    ):
        result = await vin_check.check_with_enrichment(
            raw_vin="WDDGF4HB1FA000001", listing=listing
        )
    # No debe haber alert "NHTSA reporta que el VIN físico es 'MERCEDES-BENZ'"
    assert not any(
        "NHTSA reporta que el VIN físico es 'MERCEDES-BENZ'" in a.message
        for a in result.alerts
    )


@pytest.mark.asyncio
async def test_check_with_enrichment_clean_pass() -> None:
    """VIN+NHTSA+listing todos coinciden → matches=True, sin alerts high."""
    listing = _listing("HONDA", 2018, "Honda Civic 2018 sedán EX")
    fake_nhtsa = NhtsaDecodeResult(
        raw_vin="19XFC2F58JE000001",
        found=True,
        make="HONDA",
        model="Civic",
        model_year=2018,
        body_class="Sedan/Saloon",
    )
    with patch(
        "app.analyzers.vin_check.nhtsa_decode",
        new=AsyncMock(return_value=fake_nhtsa),
    ):
        result = await vin_check.check_with_enrichment(
            raw_vin="19XFC2F58JE000001", listing=listing
        )
    assert result.nhtsa is not None
    assert result.matches_listing is True
    assert not any(a.severity == "high" for a in result.alerts)
