import json
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "echoresolve.db"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize():
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS borrowers (
            borrower_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            hardship_status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            borrower_id TEXT NOT NULL REFERENCES borrowers(borrower_id),
            balance_cents INTEGER NOT NULL CHECK(balance_cents >= 0),
            currency TEXT NOT NULL DEFAULT 'USD'
        );

        CREATE TABLE IF NOT EXISTS payment_commitments (
            commitment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL REFERENCES accounts(account_id),
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            due_date TEXT NOT NULL,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payment_proposals (
            proposal_id TEXT PRIMARY KEY,
            borrower_id TEXT NOT NULL REFERENCES borrowers(borrower_id),
            account_id TEXT NOT NULL REFERENCES accounts(account_id),
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            due_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending', 'confirmed', 'expired', 'rejected')),
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)

        conn.execute("""
            INSERT OR IGNORE INTO borrowers
                (borrower_id, name, hardship_status)
            VALUES ('BOR-1001', 'Alex Morgan', 'reported_job_loss')
        """)
        conn.execute("""
            INSERT OR IGNORE INTO accounts
                (account_id, borrower_id, balance_cents, currency)
            VALUES ('ACC-1001', 'BOR-1001', 125000, 'USD')
        """)


def get_borrower_context(borrower_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("""
            SELECT b.borrower_id, b.name, b.hardship_status,
                   a.account_id, a.balance_cents, a.currency
            FROM borrowers b
            JOIN accounts a ON a.borrower_id = b.borrower_id
            WHERE b.borrower_id = ?
        """, (borrower_id,)).fetchone()

        if row is None:
            return None

        commitments = conn.execute("""
            SELECT amount_cents, due_date, status
            FROM payment_commitments
            WHERE account_id = ?
            ORDER BY commitment_id DESC
        """, (row["account_id"],)).fetchall()

        return {
            "borrower_id": row["borrower_id"],
            "name": row["name"],
            "hardship_status": row["hardship_status"],
            "account_id": row["account_id"],
            "balance_cents": row["balance_cents"],
            "currency": row["currency"],
            "commitments": [dict(item) for item in commitments],
        }


def validate_commitment(amount_cents: int, due_date: str) -> tuple[bool, str]:
    try:
        parsed_date = date.fromisoformat(due_date)
    except ValueError:
        return False, "Due date must use YYYY-MM-DD format."

    if amount_cents < 100:
        return False, "Minimum commitment is $1.00."
    if amount_cents > 50000:
        return False, "Commitments above $500.00 require human review."
    if parsed_date < date.today():
        return False, "Due date cannot be in the past."
    if (parsed_date - date.today()).days > 30:
        return False, "Due date must be within the next 30 days."

    return True, "Commitment meets the demo policy."


def record_commitment(
    account_id: str,
    amount_cents: int,
    due_date: str,
    idempotency_key: str,
) -> dict:
    allowed, reason = validate_commitment(amount_cents, due_date)
    if not allowed:
        return {"ok": False, "reason": reason}

    with connect() as conn:
        existing = conn.execute("""
            SELECT * FROM payment_commitments WHERE idempotency_key = ?
        """, (idempotency_key,)).fetchone()

        if existing is not None:
            same_request = (
                existing["account_id"] == account_id
                and existing["amount_cents"] == amount_cents
                and existing["due_date"] == due_date
            )
            if not same_request:
                return {"ok": False, "reason": "Idempotency key reused for a different request."}
            return {"ok": True, "commitment": dict(existing), "replayed": True}

        account = conn.execute("""
            SELECT account_id FROM accounts WHERE account_id = ?
        """, (account_id,)).fetchone()
        if account is None:
            return {"ok": False, "reason": "Account not found."}

        cursor = conn.execute("""
            INSERT INTO payment_commitments
                (account_id, amount_cents, due_date, status, idempotency_key)
            VALUES (?, ?, ?, 'pending_confirmation', ?)
        """, (account_id, amount_cents, due_date, idempotency_key))

        commitment = conn.execute("""
            SELECT * FROM payment_commitments WHERE commitment_id = ?
        """, (cursor.lastrowid,)).fetchone()

        conn.execute("""
            INSERT INTO audit_events (event_type, entity_id, details_json)
            VALUES ('commitment_recorded', ?, ?)
        """, (
            str(cursor.lastrowid),
            json.dumps({
                "account_id": account_id,
                "amount_cents": amount_cents,
                "due_date": due_date,
                "status": "pending_confirmation",
            }),
        ))

        return {"ok": True, "commitment": dict(commitment), "replayed": False}


def create_payment_proposal(
    borrower_id: str,
    amount_cents: int,
    due_date: str,
    ttl_minutes: int = 10,
) -> dict:
    from datetime import datetime, timedelta, timezone
    import uuid

    context = get_borrower_context(borrower_id)
    if context is None:
        return {"ok": False, "reason": "Borrower context not found."}

    if amount_cents > context["balance_cents"]:
        return {"ok": False, "reason": "Proposed amount exceeds the outstanding balance."}

    allowed, reason = validate_commitment(amount_cents, due_date)
    if not allowed:
        return {"ok": False, "reason": reason}

    if not 1 <= ttl_minutes <= 30:
        return {"ok": False, "reason": "Proposal expiry must be between 1 and 30 minutes."}

    proposal_id = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()

    with connect() as conn:
        conn.execute("""
            INSERT INTO payment_proposals
                (proposal_id, borrower_id, account_id, amount_cents,
                 due_date, status, expires_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """, (
            proposal_id, borrower_id, context["account_id"], amount_cents,
            due_date, expires_at,
        ))
        conn.execute("""
            INSERT INTO audit_events (event_type, entity_id, details_json)
            VALUES ('proposal_created', ?, ?)
        """, (
            proposal_id,
            json.dumps({
                "borrower_id": borrower_id,
                "account_id": context["account_id"],
                "amount_cents": amount_cents,
                "due_date": due_date,
                "expires_at": expires_at,
            }),
        ))

    return {
        "ok": True,
        "proposal": {
            "proposal_id": proposal_id,
            "borrower_id": borrower_id,
            "account_id": context["account_id"],
            "amount_cents": amount_cents,
            "due_date": due_date,
            "status": "pending",
            "expires_at": expires_at,
        },
    }


def confirm_payment_proposal(borrower_id: str, proposal_id: str) -> dict:
    from datetime import datetime, timezone
    import uuid

    now = datetime.now(timezone.utc)

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        proposal = conn.execute("""
            SELECT * FROM payment_proposals WHERE proposal_id = ?
        """, (proposal_id,)).fetchone()

        if proposal is None or proposal["borrower_id"] != borrower_id:
            return {"ok": False, "reason": "Proposal not found for this borrower."}

        if proposal["status"] != "pending":
            return {"ok": False, "reason": f"Proposal is already {proposal['status']}."}

        expires_at = datetime.fromisoformat(proposal["expires_at"])
        if expires_at <= now:
            conn.execute("""
                UPDATE payment_proposals SET status = 'expired'
                WHERE proposal_id = ? AND status = 'pending'
            """, (proposal_id,))
            conn.execute("""
                INSERT INTO audit_events (event_type, entity_id, details_json)
                VALUES ('proposal_expired', ?, ?)
            """, (proposal_id, json.dumps({"reason": "confirmation_after_expiry"})))
            return {"ok": False, "reason": "Proposal has expired; create a new proposal."}

        context = conn.execute("""
            SELECT a.balance_cents
            FROM accounts a WHERE a.account_id = ?
        """, (proposal["account_id"],)).fetchone()

        if context is None or proposal["amount_cents"] > context["balance_cents"]:
            conn.execute("""
                UPDATE payment_proposals SET status = 'rejected'
                WHERE proposal_id = ? AND status = 'pending'
            """, (proposal_id,))
            return {"ok": False, "reason": "Account or balance check failed."}

        allowed, reason = validate_commitment(
            proposal["amount_cents"], proposal["due_date"]
        )
        if not allowed:
            conn.execute("""
                UPDATE payment_proposals SET status = 'rejected'
                WHERE proposal_id = ? AND status = 'pending'
            """, (proposal_id,))
            return {"ok": False, "reason": reason}

        idempotency_key = f"proposal:{proposal_id}"
        existing = conn.execute("""
            SELECT * FROM payment_commitments WHERE idempotency_key = ?
        """, (idempotency_key,)).fetchone()

        if existing is None:
            cursor = conn.execute("""
                INSERT INTO payment_commitments
                    (account_id, amount_cents, due_date, status, idempotency_key)
                VALUES (?, ?, ?, 'pending_confirmation', ?)
            """, (
                proposal["account_id"], proposal["amount_cents"],
                proposal["due_date"], idempotency_key,
            ))
            commitment_id = cursor.lastrowid
        else:
            commitment_id = existing["commitment_id"]

        conn.execute("""
            UPDATE payment_proposals SET status = 'confirmed'
            WHERE proposal_id = ? AND status = 'pending'
        """, (proposal_id,))

        conn.execute("""
            INSERT INTO audit_events (event_type, entity_id, details_json)
            VALUES ('proposal_confirmed', ?, ?)
        """, (
            proposal_id,
            json.dumps({
                "borrower_id": borrower_id,
                "commitment_id": commitment_id,
            }),
        ))

        commitment = conn.execute("""
            SELECT * FROM payment_commitments WHERE commitment_id = ?
        """, (commitment_id,)).fetchone()

    return {
        "ok": True,
        "commitment": dict(commitment),
        "proposal_id": proposal_id,
    }
