"""Dedicated Thread and Run lifecycle for PLAN_ONLY decomposition."""
from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

from agent_hub.gateway.refactor_dashboard import fetch_state
from agent_hub.gateway.refactor_run import _call
from agent_hub.gateway.decomposition_state import load as load_snapshot, save as save_snapshot, validate as validate_snapshot
from agent_hub.graphs.decomposition import RETRYABLE_BLOCKERS

PROGRAM_ID = "flutter-study-decomposition-program"
CLUSTER_ROOT = "/Users/forest/code/langGraph"


def _worker_ready(endpoint):
    try:
        host_port = endpoint.split(":")[2].split("/")[0]
        with socket.create_connection(("127.0.0.1", int(host_port)), timeout=1):
            return True
    except (OSError, IndexError, ValueError):
        return False


def _start_worker(endpoint):
    root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["AGENT_HUB_CODE_WORKER_PORT"] = endpoint.split(":")[2].split("/")[0]
    # The legacy executor still needs a primary path at server construction;
    # decomposition requests are dispatched to its dedicated multi-repo adapter.
    env["AGENT_HUB_PRIMARY_REPOSITORY_PATH"] = str(root / ".decomposition" / "flutter_study")
    return subprocess.Popen([str(root / ".venv/bin/python"), "-m", "agent_hub.gateway.code_worker"], cwd=root, env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _assistant(server):
    return next(item["assistant_id"] for item in _call("POST", f"{server.rstrip('/')}/assistants/search", {"limit": 50, "offset": 0}) if item["graph_id"] == "decomposition")


def _thread(server, thread_id):
    try:
        return _call("GET", f"{server.rstrip('/')}/threads/{thread_id}")
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def _resolve_thread(server, thread_id=None):
    if thread_id:
        thread = _thread(server, thread_id)
        if thread is None:
            restored, error = _rehydrate(server, thread_id)
            if error:
                return None, error
            thread = restored
        if (thread.get("metadata") or {}).get("program_id") != PROGRAM_ID:
            return None, "WRONG_PROGRAM_TYPE"
        return thread_id, None
    threads = _call("POST", f"{server.rstrip('/')}/threads/search", {"limit": 100, "offset": 0})
    candidates = [thread for thread in threads if (thread.get("metadata") or {}).get("program_id") == PROGRAM_ID]
    if not candidates:
        return None, "NO_DECOMPOSITION_PROGRAM"
    return max(candidates, key=lambda item: item.get("updated_at", ""))["thread_id"], None


def _rehydrate(server, thread_id):
    snapshot = load_snapshot(thread_id)
    if snapshot is None:
        return None, "THREAD_NOT_FOUND"
    error = validate_snapshot(snapshot, thread_id, CLUSTER_ROOT)
    if error:
        return None, error
    metadata = {"program_type": "decomposition", "program_id": PROGRAM_ID, "cluster_root": CLUSTER_ROOT, "rehydrated_from_local_snapshot": True}
    try:
        _call("POST", f"{server.rstrip('/')}/threads", {"thread_id": thread_id, "metadata": metadata, "if_exists": "do_nothing"})
        # A just-created Thread has no graph assignment, so initialise a
        # checkpoint with an interrupt-before-all no-op run.  It executes no
        # graph node and therefore cannot plan, dispatch, or touch business.
        _call("POST", f"{server.rstrip('/')}/threads/{thread_id}/runs", {"assistant_id": _assistant(server), "input": None, "interrupt_before": "*", "multitask_strategy": "reject"})
        values = {key: value for key, value in snapshot.items() if key in {"decomposition_program", "worker_result", "integration_result", "migration_request"}}
        _call("POST", f"{server.rstrip('/')}/threads/{thread_id}/state", {"values": values})
        restored = _thread(server, thread_id)
        state = fetch_state(server, thread_id)
        if restored is None or (state.get("values") or {}).get("decomposition_program", {}).get("program_id") != PROGRAM_ID:
            return None, "STATE_UNRECOVERABLE"
        return restored, None
    except (HTTPError, URLError, OSError, ValueError):
        return None, "STATE_UNRECOVERABLE"


def _reconcile_only(server, thread_id):
    """Run only reconciliation; the graph routes this input directly to END."""
    return _call("POST", f"{server.rstrip('/')}/threads/{thread_id}/runs", {"assistant_id": _assistant(server), "input": {"execute": False, "reconcile_only": True}, "multitask_strategy": "reject"})


def _stale_dispatching(state):
    values = state.get("values") or {}
    program = values.get("decomposition_program") if isinstance(values, dict) else None
    if not isinstance(program, dict):
        return False
    return any(task.get("status") == "DISPATCHING" for task in program.get("migration_tasks", []))


def _needs_done_reconciliation(state):
    values = state.get("values") or {}
    program, worker = values.get("decomposition_program"), values.get("worker_result")
    if not isinstance(program, dict) or not isinstance(worker, dict):
        return False
    task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == worker.get("task_id")), None)
    if not isinstance(task, dict) or task.get("status") != "DONE":
        return False
    architecture = (worker.get("validation") or {}).get("architecture_guard", {}) if isinstance(worker.get("validation"), dict) else {}
    results = worker.get("repositories", {}) if isinstance(worker.get("repositories"), dict) else {}
    changed = [repository for repository, result in results.items() if isinstance(result, dict) and result.get("changed_files")]
    commits = task.get("integration_commits") if isinstance(task.get("integration_commits"), dict) else {}
    return not (bool(changed) and worker.get("status") == "SUCCESS" and worker.get("scope_guard") == "PASS" and architecture.get("status") == "PASS" and worker.get("architecture_verdict") == "APPROVED" and all(commits.get(repository) for repository in changed))


def _needs_contract_reconciliation(state):
    values = state.get("values") or {}
    program = values.get("decomposition_program") if isinstance(values, dict) else None
    if not isinstance(program, dict):
        return False
    task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == "merge-file-picker-bridge-owners"), None)
    return isinstance(task, dict) and task.get("status") == "READY" and task.get("target_units") == ["plugins/file_picker_bridge"]


def _needs_stale_running_reconciliation(state):
    values = state.get("values") or {}
    program = values.get("decomposition_program") if isinstance(values, dict) else None
    if not isinstance(program, dict):
        return False
    return any(task.get("status") == "RUNNING" and not isinstance(task.get("worker_execution"), dict) for task in program.get("migration_tasks", []))


def _needs_ready_dirty_reconciliation(state):
    """Let graph-owned recovery classify a dirty managed READY task."""
    values = state.get("values") or {}
    program = values.get("decomposition_program") if isinstance(values, dict) else None
    if not isinstance(program, dict):
        return False
    task = next((item for item in program.get("migration_tasks", []) if item.get("task_id") == program.get("current_migration_task") and item.get("status") == "READY"), None)
    if not isinstance(task, dict):
        return False
    repositories = {"flutter_study" if str(unit).startswith(("flutter_study/", "apps/flutter_study", "apps/")) else str(unit).split("/")[0] for unit in [*task.get("source_units", []), *task.get("target_units", [])]}
    for managed in program.get("managed_worktrees", []):
        if not isinstance(managed, dict) or str(managed.get("repository")) not in repositories:
            continue
        root = str(managed.get("worktree", ""))
        if root and os.path.isdir(root):
            tracked = subprocess.check_output(["git", "diff", "--name-only"], cwd=root, text=True).splitlines()
            untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, text=True).splitlines()
            if tracked or untracked:
                return True
    return False


def _needs_rejected_worker_reconciliation(state):
    values = state.get("values") or {}
    program, worker = values.get("decomposition_program"), values.get("worker_result")
    if not isinstance(program, dict) or not isinstance(worker, dict) or worker.get("architecture_verdict") != "REJECTED":
        return False
    return any(task.get("task_id") == worker.get("task_id") and task.get("status") in {"DISPATCHING", "RUNNING"} for task in program.get("migration_tasks", []))


def _needs_app_guard_reconciliation(state):
    values = state.get("values") or {}
    program, worker = values.get("decomposition_program"), values.get("worker_result")
    if not isinstance(program, dict) or not isinstance(worker, dict) or worker.get("task_id") != "relocate-flutter-study-app" or worker.get("architecture_verdict") != "REJECTED":
        return False
    guard = (worker.get("validation") or {}).get("architecture_guard", {}) if isinstance(worker.get("validation"), dict) else {}
    return guard.get("reason") == "app_target_missing" and any(item.get("task_id") == worker.get("task_id") and item.get("status") == "BLOCKED_DECISION" for item in program.get("migration_tasks", []))


def _needs_zero_change_reconciliation(state):
    values = state.get("values") or {}
    program, worker = values.get("decomposition_program"), values.get("worker_result")
    if not isinstance(program, dict) or not isinstance(worker, dict) or worker.get("status") != "SUCCESS":
        return False
    results = worker.get("repositories", {}) if isinstance(worker.get("repositories"), dict) else {}
    changed = [path for result in results.values() if isinstance(result, dict) for path in result.get("changed_files", [])]
    return not changed and any(item.get("task_id") == worker.get("task_id") and item.get("status") in {"DISPATCHING", "RUNNING"} for item in program.get("migration_tasks", []))


def _needs_blocked_decision_metadata(state):
    values = state.get("values") or {}
    program = values.get("decomposition_program") if isinstance(values, dict) else None
    if not isinstance(program, dict):
        return False
    blocker = program.get("execution_blocker")
    return isinstance(blocker, dict) and blocker.get("status") in RETRYABLE_BLOCKERS and not blocker.get("decision_id") and any(item.get("task_id") == blocker.get("task_id") and item.get("status") == "BLOCKED_DECISION" for item in program.get("migration_tasks", []))


def _has_active_run(server, thread_id):
    runs = _call("GET", f"{server.rstrip('/')}/threads/{thread_id}/runs")
    return any(str(item.get("status", "")).lower() in {"pending", "queued", "running"} for item in runs if isinstance(item, dict))


def _reconcile_stale_dispatching(server, thread_id, state):
    """Only recover a stale dispatch when no LangGraph Run is still active."""
    if not (_stale_dispatching(state) or _needs_done_reconciliation(state) or _needs_contract_reconciliation(state) or _needs_stale_running_reconciliation(state) or _needs_ready_dirty_reconciliation(state) or _needs_rejected_worker_reconciliation(state) or _needs_app_guard_reconciliation(state) or _needs_zero_change_reconciliation(state) or _needs_blocked_decision_metadata(state)) or _has_active_run(server, thread_id):
        return state
    _reconcile_only(server, thread_id)
    # LangGraph accepts runs asynchronously.  Wait briefly for the
    # reconciliation checkpoint so `decomposition-status` does not render the
    # stale projection that it has just repaired.
    for _ in range(20):
        state = fetch_state(server, thread_id)
        if not _stale_dispatching(state) and not _needs_done_reconciliation(state) and not _needs_contract_reconciliation(state) and not _needs_stale_running_reconciliation(state) and not _needs_ready_dirty_reconciliation(state) and not _needs_rejected_worker_reconciliation(state) and not _needs_app_guard_reconciliation(state) and not _needs_zero_change_reconciliation(state) and not _needs_blocked_decision_metadata(state):
            return state
        time.sleep(.05)
    return state


def _submit(server, thread_id, payload):
    return _call("POST", f"{server.rstrip('/')}/threads/{thread_id}/runs", {"assistant_id": _assistant(server), "input": payload, "multitask_strategy": "reject"})


def plan(server, thread_id=None, output=print):
    try:
        if thread_id:
            thread_id, error = _resolve_thread(server, thread_id)
            if error:
                output(error); return 2
        else:
            thread_id = _call("POST", f"{server.rstrip('/')}/threads", {"metadata": {"program_type": "decomposition", "program_id": PROGRAM_ID, "cluster_root": CLUSTER_ROOT}})["thread_id"]
        run = _submit(server, thread_id, {"cluster_root": CLUSTER_ROOT})
        output(f"Program ID: {PROGRAM_ID}\nThread ID: {thread_id}\nRun ID: {run['run_id']}\nCluster: {CLUSTER_ROOT}\nMode: PLAN_ONLY\nStatus: PLAN_SUBMITTED")
        return 0
    except (URLError, OSError) as error:
        output(f"DISCONNECTED: {error}")
    except Exception as error:
        output(f"DECOMPOSITION_ERROR: {error}")
    return 2


def render(state):
    p = state.get("values", {}).get("decomposition_program", {}); caps=p.get("capabilities", []); tasks=p.get("migration_tasks", []); candidates=p.get("package_candidates", []); graph=p.get("target_dependency_graph", {})
    counts={kind:sum(item.get("package_type")==kind for item in candidates) for kind in ["DART_PACKAGE","FLUTTER_PACKAGE","FLUTTER_PLUGIN","FEDERATED_PLUGIN","FFI_PACKAGE","APP_ONLY","MERGE_CANDIDATE","DELETE_CANDIDATE"]}
    blocker=p.get("execution_blocker") or {}; managed=p.get("managed_worktrees",[])
    dirty=", ".join(f"{item.get('repository')}:{', '.join(item.get('changed_files',[]))}" for item in blocker.get("repositories",[])) or "—"
    managed_rows=", ".join(f"{item.get('repository')}@{item.get('branch')}" for item in managed) or "—"
    current=next((item for item in tasks if item.get("task_id")==p.get("current_migration_task")),{})
    execution=current.get("worker_execution",{}) if isinstance(current,dict) else {}
    return "\n".join(["Flutter Study Decomposition Program",f"Program ID: {p.get('program_id','—')}",f"Thread ID: {(state.get('metadata') or {}).get('thread_id','—')}",f"Cluster: {p.get('cluster_root','—')}",f"Execution mode: {p.get('execution_mode','—')} | Status: {p.get('status','PLANNING')}",f"Repositories: {', '.join(item.get('repository_id','—') for item in p.get('repositories',[])) or '—'}",f"Managed worktrees: {managed_rows}",f"Capabilities: {len(caps)} | Classified: {sum(bool(item.get('classification')) for item in caps)} | Blocked: {sum(item.get('classification')=='BLOCKED_DECISION' for item in caps)}",f"Package candidates: {counts}",f"Migration tasks: {len(tasks)} | READY: {sum(item.get('status')=='READY' for item in tasks)} | DISPATCHING: {sum(item.get('status')=='DISPATCHING' for item in tasks)} | RUNNING: {sum(item.get('status')=='RUNNING' for item in tasks)} | BLOCKED: {sum(item.get('status')=='BLOCKED_DECISION' for item in tasks)} | DONE: {sum(item.get('status')=='DONE' for item in tasks)}",f"Current migration task: {p.get('current_migration_task','—')}",f"Worker execution: {execution.get('worker_execution_id','—')} | workspace: {execution.get('worker_workspace','—')} | started: {execution.get('dispatched_at','—')}",f"Execution blocker: {blocker.get('status','—')} | {blocker.get('reason','—')}",f"Dirty repositories: {dirty}",f"Target graph: {len(graph.get('nodes',[]))} nodes / {len(graph.get('edges',[]))} edges | Cycles: {graph.get('cycles',[])}",f"Next node: {', '.join(state.get('next',[])) or '—'}"])


def status(server, thread_id=None, output=print):
    try:
        thread_id, error = _resolve_thread(server, thread_id)
        if error:
            output(error + ("; run ./agent decomposition-plan" if error == "NO_DECOMPOSITION_PROGRAM" else "")); return 2
        state = fetch_state(server, thread_id)
        program = (state.get("values") or {}).get("decomposition_program")
        if not isinstance(program, dict) or program.get("program_id") != PROGRAM_ID:
            _, error = _rehydrate(server, thread_id)
            if error:
                output("STATE_NOT_LOADED: Thread exists but no compatible DecompositionProgram checkpoint is available.")
                return 2
            state = fetch_state(server, thread_id)
        else:
            save_snapshot(thread_id, state)
        state = _reconcile_stale_dispatching(server, thread_id, state)
        save_snapshot(thread_id, state)
        output(render(state)); return 0
    except (URLError, OSError) as error:
        output(f"DISCONNECTED: {error}"); return 2
    except HTTPError as error:
        output("THREAD_NOT_FOUND" if error.code == 404 else f"DECOMPOSITION_ERROR: {error}"); return 2


def run(server, thread_id=None, execute=False, output=print):
    try:
        thread_id, error = _resolve_thread(server, thread_id)
        if error: output(error); return 2
        if not execute:
            output(f"PLAN_ONLY: decomposition-run is armed for Thread ID: {thread_id}; pass --execute to allow a MigrationTask run."); return 3
        endpoint = os.environ.get("AGENT_HUB_CODE_WORKER_ENDPOINT", "http://127.0.0.1:8766/execute")
        state = fetch_state(server, thread_id)
        values = state.get("values") or {}
        program = values.get("decomposition_program") if isinstance(values, dict) else None
        payload = {"execute": True, "worker_endpoint": endpoint}
        if not isinstance(program, dict) or program.get("program_id") != PROGRAM_ID:
            _, error = _rehydrate(server, thread_id)
            if error:
                output("STATE_UNRECOVERABLE: no compatible durable DecompositionProgram snapshot; refusing to dispatch or re-plan.")
                return 2
            state = fetch_state(server, thread_id)
            program = (state.get("values") or {}).get("decomposition_program")
            if not isinstance(program, dict) or program.get("program_id") != PROGRAM_ID:
                output("STATE_UNRECOVERABLE: rehydration did not create a compatible checkpoint.")
                return 2
        else:
            save_snapshot(thread_id, state)
        state = _reconcile_stale_dispatching(server, thread_id, state)
        program = (state.get("values") or {}).get("decomposition_program")
        if not isinstance(program, dict) or program.get("status") == "PROGRAM_BLOCKED":
            output("PROGRAM_BLOCKED: stale dispatch reconciliation requires an explicit decision.")
            return 3
        if not _worker_ready(endpoint):
            process = _start_worker(endpoint)
            for _ in range(20):
                if _worker_ready(endpoint):
                    break
                time.sleep(.25)
            if not _worker_ready(endpoint):
                output(f"WORKER_UNAVAILABLE: failed to start pid {process.pid}")
                return 3
            output(f"Worker started (pid={process.pid})")
        run = _submit(server, thread_id, {**payload, "reconcile_only": False})
        output(f"Program ID: {PROGRAM_ID}\nThread ID: {thread_id}\nRun ID: {run['run_id']}\nMode: EXECUTE\nStatus: EXECUTION_SUBMITTED"); return 0
    except (URLError, OSError) as error: output(f"DISCONNECTED: {error}")
    except Exception as error: output(f"DECOMPOSITION_ERROR: {error}")
    return 2


def decide(server, thread_id, decision_id, choice, reason="", output=print):
    try:
        thread_id, error = _resolve_thread(server, thread_id)
        if error: output(error); return 2
        if not decision_id or not choice: output("DECISION_ERROR: --decision-id and --choice are required"); return 2
        run = _submit(server, thread_id, {"cluster_root": CLUSTER_ROOT, "execute": False, "reconcile_only": True, "decision": {"decision_id": decision_id, "choice": choice, "reason": reason, "source": "human"}})
        output(f"Thread ID: {thread_id}\nRun ID: {run['run_id']}\nStatus: DECISION_SUBMITTED"); return 0
    except (URLError, OSError) as error: output(f"DISCONNECTED: {error}")
    except Exception as error: output(f"DECISION_ERROR: {error}")
    return 2
