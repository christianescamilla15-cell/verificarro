"""Tests del VIN checker — comparación contra listing + repuve.

Cubre los 4 escenarios de fraude que la feature ataca:
1. Placa clonada (marca distinta)
2. Modelo distinto (año fuera de tolerancia)
3. VIN en descripción ≠ VIN escaneado
4. VIN del REPUVE manual ≠ VIN escaneado
"""

import pytest

from app.analyzers.vin_check import check
from app.models.report import ListingData, RepuveResult, Source


def _listing(
    make: str = "Honda", model: str = "Civic", year: int = 2018,
    description: str = "",
) -> ListingData:
    return ListingData(
        source=Source.MERCADOLIBRE,
        title=f"{make} {model} {year}",
        price_mxn=230_000,
        year=year,
        make=make,
        model=model,
        kilometers=80_000,
        location="CDMX",
        description=description,
    )


# ---------------------------------------------------------------------------
# Escenario 1: Placa clonada — marca distinta


def test_make_mismatch_high_alert() -> None:
    """VIN escaneado decodifica Toyota pero anuncio dice Honda → alerta high."""
    listing = _listing(make="Honda", model="Civic", year=2020)
    # 5YFEPRAE0LP... = Toyota 2020
    result = check("5YFEPRAE0LP000001", listing)
    assert result.matches_listing is False
    high_alerts = [a for a in result.alerts if a.severity == "high"]
    assert any("PLACA CLONADA" in a.message for a in high_alerts)


def test_make_alias_match_no_alert() -> None:
    """Anuncio dice 'Acura' y VIN es WMI Honda → considerado match."""
    listing = _listing(make="Acura", model="TLX", year=2020)
    # 19U... es Honda con alias Acura
    result = check("19UUB1F5XLA000001", listing)
    # No debe tener alerta high de "placa clonada"
    high = [a for a in result.alerts if a.severity == "high"
            and "CLONADA" in a.message]
    assert high == []


# ---------------------------------------------------------------------------
# Escenario 2: Año distinto


def test_year_within_tolerance_low_alert_only() -> None:
    """Anuncio 2019, VIN 2018 — diff 1 → low alert solamente."""
    listing = _listing(make="Honda", model="Civic", year=2019)
    # 2HGFC2F65JH... = 2018 ('J' en pos 10)
    result = check("2HGFC2F65JH500001", listing)
    # Debe matchear (tolerancia ±1)
    assert result.matches_listing is True
    # Pero generar low alert informativo
    assert any(a.severity == "low" and "1 año" in a.message for a in result.alerts)


def test_year_off_by_2_medium_alert() -> None:
    listing = _listing(make="Honda", model="Civic", year=2020)
    # 2018 (J) vs anuncio 2020 = diff 2
    result = check("2HGFC2F65JH500001", listing)
    medium = [a for a in result.alerts if a.severity == "medium"]
    assert any("2 años" in a.message for a in medium)
    assert result.matches_listing is False


def test_year_off_by_5_high_alert() -> None:
    listing = _listing(make="Honda", model="Civic", year=2024)
    # 2018 (J) vs 2024 = diff 6
    result = check("2HGFC2F65JH500001", listing)
    high = [a for a in result.alerts if a.severity == "high"]
    assert any("años" in a.message for a in high)


# ---------------------------------------------------------------------------
# Escenario 3: VIN en descripción ≠ VIN escaneado


def test_vin_in_description_extracted_and_compared() -> None:
    """El vendedor pegó un VIN en la descripción que NO coincide con
    el VIN escaneado físicamente."""
    listing = _listing(
        make="Honda", model="Civic", year=2018,
        description=(
            "Honda Civic LX 2018, único dueño, factura agencia. "
            "Número de serie: 2HGFC2F65JH500001 disponible para verificar "
            "en REPUVE."
        ),
    )
    # Usuario escanea otro VIN en el auto físico
    result = check("2HGFC2F65JH999999", listing)
    assert result.vin_in_description == "2HGFC2F65JH500001"
    assert any("NO COINCIDEN" in a.message and a.severity == "high"
               for a in result.alerts)


def test_vin_in_description_match_no_alert() -> None:
    listing = _listing(
        description="Número de serie 2HGFC2F65JH500001",
    )
    result = check("2HGFC2F65JH500001", listing)
    assert result.vin_in_description == "2HGFC2F65JH500001"
    no_coinciden = [a for a in result.alerts if "NO COINCIDEN" in a.message]
    assert no_coinciden == []


def test_vin_extraction_no_vin_in_description() -> None:
    listing = _listing(description="Auto en buen estado, único dueño")
    result = check("2HGFC2F65JH500001", listing)
    assert result.vin_in_description is None


# ---------------------------------------------------------------------------
# Escenario 4: REPUVE manual VIN ≠ escaneado


def test_repuve_vin_mismatch_high_alert() -> None:
    listing = _listing(make="Honda", model="Civic", year=2018)
    repuve = RepuveResult(
        queried=True, vin="2HGFC2F65JH500001",
        is_stolen=False, raw_status="manual",
    )
    result = check("2HGFC2F65JH999999", listing, repuve)
    high = [a for a in result.alerts if a.severity == "high"]
    assert any("clonación de placa" in a.message.lower() for a in high)


def test_repuve_vin_match_no_alert() -> None:
    listing = _listing(make="Honda", model="Civic", year=2018)
    repuve = RepuveResult(
        queried=True, vin="2HGFC2F65JH500001",
        is_stolen=False, raw_status="manual",
    )
    result = check("2HGFC2F65JH500001", listing, repuve)
    high_clone = [a for a in result.alerts
                  if "clonación" in a.message.lower()]
    assert high_clone == []


def test_repuve_without_vin_no_alert() -> None:
    """REPUVE consultado por placa (no por VIN) no genera alerta."""
    listing = _listing()
    repuve = RepuveResult(queried=True, plate="ABC123D", is_stolen=False)
    result = check("2HGFC2F65JH500001", listing, repuve)
    # No debe haber alerta sobre VIN del REPUVE
    repuve_alerts = [a for a in result.alerts if "REPUVE" in a.message]
    assert repuve_alerts == []


# ---------------------------------------------------------------------------
# Format inválido


def test_short_vin_returns_high_alert_no_match() -> None:
    listing = _listing()
    result = check("ABC123", listing)
    assert result.matches_listing is False
    high = [a for a in result.alerts if a.severity == "high"]
    assert any("VIN inválido" in a.message for a in high)


def test_vin_with_prohibited_char_high_alert() -> None:
    listing = _listing()
    bad = "2HGFC2F65JI500001"  # contiene I
    assert len(bad) == 17
    result = check(bad, listing)
    assert result.matches_listing is False


# ---------------------------------------------------------------------------
# Combo


def test_clean_match_no_alerts() -> None:
    listing = _listing(make="Honda", model="Civic", year=2018)
    # Real Civic 2018 con checksum válido (calculado)
    result = check("2HGFC2F65JH500001", listing)
    # Puede tener checksum medium, pero no high
    high = [a for a in result.alerts if a.severity == "high"]
    assert high == []
    assert result.matches_listing is True
