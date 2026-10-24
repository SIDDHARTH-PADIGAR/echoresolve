from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from echoresolve import store


def setup_function():
    store.initialize()
    with store.connect() as conn:
        conn.execute("DELETE FROM audit_events")
        conn.execute("DELETE FROM payment_commitments")
        conn.execute("DELETE FROM payment_proposals")
        conn.execute("DELETE FROM accounts")
        conn.execute("DELETE FROM borrowers")
        conn.executemany(
            "INSERT INTO borrowers VALUES (?, ?, ?)",
            [
                ("BOR-P1", "Borrower One", "reported_job_loss"),
                ("BOR-P2", "Borrower Two", "none"),
            ],
        )
        conn.executemany(
            """INSERT INTO accounts
               (account_id, borrower_id, balance_cents, currency)
               VALUES (?, ?, ?, 'USD')""",
            [
                ("ACC-P1", "BOR-P1", 125000),
                ("ACC-P2", "BOR-P2", 90000),
            ],
        )


def create_proposal(borrower="BOR-P1", amount=5000, ttl=10):
    due = (date.today() + timedelta(days=7)).isoformat()
    return store.create_payment_proposal(borrower, amount, due, ttl)


def test_proposal_is_persisted():
    result = create_proposal()
    assert result["ok"] is True
    proposal = result["proposal"]

    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM payment_proposals WHERE proposal_id = ?",
            (proposal["proposal_id"],),
        ).fetchone()

    assert row is not None
    assert row["status"] == "pending"
    assert row["amount_cents"] == 5000


def test_valid_confirmation_creates_one_commitment():
    proposal = create_proposal()["proposal"]
    result = store.confirm_payment_proposal("BOR-P1", proposal["proposal_id"])

    assert result["ok"] is True
    assert result["commitment"]["amount_cents"] == 5000
    assert result["commitment"]["status"] == "pending_confirmation"

    with store.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0]
    assert count == 1


def test_wrong_borrower_cannot_confirm_proposal():
    proposal = create_proposal()["proposal"]
    result = store.confirm_payment_proposal("BOR-P2", proposal["proposal_id"])

    assert result["ok"] is False
    with store.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0]
    assert count == 0


def test_duplicate_confirmation_is_rejected_without_duplicate_commitment():
    proposal = create_proposal()["proposal"]
    first = store.confirm_payment_proposal("BOR-P1", proposal["proposal_id"])
    second = store.confirm_payment_proposal("BOR-P1", proposal["proposal_id"])

    assert first["ok"] is True
    assert second["ok"] is False
    with store.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0]
    assert count == 1


def test_expired_proposal_cannot_be_confirmed():
    proposal = create_proposal()["proposal"]
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    with store.connect() as conn:
        conn.execute(
            "UPDATE payment_proposals SET expires_at = ? WHERE proposal_id = ?",
            (expired, proposal["proposal_id"]),
        )

    result = store.confirm_payment_proposal("BOR-P1", proposal["proposal_id"])
    assert result["ok"] is False
    assert "expired" in result["reason"].lower()

    with store.connect() as conn:
        status = conn.execute(
            "SELECT status FROM payment_proposals WHERE proposal_id = ?",
            (proposal["proposal_id"],),
        ).fetchone()["status"]
        count = conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0]

    assert status == "expired"
    assert count == 0


def test_proposal_above_balance_is_rejected():
    result = create_proposal(amount=200000)
    assert result["ok"] is False
    assert "balance" in result["reason"].lower()


def test_invalid_expiry_window_is_rejected():
    result = create_proposal(ttl=0)
    assert result["ok"] is False


def test_unknown_proposal_cannot_be_confirmed():
    result = store.confirm_payment_proposal("BOR-P1", str(uuid4()))
    assert result["ok"] is False
