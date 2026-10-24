import pytest

from echoresolve.planner import (
    ALLOWED_TOOLS,
    plan_borrower_request,
    reflect_on_tool_result,
)


def test_balance_request_has_bounded_plan():
    plan = plan_borrower_request("check_balance")
    assert plan.goal == "Retrieve verified borrower context"
    assert len(plan.steps) == 2
    assert plan.complete is False


def test_payment_proposal_plan_checks_context_and_policy():
    plan = plan_borrower_request("propose_payment")
    assert "validate requested payment against policy" in plan.steps
    assert "verify proposal details before presenting them" in plan.steps


def test_unknown_intent_routes_to_clarification_or_escalation():
    plan = plan_borrower_request("something_unsupported")
    assert plan.steps == ["clarify the request or escalate to a human"]


def test_plan_cannot_advance_past_completion():
    plan = plan_borrower_request("check_balance")
    plan.advance({"ok": True})
    plan.advance({"ok": True})
    assert plan.complete is True

    with pytest.raises(RuntimeError):
        plan.advance({"ok": True})


def test_unapproved_tool_is_rejected():
    result = reflect_on_tool_result("delete_account", {"ok": True})
    assert result["proceed"] is False
    assert result["action"] == "escalate"


def test_malformed_tool_result_is_rejected():
    result = reflect_on_tool_result("get_agent_context", {"unexpected": True})
    assert result["proceed"] is False


def test_context_must_have_database_source():
    result = reflect_on_tool_result(
        "get_agent_context",
        {"ok": True, "source": "model_guess"},
    )
    assert result["proceed"] is False


def test_proposal_must_include_required_evidence():
    result = reflect_on_tool_result(
        "create_agent_proposal",
        {"ok": True, "proposal": {"proposal_id": "abc", "status": "pending"}},
    )
    assert result["proceed"] is False


def test_valid_proposal_passes_reflection():
    result = reflect_on_tool_result(
        "create_agent_proposal",
        {
            "ok": True,
            "proposal": {
                "proposal_id": "proposal-123",
                "amount_cents": 5000,
                "due_date": "2026-10-31",
                "status": "pending",
            },
        },
    )
    assert result["proceed"] is True


def test_confirmation_requires_verified_persisted_commitment():
    result = reflect_on_tool_result(
        "confirm_agent_proposal",
        {
            "ok": True,
            "verified": False,
            "commitment": {"commitment_id": 1},
        },
    )
    assert result["proceed"] is False


def test_allowlist_contains_only_implemented_agent_tools():
    assert ALLOWED_TOOLS == {
        "get_agent_context",
        "create_agent_proposal",
        "confirm_agent_proposal",
    }
