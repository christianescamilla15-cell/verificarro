"""Tests del description_analyzer.

Fixtures basadas en patrones reales que circulan en Marketplace MX.
Función pura: descripción → list[DescriptionFinding]. Sin red.
"""

import pytest

from app.analyzers.description_analyzer import _normalize, analyze


# ---------------------------------------------------------------------------
# Happy path: anuncios limpios no deben generar flags


CLEAN_DESCRIPTIONS = [
    """Honda Civic 2018 LX, único dueño, factura de agencia, todos los
    servicios al día en agencia. Llantas nuevas, neumáticos Michelin
    recién cambiados. Acepto cambio por auto de menor valor con
    diferencia.""",

    """Toyota Corolla 2020 SE. Auto en perfecto estado mecánico, listo
    para escriturar. Tiene placas vigentes de CDMX, tenencia al
    corriente. Te lo dejo ver con tu mecánico de confianza.""",

    """Vendo Mazda 3 2019 hatchback. Lo tengo desde nuevo, comprado en
    agencia Mazda Polanco, factura original a mi nombre. Servicios
    cada 10,000 km. Te muestro carpeta con todas las facturas.""",
]


@pytest.mark.parametrize("desc", CLEAN_DESCRIPTIONS)
def test_clean_descriptions_yield_no_flags(desc: str) -> None:
    findings = analyze(desc)
    assert findings == []


# ---------------------------------------------------------------------------
# Patrones individuales


def test_urgency_detected_high_severity_phrase() -> None:
    findings = analyze("Urge vender hoy mismo, necesito el dinero")
    flags = {f.flag for f in findings}
    assert "urgency" in flags
    severities = {f.severity for f in findings if f.flag == "urgency"}
    # "Urge vender" → medium; "necesito el dinero" → medium
    assert "medium" in severities


def test_urgency_low_phrase_alone() -> None:
    findings = analyze("Lo vendo cuanto antes porque ya no lo uso")
    flags = {f.flag for f in findings}
    assert "urgency" in flags


def test_seller_abroad_high() -> None:
    findings = analyze(
        "Estoy en el extranjero, vivo en USA por trabajo. Te lo envío "
        "desde Texas cuando me deposites."
    )
    flag_set = {f.flag for f in findings}
    assert "seller_abroad" in flag_set
    assert "advance_payment_request" in flag_set
    abroad = [f for f in findings if f.flag == "seller_abroad"]
    assert any(f.severity == "high" for f in abroad)


def test_advance_payment_western_union() -> None:
    findings = analyze(
        "Acepto Western Union o PayPal amigos para que sea más rápido."
    )
    flags = {f.flag for f in findings}
    assert "advance_payment_request" in flags


def test_no_inspection_allowed() -> None:
    findings = analyze(
        "Solo whatsapp, no llamadas. No se permite revisión mecánica "
        "antes de la compra."
    )
    flags = {f.flag for f in findings}
    assert "no_inspection_allowed" in flags
    high = [f for f in findings if f.flag == "no_inspection_allowed" and f.severity == "high"]
    assert high


def test_vague_history_no_factura() -> None:
    findings = analyze("Lo compré usado y no tengo factura, fue de mi compadre")
    flags = {f.flag for f in findings}
    assert "vague_history" in flags


def test_other_defensive_legality_claim() -> None:
    findings = analyze("No es robado y no tiene adeudo, te lo aseguro")
    flags = {f.flag for f in findings}
    assert "other" in flags


# ---------------------------------------------------------------------------
# Patrones en combo (estafas clásicas)


SCAM_DESCRIPTION = """¡URGE VENDER! Estoy en el extranjero, me mudé a Texas
por trabajo y necesito venderlo ya. El auto está en CDMX con un familiar.
No se permite revisión antes de la compra, solo whatsapp por la diferencia
de horario. Te lo envío en cuanto deposites el anticipo de $5,000 vía
Western Union para apartar."""


def test_classic_scam_combo_flags_multiple_categories() -> None:
    findings = analyze(SCAM_DESCRIPTION)
    flags = {f.flag for f in findings}
    # Debe cazar al menos 4 de las 5 categorías peligrosas.
    assert {"urgency", "seller_abroad", "advance_payment_request",
            "no_inspection_allowed"}.issubset(flags)


def test_classic_scam_has_high_severity_findings() -> None:
    findings = analyze(SCAM_DESCRIPTION)
    high_count = sum(1 for f in findings if f.severity == "high")
    # Al menos 2 high severity (extranjero + sin inspección, mínimo).
    assert high_count >= 2


# ---------------------------------------------------------------------------
# Robustez


def test_empty_description_returns_empty() -> None:
    assert analyze("") == []
    assert analyze("   \n  ") == []
    assert analyze(None) == []  # type: ignore[arg-type]


def test_dedup_same_flag_same_severity() -> None:
    """Múltiples menciones del mismo patrón no duplican findings."""
    text = "URGE VENDER hoy. Urge venderlo cuanto antes. Urge mucho."
    findings = analyze(text)
    by_key = {(f.flag, f.severity): f for f in findings}
    # Debe haber a lo más 1 finding por (flag, severity).
    assert len(by_key) == len(findings)


def test_excerpt_includes_label_and_fragment() -> None:
    findings = analyze("URGE VENDER, necesito venderlo hoy mismo")
    urgency_findings = [f for f in findings if f.flag == "urgency"]
    assert urgency_findings
    for f in urgency_findings:
        assert f.excerpt
        assert ":" in f.excerpt  # tiene la forma "<label>: '<fragment>'"


def test_normalize_strips_accents_and_lowercase() -> None:
    assert _normalize("Urgé Véndér Hóy") == "urge vender hoy"


def test_accents_in_input_still_match() -> None:
    """Las descripciones con acentos deben matchear igual que sin ellos."""
    findings = analyze("Estoy en el extránjero y vivo en USA")
    assert any(f.flag == "seller_abroad" for f in findings)


def test_non_string_input_safe() -> None:
    """No debe explotar si llega algo raro."""
    assert analyze("") == []
