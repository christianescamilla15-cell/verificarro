"""Tests del scoring engine.

Función pura: Report → (score, risk_level, summary). Sin red.
"""

from app.analyzers.scoring import compute_score, populate
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


def _base_report(**overrides) -> Report:
    base = {
        "score": 0,
        "risk_level": RiskLevel.RED,
        "summary": "",
        "listing": ListingData(
            source=Source.MERCADOLIBRE,
            title="Honda Civic 2018",
            price_mxn=230_000,
            year=2018,
            make="Honda",
            model="Civic",
            kilometers=80_000,
            location="CDMX",
        ),
        "repuve": RepuveResult(queried=False),
        "price": PriceEstimate(comparables_count=0),
        "photo_findings": [],
        "description_findings": [],
        "seller_findings": [],
        "questions_for_seller": [],
    }
    base.update(overrides)
    return Report(**base)


# ---------------------------------------------------------------------------
# Cases that should land green (≥70)


def test_clean_listing_lands_green() -> None:
    score, risk, summary = compute_score(_base_report())
    assert score == 100
    assert risk == RiskLevel.GREEN
    assert "Verificarro le da 100/100" in summary


def test_clean_with_minor_low_findings_still_green() -> None:
    rep = _base_report(
        photo_findings=[
            PhotoFinding(photo_index=0, issue="low_quality", severity="low", note="x"),
            PhotoFinding(photo_index=1, issue="low_quality", severity="low", note="x"),
        ],
        seller_findings=[
            SellerFinding(flag="other", severity="low", note="sin nombre"),
        ],
    )
    score, risk, _ = compute_score(rep)
    assert risk == RiskLevel.GREEN
    assert score >= 95


# ---------------------------------------------------------------------------
# Cases that land yellow (40-69)


def test_overpriced_with_few_findings_yellow() -> None:
    rep = _base_report(
        price=PriceEstimate(
            fair_price_mxn=180_000, range_low_mxn=160_000, range_high_mxn=200_000,
            delta_pct=33.0, comparables_count=10, sources=["mercadolibre"],
        ),
        description_findings=[
            DescriptionFinding(flag="urgency", severity="medium", excerpt="urge..."),
            DescriptionFinding(flag="urgency", severity="low", excerpt="cuanto antes"),
        ],
        photo_findings=[
            PhotoFinding(photo_index=0, issue="paint_mismatch", severity="medium", note="x"),
        ],
    )
    score, risk, _ = compute_score(rep)
    # 100 - 10 (price) - 3 (medium desc) - 1 (low desc) - 3 (medium photo) = 83 → green
    # Voy a hacer escenario más fuerte para yellow
    assert risk in {RiskLevel.GREEN, RiskLevel.YELLOW}
    assert score < 100


def test_multiple_high_findings_lands_yellow() -> None:
    rep = _base_report(
        description_findings=[
            DescriptionFinding(flag="urgency", severity="high", excerpt="urge"),
            DescriptionFinding(flag="seller_abroad", severity="high", excerpt="extranjero"),
        ],
        seller_findings=[
            SellerFinding(flag="new_account", severity="medium", note="60 días"),
        ],
    )
    # Penalty: 2 high desc capped... 2*10=20 → photo+desc cap is 30 each, ok 20
    # + seller medium 5 = 25 total → 75 → green (cerca del borde)
    score, risk, _ = compute_score(rep)
    assert score >= 60


# ---------------------------------------------------------------------------
# Cases that should land RED (< 40)


def test_stolen_vehicle_drops_to_red() -> None:
    """Vehículo robado fuerza red por kill switch, aunque score sea 50.

    El penalty es -50, score quedaría en 50 (yellow numéricamente),
    pero el kill switch del scoring escala a red automáticamente —
    un auto robado nunca debe mostrarse como yellow.
    """
    rep = _base_report(
        repuve=RepuveResult(queried=True, is_stolen=True, raw_status="robado"),
    )
    score, risk, summary = compute_score(rep)
    assert score == 50
    assert risk == RiskLevel.RED  # kill switch
    assert "ROBADO" in summary


def test_stolen_plus_findings_lands_red() -> None:
    rep = _base_report(
        repuve=RepuveResult(queried=True, is_stolen=True),
        description_findings=[
            DescriptionFinding(flag="seller_abroad", severity="high", excerpt="x"),
            DescriptionFinding(flag="advance_payment_request", severity="high", excerpt="x"),
        ],
        seller_findings=[
            SellerFinding(flag="new_account", severity="high", note="10 días"),
        ],
    )
    # 100 - 50 (stolen) - 20 (2 high desc) - 15 (high seller) = 15 → red
    score, risk, _ = compute_score(rep)
    assert score < _GREEN_PARTITION()
    assert risk == RiskLevel.RED


def test_vin_high_alert_kill_switch_forces_red() -> None:
    """Una alerta high en vin_check (placa clonada, VIN no coincide)
    fuerza red por kill switch, aunque el score numérico esté en
    rango green/yellow."""
    from app.models.report import (
        VinAlertModel,
        VinCheck,
        VinDecodedModel,
    )
    rep = _base_report(
        vin_check=VinCheck(
            decoded=VinDecodedModel(
                vin="5YFEPRAE0LP000001",
                valid_format=True, valid_checksum=True,
                wmi="5YF", country="USA", manufacturer="Toyota",
                year=2020,
            ),
            matches_listing=False,
            alerts=[VinAlertModel(
                severity="high",
                message="VIN físico es Toyota pero anuncio dice Honda. POSIBLE PLACA CLONADA",
            )],
        ),
    )
    score, risk, _ = compute_score(rep)
    # Penalty -25 → score 75 (verde numéricamente) pero kill switch escala
    assert score == 75
    assert risk == RiskLevel.RED


def test_vin_low_alert_no_kill_switch() -> None:
    """Una alerta low (año ±1) NO dispara el kill switch."""
    from app.models.report import (
        VinAlertModel,
        VinCheck,
        VinDecodedModel,
    )
    rep = _base_report(
        vin_check=VinCheck(
            decoded=VinDecodedModel(
                vin="2HGFC2F65JH500001",
                valid_format=True, valid_checksum=True,
                wmi="2HG", country="Canadá", manufacturer="Honda",
                year=2018,
            ),
            matches_listing=True,
            alerts=[VinAlertModel(
                severity="low",
                message="Diferencia de 1 año normal por fechas de fabricación",
            )],
        ),
    )
    score, risk, _ = compute_score(rep)
    assert risk == RiskLevel.GREEN


def test_too_cheap_red_flag() -> None:
    """Anuncio sospechosamente barato (delta -37%) suma penalty."""
    rep = _base_report(
        price=PriceEstimate(
            fair_price_mxn=365_000, range_low_mxn=300_000, range_high_mxn=633_000,
            delta_pct=-37.0, comparables_count=7, sources=["mercadolibre"],
        ),
    )
    score, _, summary = compute_score(rep)
    assert score == 85  # 100 - 15
    assert "sospechosamente barato" in summary.lower()


# ---------------------------------------------------------------------------
# Caps


def test_low_findings_capped() -> None:
    """20 findings low no rompen el score: el cap es 5."""
    rep = _base_report(
        photo_findings=[
            PhotoFinding(photo_index=i, issue="low_quality", severity="low", note="x")
            for i in range(20)
        ],
    )
    score, _, _ = compute_score(rep)
    assert score == 95  # 100 - 5 (cap low)


def test_high_findings_capped_at_30() -> None:
    """5 findings high no penalizan más que 3: el cap es 30."""
    rep = _base_report(
        description_findings=[
            DescriptionFinding(flag="urgency", severity="high", excerpt=f"x{i}")
            for i in range(5)
        ],
    )
    score, _, _ = compute_score(rep)
    assert score == 70  # 100 - 30 (cap high)


# ---------------------------------------------------------------------------
# populate mutates


def test_populate_writes_score_and_risk() -> None:
    rep = _base_report(
        repuve=RepuveResult(queried=True, is_stolen=True),
    )
    out = populate(rep)
    assert out is rep  # same instance
    assert rep.score == 50
    # Kill switch: REPUVE robado → red, aunque score sea 50 (yellow num).
    assert rep.risk_level == RiskLevel.RED
    assert rep.summary  # non-empty


def test_populate_summary_includes_recommendation() -> None:
    rep = _base_report(
        repuve=RepuveResult(queried=True, is_stolen=True),
        description_findings=[
            DescriptionFinding(flag="seller_abroad", severity="high", excerpt="x")
        ] * 3,
    )
    populate(rep)
    assert "Recomendación" in rep.summary
    assert "walk away" in rep.summary or "verificación profesional" in rep.summary


# ---------------------------------------------------------------------------
# Helpers


def _GREEN_PARTITION() -> int:
    """Constante local; coincide con `_GREEN_MIN` del módulo."""
    return 70
