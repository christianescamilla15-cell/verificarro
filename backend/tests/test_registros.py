"""Consultas a registros oficiales dentro del pipeline (docs/reglas.md).

- SAT: una factura CANCELADA o NO ENCONTRADA es bandera grave en el
  reporte; una vigente no castiga.
- REPUVE en el preview gratuito: sin consulta no se puede decir «verde»
  (tope 50/amarillo); robado manda a rojo; con situación legal irregular
  el resumen lo dice aunque el puntaje numérico quede alto.

Todo con los pasos de red simulados: las pruebas no salen a internet.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.report import (
    AnalyzeRequest,
    InvoiceData,
    ManualListing,
    PriceEstimate,
    RepuveResult,
    RiskLevel,
    Source,
)
from app.services.pipeline import orchestrator
from app.services.pipeline.orchestrator import run_pipeline, run_preview_pipeline

_ORQ = "app.services.pipeline.orchestrator"


def _request() -> AnalyzeRequest:
    return AnalyzeRequest(
        source=Source.FACEBOOK,
        manual_listing=ManualListing(
            title="Honda Civic 2018 LX", price_mxn=230_000, year=2018,
            make="Honda", model="Civic", kilometers=78_000, location="CDMX",
            description="Único dueño, factura de agencia", seller_name="Juan",
            photo_urls=[],
        ),
        invoice_number="6F9619FF-8B86-D011-B42D-00C04FC964FF",
    )


async def _run_with_sat(sat_status: str | None):
    invoice = InvoiceData(
        invoice_number="6F9619FF-8B86-D011-B42D-00C04FC964FF",
        folio_fiscal_uuid="6F9619FF-8B86-D011-B42D-00C04FC964FF",
        sat_status=sat_status,
    )
    with patch(f"{_ORQ}.resolve_repuve", new=AsyncMock(
        return_value=RepuveResult(queried=True, is_stolen=False, has_legal_status=True),
    )), patch(f"{_ORQ}.resolve_price", new=AsyncMock(
        return_value=PriceEstimate(comparables_count=0),
    )), patch(f"{_ORQ}.resolve_photos", new=AsyncMock(return_value=[])), patch(
        f"{_ORQ}.resolve_exif", new=AsyncMock(return_value=[]),
    ), patch(f"{_ORQ}.resolve_cross_listings", new=AsyncMock(return_value=[])), patch(
        f"{_ORQ}.build_invoice_data_with_verification", new=AsyncMock(return_value=invoice),
    ):
        return await run_pipeline(_request())


@pytest.mark.asyncio
@pytest.mark.parametrize("sat_status", ["cancelado", "no_encontrado"])
async def test_sat_cancelled_or_missing_invoice_is_high_flag(sat_status: str) -> None:
    report = await _run_with_sat(sat_status)
    graves = [f for f in report.description_findings if f.severity == "high"]
    assert len(graves) == 1
    assert "SAT" in graves[0].excerpt
    # Una bandera grave en descripción castiga 10 puntos.
    limpio = await _run_with_sat("vigente")
    assert report.score == limpio.score - 10


@pytest.mark.asyncio
async def test_sat_valid_invoice_adds_no_flag() -> None:
    report = await _run_with_sat("vigente")
    assert not [f for f in report.description_findings if "SAT" in f.excerpt]
    assert report.invoice is not None and report.invoice.sat_status == "vigente"


# ---------------------------------------------------------------------------
# REPUVE en el preview gratuito


async def _preview(repuve: RepuveResult):
    with patch.object(orchestrator, "run_repuve_preview", new=AsyncMock(return_value=repuve)):
        return await run_preview_pipeline(plate="ABC123D")


@pytest.mark.asyncio
async def test_preview_requires_plate_or_vin() -> None:
    with pytest.raises(ValueError):
        await run_preview_pipeline(plate=None, vin=None)


@pytest.mark.asyncio
async def test_preview_without_repuve_is_capped_to_yellow_50() -> None:
    report = await _preview(RepuveResult(queried=False, raw_status="captcha_required"))
    assert (report.score, report.risk_level) == (50, RiskLevel.YELLOW)


@pytest.mark.asyncio
async def test_preview_clean_repuve_can_be_green() -> None:
    report = await _preview(RepuveResult(queried=True, is_stolen=False, has_legal_status=True))
    assert report.risk_level == RiskLevel.GREEN
    assert "no muestra reporte de robo" in report.summary


@pytest.mark.asyncio
async def test_preview_stolen_is_red_with_alert() -> None:
    report = await _preview(RepuveResult(queried=True, is_stolen=True))
    assert report.risk_level == RiskLevel.RED
    assert "ROBADO" in report.summary


@pytest.mark.asyncio
async def test_preview_legal_irregular_is_called_out_in_summary() -> None:
    """Situación legal irregular castiga 25 (75/100). El resumen la nombra y
    no usa el texto de «sin reporte de robo» aunque el puntaje sea alto."""
    report = await _preview(RepuveResult(queried=True, is_stolen=False, has_legal_status=False))
    assert report.score == 75
    assert "situación legal irregular" in report.summary
    assert "no muestra reporte de robo" not in report.summary
