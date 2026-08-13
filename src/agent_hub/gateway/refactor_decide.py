"""Minimal Human-in-the-loop decision submission for a refactor Thread."""
from __future__ import annotations

from agent_hub.gateway.refactor_run import _call


def refactor_decide(server: str, thread_id: str, decision_id: str, choice: str, reason: str = "", output=print) -> int:
    try:
        assistants = _call("POST", server.rstrip("/") + "/assistants/search", {"limit": 50, "offset": 0})
        assistant = next(item["assistant_id"] for item in assistants if item["graph_id"] == "development")
        result = _call("POST", f"{server.rstrip('/')}/threads/{thread_id}/runs", {"assistant_id": assistant, "input": {"repository_id": "flutter_study", "decision": {"decision_id": decision_id, "choice": choice, "reason": reason}}, "multitask_strategy": "reject"})
        output(f"DECISION_SUBMITTED: {result['run_id']}")
        return 0
    except StopIteration:
        output("DECISION_ERROR: development graph not found")
    except Exception as error:
        output(f"DECISION_ERROR: {error}")
    return 2
