import re
from typing import Any

from echoresolve.agent import (
    confirm_agent_proposal,
    create_agent_proposal,
    get_agent_context,
)
from echoresolve.llm_router import route_intent
from echoresolve.payment_extractor import extract_payment_details
from echoresolve.planner import plan_borrower_request, reflect_on_tool_result


_CONFIRMATION = re.compile(
    r"\b(?:i\s+)?(?:explicitly\s+)?(?:confirm|approve|agree\s+to)\b",
    re.IGNORECASE,
)
_PROPOSAL_ID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def handle_borrower_turn(borrower_id: str, message: str) -> dict[str, Any]:
    routed = route_intent(message)
    intent = routed["intent"]
    plan = plan_borrower_request(intent)
    result: dict[str, Any] = {
        "intent": intent,
        "model": routed["model"],
        "fallback": routed.get("fallback", False),
        "goal": plan.goal,
    }

    if intent in {"check_balance", "account_context"}:
        context = get_agent_context(borrower_id)
        reflection = reflect_on_tool_result("get_agent_context", context)
        if not reflection["proceed"]:
            return {**result, "ok": False, "action": reflection["action"],
                    "message": reflection["reason"]}

        account = context["account"]
        return {
            **result, "ok": True, "action": "answer_from_verified_context",
            "source": context["source"], "borrower": context["borrower"],
            "account": account,
            "message": (
                f"Your outstanding balance is {account['currency']} "
                f"{account['balance_cents'] / 100:.2f}."
                if intent == "check_balance"
                else "Your account context has been retrieved from the database."
            ),
        }

    if intent == "propose_payment":
        details = extract_payment_details(message)
        if not details["ok"]:
            return {**result, "ok": True, "action": "clarify",
                    "message": details["reason"], "payment_created": False}

        context = get_agent_context(borrower_id)
        reflection = reflect_on_tool_result("get_agent_context", context)
        if not reflection["proceed"]:
            return {**result, "ok": False, "action": reflection["action"],
                    "message": reflection["reason"], "payment_created": False}

        proposal_result = create_agent_proposal(
            borrower_id, details["amount_cents"], details["due_date"]
        )
        reflection = reflect_on_tool_result("create_agent_proposal", proposal_result)
        if not reflection["proceed"]:
            return {**result, "ok": False, "action": reflection["action"],
                    "message": reflection["reason"], "payment_created": False}

        proposal = proposal_result["proposal"]
        return {
            **result, "ok": True, "action": "request_explicit_confirmation",
            "source": context["source"], "proposal": proposal,
            "payment_created": False,
            "message": (
                f"I've prepared a payment proposal for "
                f"{context['account']['currency']} "
                f"{proposal['amount_cents'] / 100:.2f}, due "
                f"{proposal['due_date']}. No payment has been confirmed. "
                f"To confirm, reply with the proposal ID, exact amount, "
                f"due date, and explicit confirmation. "
                f"Proposal ID: {proposal['proposal_id']}."
            ),
        }

    if intent == "confirm_payment":
        proposal_ids = _PROPOSAL_ID.findall(message)
        if len(proposal_ids) != 1 or not _CONFIRMATION.search(message):
            return {
                **result, "ok": True, "action": "clarify",
                "message": (
                    "To confirm, include the pending proposal ID, exact amount, "
                    "due date, and explicit confirmation. Nothing was confirmed."
                ),
                "payment_created": False,
            }

        details = extract_payment_details(message)
        if not details["ok"]:
            return {**result, "ok": True, "action": "clarify",
                    "message": details["reason"], "payment_created": False}

        context = get_agent_context(borrower_id)
        reflection = reflect_on_tool_result("get_agent_context", context)
        if not reflection["proceed"]:
            return {**result, "ok": False, "action": reflection["action"],
                    "message": reflection["reason"], "payment_created": False}

        matching = [
            p for p in context["pending_proposals"]
            if p["proposal_id"].lower() == proposal_ids[0].lower()
        ]
        if len(matching) != 1:
            return {
                **result, "ok": True, "action": "clarify",
                "message": "That proposal is not pending for this borrower. Nothing was confirmed.",
                "payment_created": False,
            }

        proposal = matching[0]
        if (
            details["amount_cents"] != proposal["amount_cents"]
            or details["due_date"] != proposal["due_date"]
        ):
            return {
                **result, "ok": True, "action": "clarify",
                "message": (
                    "The amount or due date doesn't match the pending proposal. "
                    "Nothing was confirmed."
                ),
                "payment_created": False,
            }

        confirmation = confirm_agent_proposal(borrower_id, proposal["proposal_id"])
        reflection = reflect_on_tool_result("confirm_agent_proposal", confirmation)
        if not reflection["proceed"]:
            return {**result, "ok": False, "action": reflection["action"],
                    "message": reflection["reason"], "payment_created": False}

        commitment = confirmation["commitment"]
        return {
            **result, "ok": True, "action": "proposal_confirmed",
            "proposal_id": proposal["proposal_id"],
            "commitment": commitment,
            "payment_created": False,
            "message": (
                f"Your proposal for {context['account']['currency']} "
                f"{commitment['amount_cents'] / 100:.2f}, due "
                f"{commitment['due_date']}, has been confirmed and recorded. "
                "This records a commitment; it does not execute a payment."
            ),
        }

    return {
        **result, "ok": True, "action": "clarify",
        "message": "Could you clarify what you need help with?",
        "payment_created": False,
    }
