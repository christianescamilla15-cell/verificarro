"""Pipeline-level tests para el nuevo path manual de REPUVE.

Estos tests evitan tocar Playwright: usan `repuve_manual` directo en la
request para validar el wiring de `_resolve_repuve`.
"""

from fastapi.testclient import TestClient

from app.main import app


def _payload(**extras) -> dict:
    base = {
        "source": "facebook",
        "manual_listing": {
            "title": "Honda Civic 2018",
            "price_mxn": 230000,
            "year": 2018,
            "make": "Honda",
            "model": "Civic",
            "kilometers": 78000,
            "location": "CDMX",
            "description": "",
            "seller_name": "",
            "photo_urls": [],
        },
    }
    base.update(extras)
    return base


def test_repuve_manual_override_clean() -> None:
    """Cuando el usuario pega un REPUVE limpio, el report lo refleja."""
    client = TestClient(app)
    res = client.post(
        "/api/analyze",
        json=_payload(
            plate="ABC123D",
            repuve_manual={"is_stolen": False, "has_legal_status": True},
        ),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["repuve"]["queried"] is True
    assert body["repuve"]["is_stolen"] is False
    assert body["repuve"]["has_legal_status"] is True
    assert body["repuve"]["raw_status"] == "manual"


def test_repuve_manual_override_stolen() -> None:
    """Override con vehículo robado se propaga sin tocar el portal."""
    client = TestClient(app)
    res = client.post(
        "/api/analyze",
        json=_payload(
            plate="XYZ789A",
            repuve_manual={"is_stolen": True},
        ),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["repuve"]["queried"] is True
    assert body["repuve"]["is_stolen"] is True


def test_repuve_no_plate_no_vin_no_query() -> None:
    """Sin placa ni NIV ni override, REPUVE no se consulta."""
    client = TestClient(app)
    res = client.post("/api/analyze", json=_payload())
    assert res.status_code == 200
    body = res.json()
    assert body["repuve"]["queried"] is False
    assert "Sin placa" in (body["repuve"]["error"] or "")
