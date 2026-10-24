from datetime import date, timedelta

from echoresolve import store
from echoresolve.agent import (
    get_agent_context,
    create_agent_proposal,
    confirm_agent_proposal,
)


def setup_function():
    store.initialize()
    with store.connect() as conn:
        conn.execute("DELETE FROM audit_events")
        conn.execute("DELETE FROM payment_commitments")
        conn.execute("DELETE FROM payment_proposals")
        conn.execute("DELETE FROM accounts")
        conn.execute("DELETE FROM borrowers")
        conn.execute("""
            INSERT INTO borrowers VALUES
            ('BOR-AG', 'Agent Test', 'reported_job_loss')
        """)
        conn.execute("""
            INSERT INTO accounts
                (account_id, borrower_id, balance_cents, currency)
            VALUES ('ACC-AG', 'BOR-AG', 125000, 'USD')
        """)


def test_agent_context_comes_from_persisted_database():
    result = get_agent_context("BOR-AG")
    assert result["ok"] is True
    assert result["source"] == "persisted_database"
    assert result["account"]["balance_cents"] == 125000


def test_unknown_borrower_has_no_verified_context():
    result = get_agent_context("UNKNOWN")
    assert result["ok"] is False
    assert result["error"] == "borrower_not_found"


def test_proposal_creation_does_not_create_commitment():
    due = (date.today() + timedelta(days=7)).isoformat()
    result = create_agent_proposal("BOR-AG", 5000, due)

    assert result["ok"] is True
    assert result["next_action"]
    with store.connect() as conn:
        commitments = conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0]
    assert commitments == 0


def test_agent_confirmation_uses_saved_proposal():
    due = (date.today() + timedelta(days=7)).isoformat()
    proposal = create_agent_proposal("BOR-AG", 5000, due)["proposal"]

    result = confirm_agent_proposal("BOR-AG", proposal["proposal_id"])
    assert result["ok"] is True
    assert result["verified"] is True
    assert result["commitment"]["amount_cents"] == 5000


def test_agent_cannot_confirm_another_borrowers_proposal():
    due = (date.today() + timedelta(days=7)).isoformat()
    proposal = create_agent_proposal("BOR-AG", 5000, due)["proposal"]

    result = confirm_agent_proposal("OTHER-BORROWER", proposal["proposal_id"])
    assert result["ok"] is False


def test_agent_rejects_proposal_above_balance():
    result = create_agent_proposal("BOR-AG", 200000, 
        (date.today() + timedelta(days=7)).isoformat())
    assert result["ok"] is False
