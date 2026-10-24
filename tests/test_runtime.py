from datetime import date, timedelta

from echoresolve import store
from echoresolve.agent import create_agent_proposal
from echoresolve.runtime import handle_borrower_turn


def setup_function():
    store.initialize()
    with store.connect() as conn:
        conn.execute("DELETE FROM audit_events")
        conn.execute("DELETE FROM payment_proposals")
        conn.execute("DELETE FROM payment_commitments")
        conn.execute("DELETE FROM accounts")
        conn.execute("DELETE FROM borrowers")
        conn.execute("""
            INSERT INTO borrowers VALUES
            ('BOR-RUNTIME', 'Runtime Test', 'reported_job_loss')
        """)
        conn.execute("""
            INSERT INTO accounts
                (account_id, borrower_id, balance_cents, currency)
            VALUES ('ACC-RUNTIME', 'BOR-RUNTIME', 125000, 'USD')
        """)


def pending_proposal():
    due = (date.today() + timedelta(days=7)).isoformat()
    return create_agent_proposal("BOR-RUNTIME", 5000, due)["proposal"]


def test_confirmation_requires_explicit_proposal_id():
    proposal = pending_proposal()
    result = handle_borrower_turn(
        "BOR-RUNTIME",
        f"I confirm $50 due {proposal['due_date']}",
    )
    assert result["action"] == "clarify"
    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0] == 0


def test_confirmation_rejects_mismatched_amount():
    proposal = pending_proposal()
    result = handle_borrower_turn(
        "BOR-RUNTIME",
        f"I confirm proposal {proposal['proposal_id']} for $75 due {proposal['due_date']}",
    )
    assert result["action"] == "clarify"
    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0] == 0


def test_confirmation_rejects_mismatched_date():
    proposal = pending_proposal()
    wrong_date = (date.today() + timedelta(days=8)).isoformat()
    result = handle_borrower_turn(
        "BOR-RUNTIME",
        f"I confirm proposal {proposal['proposal_id']} for $50 due {wrong_date}",
    )
    assert result["action"] == "clarify"
    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0] == 0


def test_confirmation_with_exact_terms_records_one_commitment(monkeypatch):
    proposal = pending_proposal()
    monkeypatch.setattr(
        "echoresolve.runtime.route_intent",
        lambda message: {
            "intent": "confirm_payment",
            "model": "test-router",
            "fallback": False,
        },
    )
    message = (
        f"I confirm proposal {proposal['proposal_id']} "
        f"for $50 due {proposal['due_date']}"
    )
    result = handle_borrower_turn("BOR-RUNTIME", message)

    assert result["ok"] is True
    assert result["action"] == "proposal_confirmed"
    assert result["commitment"]["amount_cents"] == 5000

    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0] == 1


def test_repeated_conversational_confirmation_does_not_duplicate(monkeypatch):
    proposal = pending_proposal()
    monkeypatch.setattr(
        "echoresolve.runtime.route_intent",
        lambda message: {
            "intent": "confirm_payment",
            "model": "test-router",
            "fallback": False,
        },
    )
    message = (
        f"I confirm proposal {proposal['proposal_id']} "
        f"for $50 due {proposal['due_date']}"
    )

    first = handle_borrower_turn("BOR-RUNTIME", message)
    second = handle_borrower_turn("BOR-RUNTIME", message)

    assert first["action"] == "proposal_confirmed"
    assert second["action"] == "clarify"
    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0] == 1
