"""Durable local recovery snapshot for a persisted decomposition Thread."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3] / ".decomposition" / "state"


def path(thread_id: str) -> Path:
    return ROOT / f"{thread_id}.json"


def save(thread_id: str, state: dict[str, object]) -> None:
    values = state.get("values", {}) if isinstance(state, dict) else {}
    program = values.get("decomposition_program") if isinstance(values, dict) else None
    if not isinstance(program, dict) or program.get("program_id") != "flutter-study-decomposition-program":
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "thread_id": thread_id, "decomposition_program": program}
    for key in ("worker_result", "integration_result", "migration_request"):
        if isinstance(values.get(key), dict):
            payload[key] = values[key]
    path(thread_id).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load(thread_id: str) -> dict[str, object] | None:
    candidate = path(thread_id)
    if not candidate.is_file():
        return None
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if value.get("schema_version") != 1 or value.get("thread_id") != thread_id:
        return None
    return value if isinstance(value.get("decomposition_program"), dict) else None


def validate(snapshot: dict[str, object], thread_id: str, cluster_root: str) -> str | None:
    if snapshot.get("schema_version") != 1:
        return "STATE_SCHEMA_INCOMPATIBLE"
    if snapshot.get("thread_id") != thread_id:
        return "STATE_UNRECOVERABLE"
    program = snapshot.get("decomposition_program")
    if not isinstance(program, dict) or program.get("program_id") != "flutter-study-decomposition-program":
        return "STATE_UNRECOVERABLE"
    if program.get("cluster_root") != cluster_root:
        return "STATE_UNRECOVERABLE"
    tasks, managed = program.get("migration_tasks"), program.get("managed_worktrees")
    if not isinstance(tasks, list) or not tasks or not all(isinstance(task, dict) and task.get("task_id") for task in tasks):
        return "STATE_UNRECOVERABLE"
    if not isinstance(managed, list) or not all(isinstance(item, dict) and item.get("repository") and item.get("worktree") and item.get("head") for item in managed):
        return "STATE_UNRECOVERABLE"
    return None
