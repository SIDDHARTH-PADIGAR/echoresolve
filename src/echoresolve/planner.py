from dataclasses import dataclass, field
from typing import Any


ALLOWED_TOOLS = {
    "get_agent_context",
    "create_agent_proposal",
    "confirm_agent_proposal",
}


@dataclass
class AgentPlan:
    goal: str
    steps: list[str]
    current_step: int = 0
    evidence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.current_step >= len(self.steps)

    def advance(self, evidence: dict[str, Any]) -> None:
        if self.complete:
            raise RuntimeError("Plan is already complete.")
        self.evidence.append(evidence)
        self.current_step += 1


def plan_borrower_request(intent: str) -> AgentPlan:
    """Create a bounded plan for supported borrower intents."""
    normalized = intent.strip().lower()

    if normalized in {"check_balance", "account_context"}:
        return AgentPlan(
            goal="Retrieve verified borrower context",
            steps=["load persisted borrower context", "verify required account fields"],
        )

    if normalized == "propose_payment":
        return AgentPlan(
            goal="Prepare a policy-checked payment proposal",
            steps=[
                "load persisted borrower context",
                "validate requested payment against policy",
                "create a pending proposal",
                "verify proposal details before presenting them",
            ],
        )

    if normalized == "confirm_payment":
        return AgentPlan(
            goal="Confirm an explicitly identified proposal",
            steps=[
                "retrieve the pending proposal",
                "confirm the exact proposal ID",
                "verify the persisted commitment",
            ],
        )

    return AgentPlan(
        goal="Safely handle unsupported request",
        steps=["clarify the request or escalate to a human"],
    )


def reflect_on_tool_result(
    tool_name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Check the tool boundary and evidence before the agent proceeds.
    This is deterministic reflection, not a second LLM call.
    """
    if tool_name not in ALLOWED_TOOLS:
        return {
            "proceed": False,
            "reason": "Tool is not allowlisted.",
            "action": "escalate",
        }

    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        return {
            "proceed": False,
            "reason": "Tool result has an invalid structure.",
            "action": "retry_or_escalate",
        }

    if not result["ok"]:
        return {
            "proceed": False,
            "reason": str(result.get("message", result.get("error", "Tool failed."))),
            "action": "clarify_or_escalate",
        }

    if tool_name == "get_agent_context":
        if result.get("source") != "persisted_database":
            return {
                "proceed": False,
                "reason": "Context source is not verified.",
                "action": "escalate",
            }

    if tool_name == "create_agent_proposal":
        proposal = result.get("proposal")
        required = {"proposal_id", "amount_cents", "due_date", "status"}
        if not isinstance(proposal, dict) or not required.issubset(proposal):
            return {
                "proceed": False,
                "reason": "Proposal evidence is incomplete.",
                "action": "escalate",
            }
        if proposal["status"] != "pending":
            return {
                "proceed": False,
                "reason": "New proposal is not pending.",
                "action": "escalate",
            }

    if tool_name == "confirm_agent_proposal":
        if result.get("verified") is not True:
            return {
                "proceed": False,
                "reason": "Commitment persistence was not verified.",
                "action": "escalate",
            }
        commitment = result.get("commitment")
        if not isinstance(commitment, dict) or not commitment.get("commitment_id"):
            return {
                "proceed": False,
                "reason": "Persisted commitment details are missing.",
                "action": "escalate",
            }

    return {
        "proceed": True,
        "reason": "Tool result passed deterministic evidence checks.",
        "action": "continue",
    }
