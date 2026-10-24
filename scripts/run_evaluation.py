import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from echoresolve import store
from echoresolve.agent import get_agent_context, create_agent_proposal, confirm_agent_proposal
from echoresolve.planner import reflect_on_tool_result, plan_borrower_request


def reset_db():
    store.initialize()
    with store.connect() as conn:
        conn.execute("DELETE FROM audit_events")
        conn.execute("DELETE FROM payment_commitments")
        conn.execute("DELETE FROM payment_proposals")
        conn.execute("DELETE FROM accounts")
        conn.execute("DELETE FROM borrowers")
        conn.execute(
            "INSERT INTO borrowers VALUES (?, ?, ?)",
            ("BOR-EVAL", "Evaluation Borrower", "reported_job_loss"),
        )
        conn.execute(
            """INSERT INTO accounts
               (account_id, borrower_id, balance_cents, currency)
               VALUES (?, ?, ?, ?)""",
            ("ACC-EVAL", "BOR-EVAL", 125000, "USD"),
        )


def run():
    scenarios = json.loads((ROOT / "data" / "eval_scenarios.json").read_text(encoding="utf-8-sig"))
    results = []

    def record(scenario_id, passed, evidence):
        results.append({
            "id": scenario_id,
            "passed": bool(passed),
            "evidence": evidence,
        })

    # CTX-01, CTX-02
    reset_db()
    context = get_agent_context("BOR-EVAL")
    missing = get_agent_context("UNKNOWN")
    record("CTX-01", context["ok"] and context["account"]["balance_cents"] == 125000, context)
    record("CTX-02", not missing["ok"], missing)

    due = (date.today() + timedelta(days=7)).isoformat()

    # POL-01
    reset_db()
    proposal_result = create_agent_proposal("BOR-EVAL", 5000, due)
    proposal = proposal_result.get("proposal", {})
    record(
        "POL-01",
        proposal_result["ok"] and proposal.get("status") == "pending",
        proposal_result,
    )

    # POL-02
    reset_db()
    over_balance = create_agent_proposal("BOR-EVAL", 200000, due)
    record("POL-02", not over_balance["ok"], over_balance)

    # POL-03
    reset_db()
    past_due = create_agent_proposal(
        "BOR-EVAL", 5000, (date.today() - timedelta(days=1)).isoformat()
    )
    record("POL-03", not past_due["ok"], past_due)

    # CON-01
    reset_db()
    pending = create_agent_proposal("BOR-EVAL", 5000, due)
    with store.connect() as conn:
        commitment_count = conn.execute(
            "SELECT COUNT(*) FROM payment_commitments"
        ).fetchone()[0]
    record(
        "CON-01",
        pending["ok"] and commitment_count == 0,
        {"proposal_created": pending["ok"], "commitments_before_confirmation": commitment_count},
    )

    # CON-02
    reset_db()
    pending = create_agent_proposal("BOR-EVAL", 5000, due)
    confirmation = confirm_agent_proposal("BOR-EVAL", pending["proposal"]["proposal_id"])
    record(
        "CON-02",
        confirmation["ok"] and confirmation["commitment"]["amount_cents"] == 5000,
        confirmation,
    )

    # CON-03
    reset_db()
    pending = store.create_payment_proposal("BOR-EVAL", 5000, due)
    if pending["ok"]:
        with store.connect() as conn:
            conn.execute(
                "UPDATE payment_proposals SET expires_at = ? WHERE proposal_id = ?",
                ("2000-01-01T00:00:00+00:00", pending["proposal"]["proposal_id"]),
            )
        expired = store.confirm_payment_proposal(
            "BOR-EVAL", pending["proposal"]["proposal_id"]
        )
    else:
        expired = pending
    record("CON-03", not expired["ok"] and "expired" in expired["reason"].lower(), expired)

    # REL-01
    reset_db()
    pending = store.create_payment_proposal("BOR-EVAL", 5000, due)
    if pending["ok"]:
        pid = pending["proposal"]["proposal_id"]
        first = store.confirm_payment_proposal("BOR-EVAL", pid)
        second = store.confirm_payment_proposal("BOR-EVAL", pid)
        with store.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM payment_commitments").fetchone()[0]
        passed = first["ok"] and not second["ok"] and count == 1
        evidence = {"first_ok": first["ok"], "second_ok": second["ok"], "commitment_count": count}
    else:
        passed, evidence = False, pending
    record("REL-01", passed, evidence)

    # REL-02
    reflection = reflect_on_tool_result(
        "confirm_agent_proposal",
        {"ok": True, "verified": False, "commitment": {"commitment_id": 1}},
    )
    record("REL-02", not reflection["proceed"], reflection)

    # SAFE-01
    plan = plan_borrower_request("unsupported_request")
    record(
        "SAFE-01",
        plan.goal == "Safely handle unsupported request"
        and ("clarify" in plan.steps[0] or "escalate" in plan.steps[0]),
        {"goal": plan.goal, "steps": plan.steps},
    )

    summary = {
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    output_path = ROOT / "data" / "evaluation_results.json"
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({
        "passed": summary["passed"],
        "total": summary["total"],
        "failed": [item for item in results if not item["passed"]],
        "results_file": str(output_path),
    }, indent=2))


if __name__ == "__main__":
    run()

