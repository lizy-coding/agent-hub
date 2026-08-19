"""Durable local recovery snapshot for a persisted decomposition Thread."""
from __future__ import annotations

import json
from pathlib import Path
from agent_hub.projects.decomposition_config import load_decomposition_project


ROOT = Path(__file__).resolve().parents[3] / ".decomposition" / "state"
_DEFAULT_PROJECT = load_decomposition_project()
DEFAULT_PROGRAM_ID = _DEFAULT_PROJECT.program_id
DEFAULT_PROJECT_ID = _DEFAULT_PROJECT.project_id


def path(thread_id: str, project_id: str | None = None) -> Path:
    if project_id is None:
        return ROOT / f"{thread_id}.json"
    namespace = project_id.replace("/", "_").replace("..", "_")
    return ROOT / namespace / f"{thread_id}.json"


def save(thread_id: str, state: dict[str, object], project_id: str | None = None) -> None:
    values = state.get("values", {}) if isinstance(state, dict) else {}
    program = values.get("decomposition_program") if isinstance(values, dict) else None
    if not isinstance(program, dict) or not program.get("program_id"):
        return
    selected_project = project_id or str(program.get("project_id") or DEFAULT_PROJECT_ID)
    destination = path(thread_id, selected_project) if project_id else path(thread_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 2 if project_id else 1, "thread_id": thread_id, "decomposition_program": program}
    if project_id:
        payload.update({"project_id": selected_project, "program_id": program.get("program_id")})
    for key in ("worker_result", "integration_result", "migration_request"):
        if isinstance(values.get(key), dict):
            payload[key] = values[key]
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load(thread_id: str, project_id: str | None = None) -> dict[str, object] | None:
    candidate = path(thread_id, project_id) if project_id else path(thread_id)
    if project_id and not candidate.is_file():
        # Read legacy v1 snapshots during the transition; the next save writes
        # the project-namespaced v2 representation.
        candidate = path(thread_id)
    if not candidate.is_file():
        return None
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if value.get("schema_version") not in {1, 2} or value.get("thread_id") != thread_id:
        return None
    if project_id and value.get("schema_version") == 2 and value.get("project_id") != project_id:
        return None
    return value if isinstance(value.get("decomposition_program"), dict) else None


def validate(snapshot: dict[str, object], thread_id: str, cluster_root: str, program_id: str = DEFAULT_PROGRAM_ID, project_id: str | None = None) -> str | None:
    if snapshot.get("schema_version") not in {1, 2}:
        return "STATE_SCHEMA_INCOMPATIBLE"
    if snapshot.get("thread_id") != thread_id:
        return "STATE_UNRECOVERABLE"
    program = snapshot.get("decomposition_program")
    if not isinstance(program, dict) or program.get("program_id") != program_id:
        return "STATE_UNRECOVERABLE"
    if project_id and snapshot.get("schema_version") == 2 and snapshot.get("project_id") != project_id:
        return "STATE_UNRECOVERABLE"
    if program.get("cluster_root") != cluster_root:
        return "STATE_UNRECOVERABLE"
    tasks, managed = program.get("migration_tasks"), program.get("managed_worktrees")
    if not isinstance(tasks, list) or not tasks or not all(isinstance(task, dict) and task.get("task_id") for task in tasks):
        return "STATE_UNRECOVERABLE"
    if not isinstance(managed, list) or not all(isinstance(item, dict) and item.get("repository") and item.get("worktree") and item.get("head") for item in managed):
        return "STATE_UNRECOVERABLE"
    return None
