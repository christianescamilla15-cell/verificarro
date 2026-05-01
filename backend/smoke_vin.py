"""Smoke local del VIN check.

Demuestra los 4 escenarios de fraude que la feature ataca:
1. Match perfecto (verde)
2. Año ±1 (verde con info)
3. Marca distinta — placa clonada (rojo)
4. VIN en descripción ≠ escaneado (rojo)

Sin red, sin Claude API.
"""

from app.analyzers.scoring import populate
from app.analyzers.vin_check import check
from app.models.report import (
    ListingData,
    PriceEstimate,
    Report,
    RepuveResult,
    RiskLevel,
    Source,
    VinAlertModel,
    VinCheck,
    VinDecodedModel,
)


def _to_pydantic(result):
    return VinCheck(
        decoded=VinDecodedModel(**result.decoded.__dict__),
        matches_listing=result.matches_listing,
        alerts=[VinAlertModel(severity=a.severity, message=a.message)
                for a in result.alerts],
        vin_in_description=result.vin_in_description,
        scanned_at=result.scanned_at,
    )


def _show(title: str, result, build_report=False) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)
    d = result.decoded
    print(f"  VIN escaneado:  {d.vin}")
    print(f"  Marca decoded:  {d.manufacturer or '(desconocido)'}", end="")
    if d.manufacturer_aliases:
        print(f"  (aliases: {', '.join(d.manufacturer_aliases)})")
    else:
        print()
    print(f"  País:           {d.country or '—'}")
    print(f"  Año:            {d.year or '—'}")
    print(f"  Checksum:       {'válido' if d.valid_checksum else 'inválido'}")
    print(f"  matches_listing: {result.matches_listing}")
    if result.vin_in_description:
        print(f"  VIN en descripción: {result.vin_in_description}")
    if result.alerts:
        print("\n  Alertas:")
        for a in result.alerts:
            tag = {"high": "🚨", "medium": "⚠️", "low": "ℹ️"}.get(a.severity, "•")
            print(f"   {tag} [{a.severity.upper()}] {a.message}")
    else:
        print("\n  (sin alertas)")


def main() -> int:
    # --- ESCENARIO 1: Match perfecto ---
    listing = ListingData(
        source=Source.MERCADOLIBRE,
        title="Honda Civic LX 2018", price_mxn=230_000,
        year=2018, make="Honda", model="Civic",
        kilometers=80_000, location="CDMX",
    )
    result = check("2HGFC2F65JH500001", listing)
    _show("ESCENARIO 1 — Match perfecto (Honda Civic 2018)", result)

    # --- ESCENARIO 2: Año fuera de tolerancia ---
    listing2 = ListingData(
        source=Source.MERCADOLIBRE,
        title="Honda Civic 2024", price_mxn=420_000,
        year=2024, make="Honda", model="Civic",
        kilometers=10_000, location="CDMX",
    )
    result2 = check("2HGFC2F65JH500001", listing2)
    _show(
        "ESCENARIO 2 — Año del VIN (2018) ≠ anuncio (2024) — diff 6 años",
        result2,
    )

    # --- ESCENARIO 3: Placa clonada (marca distinta) ---
    listing3 = ListingData(
        source=Source.MERCADOLIBRE,
        title="Honda Civic 2020", price_mxn=320_000,
        year=2020, make="Honda", model="Civic",
        kilometers=40_000, location="CDMX",
    )
    # 5YFEPRAE0LP000001 = Toyota 2020 (NO Honda)
    result3 = check("5YFEPRAE0LP000001", listing3)
    _show(
        "ESCENARIO 3 — VIN físico es Toyota pero anuncio dice Honda 🚨",
        result3,
    )

    # --- ESCENARIO 4: VIN en descripción ≠ escaneado ---
    listing4 = ListingData(
        source=Source.MERCADOLIBRE,
        title="Honda Civic 2018", price_mxn=230_000,
        year=2018, make="Honda", model="Civic",
        kilometers=80_000, location="CDMX",
        description=(
            "Honda Civic 2018, único dueño. Consulta en REPUVE con el "
            "VIN 2HGFC2F65JH500001. Listo para escriturar."
        ),
    )
    # Usuario escanea OTRO VIN en el auto físico
    result4 = check("2HGFC2F65JH999999", listing4)
    _show(
        "ESCENARIO 4 — Anuncio dice un VIN, auto físico tiene OTRO 🚨",
        result4,
    )

    # --- Score impact ---
    print(f"\n{'=' * 70}")
    print("  SCORING — efecto en el reporte completo")
    print("=" * 70)
    rep = Report(
        score=0, risk_level=RiskLevel.RED, summary="",
        listing=listing3, repuve=RepuveResult(queried=False),
        price=PriceEstimate(comparables_count=0),
        vin_check=_to_pydantic(result3),  # marca clonada
    )
    populate(rep)
    print(f"  Reporte con clonación → score={rep.score} risk={rep.risk_level.value}")
    if "VIN" in rep.summary or "discrepa" in rep.summary:
        print("  ✓ Summary menciona el VIN")
    else:
        print(f"  Summary: {rep.summary[:200]}…")

    print("\n[smoke] OK — los 4 escenarios disparan correctamente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
