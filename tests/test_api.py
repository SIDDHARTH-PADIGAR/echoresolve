from datetime import date, timedelta

from fastapi.testclient import TestClient

from echoresolve.api import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_borrower_context_endpoint():
    with TestClient(app) as client:
        response = client.get("/borrowers/BOR-1001/context")
    assert response.status_code == 200
    assert response.json()["account_id"] == "ACC-1001"


def test_unknown_borrower_returns_404():
    with TestClient(app) as client:
        response = client.get("/borrowers/UNKNOWN/context")
    assert response.status_code == 404


def test_commitment_endpoint_persists_result():
    due = (date.today() + timedelta(days=7)).isoformat()
    payload = {
        "account_id": "ACC-1001",
        "amount_cents": 5000,
        "due_date": due,
        "idempotency_key": "api-test-key-001",
    }
    with TestClient(app) as client:
        first = client.post("/commitments", json=payload)
        second = client.post("/commitments", json=payload)
        context = client.get("/borrowers/BOR-1001/context")

    assert first.status_code == 200
    assert first.json()["commitment"]["status"] == "pending_confirmation"
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert len(context.json()["commitments"]) == 1


def test_invalid_commitment_is_rejected():
    payload = {
        "account_id": "ACC-1001",
        "amount_cents": 0,
        "due_date": date.today().isoformat(),
        "idempotency_key": "api-test-key-002",
    }
    with TestClient(app) as client:
        response = client.post("/commitments", json=payload)
    assert response.status_code == 422
