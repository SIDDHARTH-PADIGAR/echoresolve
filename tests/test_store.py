from datetime import date, timedelta

from echoresolve import store


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
            ('BOR-TEST', 'Test Borrower', 'reported_job_loss')
        """)
        conn.execute("""
            INSERT INTO accounts
                (account_id, borrower_id, balance_cents, currency)
            VALUES ('ACC-TEST', 'BOR-TEST', 125000, 'USD')
        """)


def test_context_is_loaded_from_database():
    context = store.get_borrower_context("BOR-TEST")
    assert context is not None
    assert context["account_id"] == "ACC-TEST"
    assert context["balance_cents"] == 125000
    assert context["commitments"] == []


def test_valid_commitment_is_persisted_and_audited():
    due = (date.today() + timedelta(days=7)).isoformat()
    result = store.record_commitment("ACC-TEST", 5000, due, "test-key-1")

    assert result["ok"] is True
    assert result["commitment"]["status"] == "pending_confirmation"

    context = store.get_borrower_context("BOR-TEST")
    assert len(context["commitments"]) == 1
    with store.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'commitment_recorded'"
        ).fetchone()[0]
    assert count == 1


def test_invalid_commitment_is_rejected():
    due = (date.today() + timedelta(days=7)).isoformat()
    result = store.record_commitment("ACC-TEST", 0, due, "test-key-2")
    assert result["ok"] is False


def test_idempotent_retry_does_not_duplicate_commitment():
    due = (date.today() + timedelta(days=7)).isoformat()
    first = store.record_commitment("ACC-TEST", 5000, due, "test-key-3")
    second = store.record_commitment("ACC-TEST", 5000, due, "test-key-3")

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["replayed"] is True

    context = store.get_borrower_context("BOR-TEST")
    assert len(context["commitments"]) == 1


def test_idempotency_key_cannot_be_reused_for_different_request():
    due = (date.today() + timedelta(days=7)).isoformat()
    other_due = (date.today() + timedelta(days=8)).isoformat()

    store.record_commitment("ACC-TEST", 5000, due, "test-key-4")
    result = store.record_commitment("ACC-TEST", 6000, other_due, "test-key-4")

    assert result["ok"] is False


def test_unknown_borrower_returns_no_context():
    assert store.get_borrower_context("DOES-NOT-EXIST") is None
