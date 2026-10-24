from typing import Any

from echoresolve import store


def get_agent_context(borrower_id: str) -> dict[str, Any]:
    """Return persisted facts for the current borrower turn."""
    context = store.get_borrower_context(borrower_id)

    if context is None:
        return {
            "ok": False,
            "error": "borrower_not_found",
            "message": "No verified borrower context is available.",
        }

    with store.connect() as conn:
        proposals = conn.execute("""
            SELECT proposal_id, amount_cents, due_date, status, expires_at
            FROM payment_proposals
            WHERE borrower_id = ? AND status = 'pending'
            ORDER BY created_at DESC
        """, (borrower_id,)).fetchall()

    return {
        "ok": True,
        "borrower": {
            "borrower_id": context["borrower_id"],
            "name": context["name"],
            "hardship_status": context["hardship_status"],
        },
        "account": {
            "account_id": context["account_id"],
            "balance_cents": context["balance_cents"],
            "currency": context["currency"],
        },
        "commitments": context["commitments"],
        "pending_proposals": [dict(row) for row in proposals],
        "source": "persisted_database",
    }


def create_agent_proposal(
    borrower_id: str,
    amount_cents: int,
    due_date: str,
) -> dict[str, Any]:
    """Create a policy-checked proposal; never confirm it implicitly."""
    result = store.create_payment_proposal(
        borrower_id=borrower_id,
        amount_cents=amount_cents,
        due_date=due_date,
    )

    if not result["ok"]:
        return {
            "ok": False,
            "error": "proposal_rejected",
            "message": result["reason"],
        }

    return {
        "ok": True,
        "proposal": result["proposal"],
        "next_action": "Read the exact amount and due date to the borrower and request confirmation.",
    }


def confirm_agent_proposal(
    borrower_id: str,
    proposal_id: str,
) -> dict[str, Any]:
    """Confirm only the exact persisted proposal identified by its ID."""
    result = store.confirm_payment_proposal(
        borrower_id=borrower_id,
        proposal_id=proposal_id,
    )

    if not result["ok"]:
        return {
            "ok": False,
            "error": "confirmation_rejected",
            "message": result["reason"],
        }

    return {
        "ok": True,
        "commitment": result["commitment"],
        "verified": True,
        "message": "The commitment was saved. Its status is pending confirmation.",
    }
