from fastapi.testclient import TestClient

from app.main import app


def test_analyze_with_manual_listing() -> None:
    client = TestClient(app)
    payload = {
        "source": "facebook",
        "manual_listing": {
            "title": "Honda Civic 2018 LX",
            "price_mxn": 230000,
            "year": 2018,
            "make": "Honda",
            "model": "Civic",
            "kilometers": 78000,
            "location": "CDMX",
            "description": "Único dueño, factura agencia",
            "seller_name": "Juan",
            "photo_urls": [],
        },
    }
    res = client.post("/api/analyze", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["score"] == 50
    assert body["risk_level"] == "yellow"
    assert body["listing"]["make"] == "Honda"
    assert len(body["questions_for_seller"]) >= 3


def test_analyze_rejects_empty_input() -> None:
    client = TestClient(app)
    res = client.post("/api/analyze", json={})
    assert res.status_code == 400
