"""Read-only terminal rendering for a persisted LangGraph refactor thread."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import URLError
from urllib.request import urlopen


DEFAULT_SERVER = "http://127.0.0.1:2024"
DEFAULT_THREAD_ID = "019ff8bc-e2de-76d1-8386-4c08fdbaf5a6"


def fetch_state(server: str, thread_id: str) -> dict[str, object]:
    with urlopen(f"{server.rstrip('/')}/threads/{thread_id}/state", timeout=5) as response:
        return json.loads(response.read())


def _state(value: bool) -> str:
    return "DONE" if value else "PENDING"


def render(state: dict[str, object]) -> str:
    values = state.get("values", {})
    program = values.get("program", {})
    worker = values.get("worker_result") or {}
    primary = values.get("primary_apply") or {}
    task = values.get("development_task") or {}
    metadata = state.get("metadata") or {}
    graph_tasks = state.get("tasks") or []
    next_nodes = state.get("next") or []
    tasks = program.get("tasks", [])
    done = [item for item in tasks if item.get("status") == "DONE"]
    ready = [item for item in tasks if item.get("status") == "READY"]
    blocked = [item for item in tasks if item.get("status") == "BLOCKED"] + list(program.get("blocked_tasks", []))
    total = len(tasks)
    progress = 100 if total and len(done) == total else (round(100 * len(done) / total) if total else 0)
    graph_active = bool(next_nodes or graph_tasks)
    overall = f"PROGRAM {program.get('status', 'UNKNOWN')} / GRAPH {'ACTIVE' if graph_active else 'IDLE'}"
    execute_done = worker.get("status") == "SUCCESS" and worker.get("review") == "APPROVED"
    pipeline = [
        ("Context", bool(program)),
        ("Plan", bool(program.get("tasks") is not None)),
        ("Freeze", bool(task)),
        ("Execute Code", execute_done or "execute_code" in next_nodes),
        ("ScopeGuard", worker.get("scope_guard") == "PASS"),
        ("Validation", (worker.get("validation") or {}).get("analyze", {}).get("status") == "PASS"),
        ("Review", worker.get("review") == "APPROVED"),
        ("Apply PRIMARY", primary.get("status") == "APPLIED"),
        ("PRIMARY Validate", (primary.get("validation") or {}).get("analyze", {}).get("status") == "PASS"),
    ]
    task_rows = lambda items: ", ".join(item.get("task_id", "unknown") for item in items) or "—"
    current = program.get("current_task") or "—"
    last_task = task.get("task_id") or "—"
    lines = [
        "Flutter Study Refactor Program",
        f"Program ID: {program.get('program_id', '—')}",
        f"Thread ID: {metadata.get('thread_id', '—')}",
        f"Run ID: {metadata.get('run_id', '—')} | Graph step: {metadata.get('step', '—')}",
        f"Overall: {overall}",
        "",
        f"Units: {len(program.get('development_units', []))} | Tasks: {total} | DONE: {len(done)} | READY: {len(ready)} | BLOCKED: {len(blocked)} | Progress: {progress}%",
        f"Current: {current} | Last task: {last_task}",
        "Pipeline: " + " -> ".join(f"{name}={'RUNNING' if name == 'Execute Code' and active and not execute_done else _state(active)}" for name, active in pipeline),
        "",
        f"Workstreams: {', '.join(program.get('workstreams', [])) or '—'}",
        f"Completed: {task_rows(done)}",
        f"Ready: {task_rows(ready)}",
        f"Blocked decisions: {task_rows(blocked)}",
        f"Next node: {', '.join(next_nodes) or '—'}",
        "",
        "Last execution:",
        f"  Worker: {worker.get('status', '—')} | exit_code: {worker.get('exit_code', '—')} | ScopeGuard: {worker.get('scope_guard', '—')}",
        f"  flutter analyze: {(worker.get('validation') or {}).get('analyze', {}).get('status', worker.get('analyze', {}).get('status', '—'))} | Review: {worker.get('review', '—')}",
        f"  Changed files: {', '.join(worker.get('changed_files', [])) or '—'}",
        f"  PRIMARY apply: {primary.get('status', '—')} | PRIMARY changed: {', '.join(primary.get('changed_files', [])) or '—'}",
    ]
    if task:
        lines.extend([f"  Allowed paths: {', '.join(task.get('allowed_paths', [])) or '—'}", f"  Base revision: {task.get('base_revision', '—')}"])
    return "\n".join(lines)


def status(server: str, thread_id: str, output: Callable[[str], None] = print) -> int:
    try:
        output(render(fetch_state(server, thread_id)))
        return 0
    except (URLError, OSError, ValueError) as error:
        output(f"DISCONNECTED: {error}")
        return 2
