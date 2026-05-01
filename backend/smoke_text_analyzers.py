"""Smoke local de description + seller analyzers.

Sin red, sin API. Corre los dos analyzers contra:
1. La descripción real del Kia Seltos validada en D2 (debe ser limpia).
2. Una descripción de estafa-clásica sintética (debe disparar varias).

Sirve como sanity check rápido antes de commitear D6.
"""

import json

from app.analyzers import description_analyzer, seller_analyzer
from app.models.report import ListingData, Source


# Descripción real del Kia Seltos extraída por el scraper de D2 el 2026-04-30.
KIA_SELTOS_DESCRIPTION = (
    "KIA SELTOS SX 2025 – ÚLTIMA UNIDAD DISPONIBLE | PRECIO DE REMATE\n"
    "Aprovecha esta oportunidad única. Se trata de la última Kia Seltos SX "
    "modelo 2025 disponible, con precio especial de remate y entrega inmediata.\n"
    "Vehículo completamente nuevo, ideal para quien busca estrenar con un "
    "ahorro real frente a modelos 2026.\n"
    "Características principales: motor 1.5L, transmisión automática IVT, "
    "pantalla táctil, Apple CarPlay, cámara de reversa, 6 bolsas de aire."
)


SCAM_DESCRIPTION = (
    "¡URGE VENDER! Estoy en el extranjero, me mudé a Texas por trabajo. "
    "El auto está en CDMX con un familiar. No se permite revisión antes de "
    "la compra, solo whatsapp. Te lo envío desde Texas cuando me deposites "
    "el anticipo de $5,000 vía Western Union para apartar."
)


def _print_findings(label: str, findings) -> None:
    print(f"\n--- {label} ---")
    if not findings:
        print("  (cero hallazgos — limpia)")
        return
    for f in findings:
        d = f.model_dump(mode="json")
        print(f"  · [{d['severity']}] {d.get('flag')}: {d.get('excerpt') or d.get('note')}")


def main() -> int:
    print("=" * 70)
    print("CASO 1: Descripción REAL del Kia Seltos 2025 (concesionario)")
    print("=" * 70)
    real_findings = description_analyzer.analyze(KIA_SELTOS_DESCRIPTION)
    _print_findings("description_findings", real_findings)

    real_seller = seller_analyzer.analyze(
        ListingData(
            source=Source.MERCADOLIBRE,
            title="Kia Seltos 1.5 SX",
            price_mxn=489900, year=2025, make="Kia", model="Seltos",
            kilometers=0, location="Benito Juárez, Distrito Federal",
            seller_name="",  # ML no expuso nombre del concesionario
            seller_account_age_days=None,
        )
    )
    _print_findings("seller_findings", real_seller)

    print("\n" + "=" * 70)
    print("CASO 2: Descripción de ESTAFA-CLÁSICA sintética")
    print("=" * 70)
    scam_findings = description_analyzer.analyze(SCAM_DESCRIPTION)
    _print_findings("description_findings", scam_findings)

    scam_seller = seller_analyzer.analyze(
        ListingData(
            source=Source.MERCADOLIBRE,
            title="Honda Civic 2018",
            price_mxn=180000, year=2018, make="Honda", model="Civic",
            kilometers=80000, location="CDMX",
            seller_name="user98765",
            seller_account_age_days=12,
        )
    )
    _print_findings("seller_findings", scam_seller)

    # Validaciones de sanidad
    if real_findings:
        print("\n[smoke] WARN: anuncio limpio del Kia generó hallazgos — revisar regexes")
        print(json.dumps([f.model_dump(mode="json") for f in real_findings], indent=2))
        return 1

    expected_scam_flags = {
        "urgency", "seller_abroad", "advance_payment_request",
        "no_inspection_allowed",
    }
    found_flags = {f.flag for f in scam_findings}
    missing = expected_scam_flags - found_flags
    if missing:
        print(f"\n[smoke] FAIL: scam description no detectó flags: {missing}")
        return 1

    if not any(f.flag == "new_account" and f.severity == "high" for f in scam_seller):
        print("\n[smoke] FAIL: vendedor con cuenta de 12 días debió disparar new_account high")
        return 1

    print(
        f"\n[smoke] OK — Kia limpio (0 flags), scam disparó "
        f"{len(scam_findings)} flags de descripción + {len(scam_seller)} de vendedor"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
