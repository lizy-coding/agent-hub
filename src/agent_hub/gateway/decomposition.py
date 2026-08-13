"""Dedicated Thread and Run lifecycle for PLAN_ONLY decomposition."""
from __future__ import annotations

from urllib.error import HTTPError, URLError

from agent_hub.gateway.refactor_dashboard import fetch_state
from agent_hub.gateway.refactor_run import _call

PROGRAM_ID = "flutter-study-decomposition-program"
CLUSTER_ROOT = "/Users/forest/code/langGraph"


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
            return None, "THREAD_NOT_FOUND"
        if (thread.get("metadata") or {}).get("program_id") != PROGRAM_ID:
            return None, "WRONG_PROGRAM_TYPE"
        return thread_id, None
    threads = _call("POST", f"{server.rstrip('/')}/threads/search", {"limit": 100, "offset": 0})
    candidates = [thread for thread in threads if (thread.get("metadata") or {}).get("program_id") == PROGRAM_ID]
    if not candidates:
        return None, "NO_DECOMPOSITION_PROGRAM"
    return max(candidates, key=lambda item: item.get("updated_at", ""))["thread_id"], None


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
    return "\n".join(["Flutter Study Decomposition Program",f"Program ID: {p.get('program_id','—')}",f"Thread ID: {(state.get('metadata') or {}).get('thread_id','—')}",f"Cluster: {p.get('cluster_root','—')}",f"Execution mode: {p.get('execution_mode','—')} | Status: {p.get('status','PLANNING')}",f"Repositories: {', '.join(item.get('repository_id','—') for item in p.get('repositories',[])) or '—'}",f"Capabilities: {len(caps)} | Classified: {sum(bool(item.get('classification')) for item in caps)} | Blocked: {sum(item.get('classification')=='BLOCKED_DECISION' for item in caps)}",f"Package candidates: {counts}",f"Migration tasks: {len(tasks)} | READY: {sum(item.get('status')=='READY' for item in tasks)} | BLOCKED: {sum(item.get('status')=='BLOCKED_DECISION' for item in tasks)} | DONE: {sum(item.get('status')=='DONE' for item in tasks)}",f"Target graph: {len(graph.get('nodes',[]))} nodes / {len(graph.get('edges',[]))} edges | Cycles: {graph.get('cycles',[])}",f"Next node: {', '.join(state.get('next',[])) or '—'}"])


def status(server, thread_id=None, output=print):
    try:
        thread_id, error = _resolve_thread(server, thread_id)
        if error:
            output(error + ("; run ./agent decomposition-plan" if error == "NO_DECOMPOSITION_PROGRAM" else "")); return 2
        output(render(fetch_state(server, thread_id))); return 0
    except (URLError, OSError) as error:
        output(f"DISCONNECTED: {error}"); return 2
    except HTTPError as error:
        output("THREAD_NOT_FOUND" if error.code == 404 else f"DECOMPOSITION_ERROR: {error}"); return 2


def run(server, thread_id=None, output=print):
    thread_id, error = _resolve_thread(server, thread_id)
    if error: output(error); return 2
    output(f"PLAN_ONLY: decomposition-run is armed for Thread ID: {thread_id}; no business migration was submitted."); return 3


def decide(server, thread_id, decision_id, choice, reason="", output=print):
    try:
        thread_id, error = _resolve_thread(server, thread_id)
        if error: output(error); return 2
        if not decision_id or not choice: output("DECISION_ERROR: --decision-id and --choice are required"); return 2
        run = _submit(server, thread_id, {"cluster_root": CLUSTER_ROOT, "decision": {"decision_id": decision_id, "choice": choice, "reason": reason, "source": "human"}})
        output(f"Thread ID: {thread_id}\nRun ID: {run['run_id']}\nStatus: DECISION_SUBMITTED"); return 0
    except (URLError, OSError) as error: output(f"DISCONNECTED: {error}")
    except Exception as error: output(f"DECISION_ERROR: {error}")
    return 2
