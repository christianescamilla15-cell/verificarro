"""Tests del generador de links a portales oficiales gob.mx."""

from __future__ import annotations

from app.services.gob_mx_links import (
    _detect_state,
    build_consultation_links,
)


# ---------------------------------------------------------------------------
# State detection


def test_detect_state_cdmx_explicit() -> None:
    assert _detect_state("Ciudad de México") == "CDMX"
    assert _detect_state("CDMX") == "CDMX"
    assert _detect_state("Distrito Federal") == "CDMX"
    assert _detect_state("D.F.") == "CDMX"
    assert _detect_state("DF") == "CDMX"


def test_detect_state_cdmx_delegations() -> None:
    assert _detect_state("Coyoacán, CDMX") == "CDMX"
    assert _detect_state("Benito Juárez, México") == "CDMX"
    assert _detect_state("Iztapalapa") == "CDMX"


def test_detect_state_edomex_municipalities() -> None:
    assert _detect_state("Naucalpan, Edomex") == "Edomex"
    assert _detect_state("Ecatepec de Morelos") == "Edomex"
    assert _detect_state("Toluca") == "Edomex"
    assert _detect_state("Estado de México") == "Edomex"


def test_detect_state_other_state() -> None:
    """Estados fuera de CDMX/Edomex devuelven None."""
    assert _detect_state("Monterrey, Nuevo León") is None
    assert _detect_state("Guadalajara, Jalisco") is None


def test_detect_state_empty() -> None:
    assert _detect_state(None) is None
    assert _detect_state("") is None


# ---------------------------------------------------------------------------
# build_consultation_links


def test_links_always_include_repuve_federal() -> None:
    links = build_consultation_links(plate="ABC123D")
    repuve = next((l for l in links if "REPUVE" in l.name), None)
    assert repuve is not None
    assert repuve.applicable is True
    assert repuve.category == "robo"
    assert repuve.state_scope == "Federal"


def test_links_cdmx_marked_applicable_when_location_matches() -> None:
    links = build_consultation_links(
        plate="ABC123D", location="Coyoacán, Ciudad de México"
    )
    cdmx_links = [l for l in links if l.state_scope == "CDMX"]
    assert all(l.applicable for l in cdmx_links)
    assert len(cdmx_links) >= 3  # tenencia + verificación + infracciones


def test_links_edomex_marked_not_applicable_for_cdmx_location() -> None:
    links = build_consultation_links(
        plate="ABC123D", location="Ciudad de México"
    )
    edomex_links = [l for l in links if l.state_scope == "Edomex"]
    assert all(not l.applicable for l in edomex_links)


def test_links_edomex_applicable_when_location_matches() -> None:
    links = build_consultation_links(
        plate="DEF456E", location="Naucalpan, Estado de México"
    )
    edomex_links = [l for l in links if l.state_scope == "Edomex"]
    assert all(l.applicable for l in edomex_links)


def test_links_plate_appears_in_descriptions() -> None:
    links = build_consultation_links(plate="ABC123D")
    assert any("ABC123D" in l.description for l in links)


def test_links_no_plate_uses_placeholder() -> None:
    links = build_consultation_links()
    assert any("___" in l.description for l in links)


def test_links_categories_cover_main_concerns() -> None:
    links = build_consultation_links(
        plate="ABC123D", location="CDMX"
    )
    cats = {l.category for l in links}
    assert "robo" in cats
    assert "fiscal" in cats
    assert "ambiental" in cats
    assert "infracciones" in cats


def test_links_verificacion_cdmx_url_includes_plate() -> None:
    links = build_consultation_links(
        plate="ABC123D", location="CDMX"
    )
    verif = next(
        l for l in links
        if "Verificación" in l.name and l.state_scope == "CDMX"
    )
    assert "placa=ABC123D" in verif.url


def test_links_no_state_match_includes_all_marked_inapplicable() -> None:
    """Si la location es de otro estado, REPUVE federal aplica pero
    los CDMX/Edomex no — sin embargo siguen en la lista."""
    links = build_consultation_links(
        plate="ABC123D", location="Monterrey, Nuevo León"
    )
    federal = [l for l in links if l.state_scope == "Federal"]
    assert all(l.applicable for l in federal)
    state_specific = [l for l in links if l.state_scope in ("CDMX", "Edomex")]
    assert state_specific  # los devolvemos
    assert all(not l.applicable for l in state_specific)
