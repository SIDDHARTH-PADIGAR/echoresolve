from datetime import date, timedelta

from fastapi.testclient import TestClient

from echoresolve.api import app


def test_proposal_creation_and_confirmation():
    due = (date.today() + timedelta(days=7)).isoformat()

    with TestClient(app) as client:
        created = client.post("/proposals", json={
            "borrower_id": "BOR-1001",
            "amount_cents": 5000,
            "due_date": due,
            "ttl_minutes": 10,
        })

        assert created.status_code == 200, created.text
        proposal = created.json()["proposal"]

        confirmed = client.post("/proposals/confirm", json={
            "borrower_id": "BOR-1001",
            "proposal_id": proposal["proposal_id"],
        })

        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["commitment"]["amount_cents"] == 5000

        context = client.get("/borrowers/BOR-1001/context")
        assert context.status_code == 200
        assert any(
            item["amount_cents"] == 5000
            for item in context.json()["commitments"]
        )


def test_proposal_confirmation_cannot_be_replayed():
    due = (date.today() + timedelta(days=7)).isoformat()

    with TestClient(app) as client:
        created = client.post("/proposals", json={
            "borrower_id": "BOR-1001",
            "amount_cents": 2500,
            "due_date": due,
        })
        assert created.status_code == 200, created.text
        proposal_id = created.json()["proposal"]["proposal_id"]

        payload = {
            "borrower_id": "BOR-1001",
            "proposal_id": proposal_id,
        }
        first = client.post("/proposals/confirm", json=payload)
        second = client.post("/proposals/confirm", json=payload)

    assert first.status_code == 200
    assert second.status_code == 422


def test_invalid_proposal_is_rejected():
    with TestClient(app) as client:
        response = client.post("/proposals", json={
            "borrower_id": "BOR-1001",
            "amount_cents": 0,
            "due_date": date.today().isoformat(),
        })
    assert response.status_code == 422
