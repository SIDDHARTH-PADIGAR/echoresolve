from datetime import date, timedelta

from echoresolve import store
from echoresolve.workflow import handle_payment_request


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
            ('BOR-WF', 'Workflow Borrower', 'reported_job_loss')
        """)
        conn.execute("""
            INSERT INTO accounts
                (account_id, borrower_id, balance_cents, currency)
            VALUES ('ACC-WF', 'BOR-WF', 125000, 'USD')
        """)


def test_missing_borrower_is_rejected():
    result = handle_payment_request(
        "UNKNOWN", 5000,
        (date.today() + timedelta(days=7)).isoformat(), True
    )
    assert result["ok"] is False
    assert result["trace"][0]["event"] == "plan_created"


def test_policy_rejection_prevents_write():
    result = handle_payment_request(
        "BOR-WF", 0,
        (date.today() + timedelta(days=7)).isoformat(), True
    )
    assert result["ok"] is False
    assert result["trace"][-1]["event"] == "policy_rejected"
    assert store.get_borrower_context("BOR-WF")["commitments"] == []


def test_confirmation_is_required_before_write():
    result = handle_payment_request(
        "BOR-WF", 5000,
        (date.today() + timedelta(days=7)).isoformat(), False
    )
    assert result["status"] == "awaiting_confirmation"
    assert store.get_borrower_context("BOR-WF")["commitments"] == []


def test_confirmed_commitment_is_saved_and_verified():
    due = (date.today() + timedelta(days=7)).isoformat()
    result = handle_payment_request("BOR-WF", 5000, due, True)

    assert result["ok"] is True
    assert result["trace"][-1] == {
        "event": "persistence_verified", "verified": True
    }
    context = store.get_borrower_context("BOR-WF")
    assert len(context["commitments"]) == 1


def test_amount_above_balance_is_rejected():
    result = handle_payment_request(
        "BOR-WF", 200000,
        (date.today() + timedelta(days=7)).isoformat(), True
    )
    assert result["ok"] is False
    assert "outstanding balance" in result["reason"]
    assert store.get_borrower_context("BOR-WF")["commitments"] == []
