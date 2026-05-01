from fastapi.testclient import TestClient

from app.main import app


def test_analyze_with_manual_listing_clean() -> None:
    """Manual listing limpio (descripción honesta, sin red flags) debe
    cerrar en green con score alto. El test stub original asumía un
    score placeholder fijo de 50; con el scoring real (D7) el score
    sale del análisis combinado."""
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
    assert body["risk_level"] == "green"
    assert body["score"] >= 80
    assert body["listing"]["make"] == "Honda"
    assert isinstance(body["summary"], str) and len(body["summary"]) > 50
    assert len(body["questions_for_seller"]) >= 3


def test_analyze_rejects_empty_input() -> None:
    client = TestClient(app)
    res = client.post("/api/analyze", json={})
    assert res.status_code == 400


def test_analyze_pdf_endpoint_returns_pdf() -> None:
    """`POST /api/analyze/pdf` regresa Content-Type application/pdf
    con bytes válidos del PDF (header `%PDF-`)."""
    client = TestClient(app)
    # Construimos un Report mínimo con todos los campos requeridos.
    report_payload = {
        "score": 85,
        "risk_level": "green",
        "summary": "Reporte de prueba",
        "listing": {
            "source": "mercadolibre",
            "title": "Honda Civic 2018",
            "price_mxn": 230000,
            "year": 2018,
            "make": "Honda",
            "model": "Civic",
            "kilometers": 80000,
            "location": "CDMX",
        },
        "repuve": {"queried": False},
        "price": {"comparables_count": 0},
    }
    res = client.post("/api/analyze/pdf", json=report_payload)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert "attachment" in res.headers.get("content-disposition", "")
