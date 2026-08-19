"""Minimal Human-in-the-loop decision submission for a refactor Thread."""
from __future__ import annotations

from agent_hub.gateway.refactor_run import _call
from agent_hub.gateway.refactor_dashboard import resolve_thread
from agent_hub.projects.decomposition_config import load_decomposition_project


def refactor_decide(server: str, thread_id: str, decision_id: str, choice: str, reason: str = "", output=print, project_id: str | None = None) -> int:
    try:
        project = load_decomposition_project(project_id)
        thread_id = resolve_thread(server, thread_id, project.project_id)
        if not thread_id:
            output("DECISION_ERROR: NO_REFACTOR_PROGRAM")
            return 2
        assistants = _call("POST", server.rstrip("/") + "/assistants/search", {"limit": 50, "offset": 0})
        assistant = next(item["assistant_id"] for item in assistants if item["graph_id"] == "development")
        result = _call("POST", f"{server.rstrip('/')}/threads/{thread_id}/runs", {"assistant_id": assistant, "input": {"repository_id": project.primary_repository_id, "decision": {"decision_id": decision_id, "choice": choice, "reason": reason}}, "multitask_strategy": "reject"})
        output(f"DECISION_SUBMITTED: {result['run_id']}")
        return 0
    except StopIteration:
        output("DECISION_ERROR: development graph not found")
    except Exception as error:
        output(f"DECISION_ERROR: {error}")
    return 2
