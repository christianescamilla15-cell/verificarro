"""Smoke del PDF generator: arma un Report sintético y escribe 2 PDFs.

1. `report_clean.pdf` — anuncio limpio (Honda Civic agencia)
2. `report_scam.pdf` — estafa-clásica con varios red flags

Sirve como regression check visual antes de lanzar.

Uso:
    python smoke_pdf.py
    # abre los dos PDFs generados en backend/
"""

from pathlib import Path

from app.analyzers.scoring import populate
from app.models.report import (
    DescriptionFinding,
    ListingData,
    PhotoFinding,
    PriceEstimate,
    Report,
    RepuveResult,
    RiskLevel,
    SellerFinding,
    Source,
)
from app.services.pdf_report import generate_pdf


def _clean_report() -> Report:
    rep = Report(
        score=0,
        risk_level=RiskLevel.RED,
        summary="",
        listing=ListingData(
            source=Source.MERCADOLIBRE,
            source_url="https://auto.mercadolibre.com.mx/MLM-1234-honda-civic-2018",
            title="Honda Civic Lx 2018 4p Aut",
            price_mxn=230_000,
            year=2018,
            make="Honda",
            model="Civic",
            kilometers=78_500,
            location="Benito Juárez, Distrito Federal",
            seller_name="Juan Pérez",
            seller_account_age_days=720,
        ),
        repuve=RepuveResult(
            queried=True, plate="ABC123D", is_stolen=False,
            has_legal_status=True, raw_status="sin_reportes",
        ),
        price=PriceEstimate(
            fair_price_mxn=235_000, range_low_mxn=210_000,
            range_high_mxn=265_000, delta_pct=-2.1,
            comparables_count=12, sources=["mercadolibre"],
        ),
        photo_findings=[],
        description_findings=[],
        seller_findings=[],
        questions_for_seller=[
            "¿Tienes la factura original y el endoso completo?",
            "¿Me dejas verificarlo en una agencia o con mi mecánico?",
            "¿Por qué lo vendes y desde cuándo lo tienes?",
        ],
    )
    return populate(rep)


def _scam_report() -> Report:
    rep = Report(
        score=0,
        risk_level=RiskLevel.RED,
        summary="",
        listing=ListingData(
            source=Source.MERCADOLIBRE,
            source_url="https://auto.mercadolibre.com.mx/MLM-9999-honda-civic-2018",
            title="Honda Civic 2018 - URGE VENDER",
            price_mxn=120_000,
            year=2018,
            make="Honda",
            model="Civic",
            kilometers=80_000,
            location="CDMX",
            seller_name="user98765",
            seller_account_age_days=12,
        ),
        repuve=RepuveResult(
            queried=False, plate="XYZ789A",
            raw_status="captcha_required",
            error="REPUVE pidió reCaptcha. Consulta manualmente y pega el resultado.",
        ),
        price=PriceEstimate(
            fair_price_mxn=235_000, range_low_mxn=210_000,
            range_high_mxn=265_000, delta_pct=-48.9,
            comparables_count=12, sources=["mercadolibre"],
        ),
        photo_findings=[
            PhotoFinding(
                photo_index=0, issue="paint_mismatch", severity="high",
                note="Cofre con tono distinto al resto, posible repintado",
            ),
            PhotoFinding(
                photo_index=2, issue="prior_repair", severity="medium",
                note="Marca de masilla visible cerca de la salpicadera",
            ),
            PhotoFinding(
                photo_index=4, issue="low_quality", severity="low",
                note="Foto borrosa, no se evalúa bien",
            ),
        ],
        description_findings=[
            DescriptionFinding(
                flag="urgency", severity="medium",
                excerpt="vendedor expresa urgencia: '¡URGE VENDER!'",
            ),
            DescriptionFinding(
                flag="seller_abroad", severity="high",
                excerpt="vendedor declara residir en el extranjero: '...vivo en Texas...'",
            ),
            DescriptionFinding(
                flag="advance_payment_request", severity="high",
                excerpt="envío condicionado al pago previo: '...cuando me deposites...'",
            ),
            DescriptionFinding(
                flag="no_inspection_allowed", severity="high",
                excerpt="no permite revisión mecánica: '...no se permite revisión antes...'",
            ),
        ],
        seller_findings=[
            SellerFinding(
                flag="new_account", severity="high",
                note="Cuenta del vendedor tiene 12 días — riesgo alto",
            ),
            SellerFinding(
                flag="new_account", severity="medium",
                note="Nombre de vendedor genérico/aleatorio: 'user98765'",
            ),
        ],
        questions_for_seller=[
            "¿Tienes la factura original y el endoso completo?",
            "¿Me dejas verificarlo en una agencia o con mi mecánico?",
            "¿Por qué lo vendes y desde cuándo lo tienes?",
        ],
    )
    return populate(rep)


def main() -> int:
    out_dir = Path(".")

    clean = _clean_report()
    print(f"[smoke] CLEAN report — score={clean.score} risk={clean.risk_level.value}")
    pdf_clean = generate_pdf(clean)
    (out_dir / "report_clean.pdf").write_bytes(pdf_clean)
    print(f"  → report_clean.pdf  ({len(pdf_clean):,} bytes)")

    scam = _scam_report()
    print(f"[smoke] SCAM  report — score={scam.score} risk={scam.risk_level.value}")
    pdf_scam = generate_pdf(scam)
    (out_dir / "report_scam.pdf").write_bytes(pdf_scam)
    print(f"  → report_scam.pdf   ({len(pdf_scam):,} bytes)")

    if clean.risk_level.value != "green":
        print("[smoke] FAIL: clean debió clasificarse green")
        return 1
    if scam.risk_level.value != "red":
        print("[smoke] FAIL: scam debió clasificarse red")
        return 1
    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
