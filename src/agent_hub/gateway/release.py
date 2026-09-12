"""Dedicated Thread and Run lifecycle for GitHub installer release hosting.

PLAN_ONLY by default: ``release-plan`` freezes a ReleaseProgram and verifies
artifact checksums.  Only ``release-run --execute`` enters the publish lane,
and even then only through the frozen ``gh release`` commands validated by
``agent_hub.policies.safety``.  Publish tokens come from the operator's own
``gh auth`` session; nothing is stored by this host.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError

from agent_hub.gateway.refactor_dashboard import fetch_state
from agent_hub.gateway.refactor_run import _call
from agent_hub.projects.release_config import ReleaseProjectConfig, load_release_project


def _project(project_id: str | None = None) -> ReleaseProjectConfig:
    return load_release_project(project_id)


def _metadata(project: ReleaseProjectConfig) -> dict[str, object]:
    return {
        "program_type": "release_hosting",
        "program_id": project.program_id,
        "project_id": project.project_id,
        "cluster_root": str(project.cluster_root),
    }


def _graph_payload(project: ReleaseProjectConfig) -> dict[str, object]:
    return {"project_context": project.graph_input()}


def _assistant(server):
    return next(item["assistant_id"] for item in _call("POST", f"{server.rstrip('/')}/assistants/search", {"limit": 50, "offset": 0}) if item["graph_id"] == "release_hosting")


def _thread(server, thread_id):
    try:
        return _call("GET", f"{server.rstrip('/')}/threads/{thread_id}")
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def _resolve_thread(server, thread_id=None, project: ReleaseProjectConfig | None = None):
    project = project or _project()
    if thread_id:
        thread = _thread(server, thread_id)
        if thread is None:
            return None, "THREAD_NOT_FOUND"
        if (thread.get("metadata") or {}).get("program_id") != project.program_id:
            return None, "WRONG_PROGRAM_TYPE"
        return thread_id, None
    threads = _call("POST", f"{server.rstrip('/')}/threads/search", {"limit": 100, "offset": 0})
    candidates = [thread for thread in threads if (thread.get("metadata") or {}).get("program_id") == project.program_id and (thread.get("metadata") or {}).get("project_id", project.project_id) == project.project_id]
    if not candidates:
        return None, "NO_RELEASE_PROGRAM"
    return max(candidates, key=lambda item: item.get("updated_at", ""))["thread_id"], None


def _submit(server, thread_id, payload):
    return _call("POST", f"{server.rstrip('/')}/threads/{thread_id}/runs", {"assistant_id": _assistant(server), "input": payload, "multitask_strategy": "reject"})


def _load_spec(spec_path: str | None) -> tuple[dict[str, object], str]:
    if not spec_path:
        return {}, ""
    try:
        spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {}, f"RELEASE_SPEC_ERROR: {error}"
    if not isinstance(spec, dict):
        return {}, "RELEASE_SPEC_ERROR: spec must be a JSON object"
    # The graph and the checked-in release config own the target repository,
    # the tag shape, and artifact path safety.  A spec may request a version,
    # notes, draft/prerelease flags, or an explicit artifact list — nothing else.
    forbidden = {"github_repo", "release", "allowed_paths", "repository_paths"} & set(spec)
    if forbidden:
        return {}, f"RELEASE_SPEC_ERROR: graph-owned fields are not accepted: {', '.join(sorted(forbidden))}"
    return spec, ""


def plan(server, thread_id=None, spec_path=None, output=print, project_id=None):
    """Freeze a ReleaseProgram (PLAN_ONLY); never publishes anything."""
    try:
        project = _project(project_id)
        spec, error = _load_spec(spec_path)
        if error:
            output(error)
            return 2
        if thread_id:
            thread_id, error = _resolve_thread(server, thread_id, project)
            if error:
                output(error)
                return 2
        else:
            thread_id = _call("POST", f"{server.rstrip('/')}/threads", {"metadata": _metadata(project)})["thread_id"]
        run = _submit(server, thread_id, {**_graph_payload(project), "release_spec": spec, "execute": False})
        output(f"Project ID: {project.project_id}\nProgram ID: {project.program_id}\nThread ID: {thread_id}\nRun ID: {run['run_id']}\nGitHub repo: {project.release.get('github_repo') or '<unconfigured>'}\nMode: PLAN_ONLY\nStatus: RELEASE_PLAN_SUBMITTED")
        return 0
    except (URLError, OSError) as error:
        output(f"DISCONNECTED: {error}")
    except Exception as error:
        output(f"RELEASE_ERROR: {error}")
    return 2


def run(server, thread_id=None, execute=False, output=print, project_id=None):
    """Publish the frozen release; requires --execute and a clean frozen plan."""
    try:
        project = _project(project_id)
        thread_id, error = _resolve_thread(server, thread_id, project)
        if error:
            output(error)
            return 2
        if not execute:
            output(f"PLAN_ONLY: release-run is armed for Thread ID: {thread_id}; pass --execute to publish the frozen release to GitHub.")
            return 3
        state = fetch_state(server, thread_id)
        program = (state.get("values") or {}).get("release_program")
        if not isinstance(program, dict) or program.get("program_id") != project.program_id:
            output("STATE_NOT_LOADED: no frozen ReleaseProgram checkpoint; run ./agent release-plan first.")
            return 2
        if program.get("status") == "PROGRAM_BLOCKED":
            blocker = program.get("execution_blocker") or {}
            hint = f"; resolve with ./agent release-decide --decision-id {blocker.get('decision_id')} --choice retry" if blocker.get("decision_id") else ""
            output(f"PROGRAM_BLOCKED: {blocker.get('status', '—')}: {blocker.get('reason', '—')}{hint}")
            return 3
        run = _submit(server, thread_id, {**_graph_payload(project), "execute": True})
        output(f"Project ID: {project.project_id}\nProgram ID: {project.program_id}\nThread ID: {thread_id}\nRun ID: {run['run_id']}\nGitHub repo: {program.get('github_repo') or '<unconfigured>'}\nTag: {(program.get('release') or {}).get('tag', '—')}\nMode: EXECUTE\nStatus: RELEASE_PUBLISH_SUBMITTED")
        return 0
    except (URLError, OSError) as error:
        output(f"DISCONNECTED: {error}")
    except Exception as error:
        output(f"RELEASE_ERROR: {error}")
    return 2


def decide(server, thread_id, decision_id, choice, reason="", output=print, project_id=None):
    try:
        project = _project(project_id)
        thread_id, error = _resolve_thread(server, thread_id, project)
        if error:
            output(error)
            return 2
        if not decision_id or not choice:
            output("DECISION_ERROR: --decision-id and --choice are required")
            return 2
        run = _submit(server, thread_id, {**_graph_payload(project), "execute": False, "decision": {"decision_id": decision_id, "choice": choice, "reason": reason, "source": "human"}})
        output(f"Thread ID: {thread_id}\nRun ID: {run['run_id']}\nStatus: DECISION_SUBMITTED")
        return 0
    except (URLError, OSError) as error:
        output(f"DISCONNECTED: {error}")
    except Exception as error:
        output(f"DECISION_ERROR: {error}")
    return 2


def render(state):
    program = (state.get("values") or {}).get("release_program") or {}
    release = program.get("release") or {}
    artifacts = release.get("artifacts", [])
    blocker = program.get("execution_blocker") or {}
    publish_state = program.get("publish") or {}
    verification = program.get("artifact_verification") or {}
    counts = {key: sum(artifact.get("status") == key for artifact in artifacts) for key in ("PENDING", "UPLOADED", "FAILED", "VERIFIED")}
    rows = "\n".join(f"  - {artifact.get('asset_name')} [{artifact.get('status')}] sha256:{str(artifact.get('sha256') or '—')[:12]} size:{artifact.get('size') or '—'}" for artifact in artifacts) or "  —"
    return "\n".join([
        "Release Hosting Program",
        f"Project ID: {program.get('project_id', '—')}",
        f"Program ID: {program.get('program_id', '—')}",
        f"Thread ID: {(state.get('metadata') or {}).get('thread_id', '—')}",
        f"GitHub repo: {program.get('github_repo') or '<unconfigured>'}",
        f"Execution mode: {program.get('execution_mode', '—')} | Status: {program.get('status', '—')}",
        f"Tag: {release.get('tag', '—')} | Name: {release.get('name', '—')} | draft:{release.get('draft', False)} prerelease:{release.get('prerelease', False)}",
        f"Artifacts: {len(artifacts)} | PENDING: {counts['PENDING']} | UPLOADED: {counts['UPLOADED']} | FAILED: {counts['FAILED']} | VERIFIED: {counts['VERIFIED']}",
        rows,
        f"Artifact verification: {verification.get('status', '—')} | Publish mode: {publish_state.get('mode', '—')}",
        f"Release URL: {program.get('release_url', '—')} | Published at: {program.get('published_at', '—')}",
        f"Execution blocker: {blocker.get('status', '—')} | {blocker.get('reason', '—')}" + (f" | decision: {blocker.get('decision_id')}" if blocker.get("decision_id") else ""),
        f"Evidence: {'; '.join(str(item) for item in program.get('evidence', [])) or '—'}",
        f"Next node: {', '.join(state.get('next', [])) or '—'}",
    ])


def status(server, thread_id=None, output=print, project_id=None):
    try:
        project = _project(project_id)
        thread_id, error = _resolve_thread(server, thread_id, project)
        if error:
            output(error + ("; run ./agent release-plan" if error == "NO_RELEASE_PROGRAM" else ""))
            return 2
        state = fetch_state(server, thread_id)
        program = (state.get("values") or {}).get("release_program")
        if not isinstance(program, dict) or program.get("program_id") != project.program_id:
            output("STATE_NOT_LOADED: Thread exists but no compatible ReleaseProgram checkpoint is available.")
            return 2
        output(render(state))
        return 0
    except (ValueError, KeyError) as error:
        output(f"PROJECT_CONFIG_ERROR: {error}")
        return 2
    except (URLError, OSError) as error:
        output(f"DISCONNECTED: {error}")
        return 2
    except HTTPError as error:
        output("THREAD_NOT_FOUND" if error.code == 404 else f"RELEASE_ERROR: {error}")
        return 2
