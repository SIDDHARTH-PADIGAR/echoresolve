from dataclasses import dataclass, field
from datetime import date
from typing import Any
import uuid

from echoresolve import store


@dataclass
class WorkflowTrace:
    plan: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, event: str, **details):
        self.events.append({"event": event, **details})


def handle_payment_request(
    borrower_id: str,
    amount_cents: int,
    due_date: str,
    confirmed_by_borrower: bool,
) -> dict:
    """
    Deterministic first-pass agent workflow.
    This does not infer consent or parse free-form speech.
    """
    trace = WorkflowTrace(plan=[
        "retrieve verified borrower context",
        "validate the proposed commitment against demo policy",
        "require explicit borrower confirmation",
        "record the commitment idempotently",
        "read back persisted state before reporting success",
    ])
    trace.record("plan_created", steps=trace.plan)

    context = store.get_borrower_context(borrower_id)
    if context is None:
        trace.record("context_lookup_failed", borrower_id=borrower_id)
        return {"ok": False, "reason": "Borrower context not found.", "trace": trace.events}

    trace.record(
        "context_loaded",
        borrower_id=borrower_id,
        account_id=context["account_id"],
        balance_cents=context["balance_cents"],
    )

    if amount_cents > context["balance_cents"]:
        reason = "Proposed amount exceeds the outstanding balance."
        trace.record("policy_rejected", reason=reason)
        return {"ok": False, "reason": reason, "trace": trace.events}

    allowed, reason = store.validate_commitment(amount_cents, due_date)
    if not allowed:
        trace.record("policy_rejected", reason=reason)
        return {"ok": False, "reason": reason, "trace": trace.events}

    trace.record("policy_validated", amount_cents=amount_cents, due_date=due_date)

    if not confirmed_by_borrower:
        trace.record("awaiting_confirmation")
        return {
            "ok": False,
            "status": "awaiting_confirmation",
            "reason": "Ask the borrower to confirm the amount and date before recording.",
            "context": context,
            "trace": trace.events,
        }

    key = str(uuid.uuid4())
    result = store.record_commitment(
        account_id=context["account_id"],
        amount_cents=amount_cents,
        due_date=due_date,
        idempotency_key=key,
    )
    trace.record("commitment_tool_called", tool_ok=result["ok"])

    if not result["ok"]:
        trace.record("commitment_failed", reason=result["reason"])
        return {"ok": False, "reason": result["reason"], "trace": trace.events}

    verified = store.get_borrower_context(borrower_id)
    persisted = any(
        item["amount_cents"] == amount_cents
        and item["due_date"] == due_date
        and item["status"] == "pending_confirmation"
        for item in verified["commitments"]
    )
    trace.record("persistence_verified", verified=persisted)

    if not persisted:
        return {
            "ok": False,
            "reason": "Commitment could not be verified after saving.",
            "trace": trace.events,
        }

    return {
        "ok": True,
        "status": "pending_confirmation",
        "message": "The commitment has been recorded as pending confirmation.",
        "commitment": result["commitment"],
        "trace": trace.events,
    }

