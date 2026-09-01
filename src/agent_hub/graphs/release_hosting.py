"""Guarded GitHub installer release hosting for hosted projects.

The graph owns the release lifecycle; project adapters own the facts.  Every
release is a frozen ReleaseProgram: tag, notes, and the exact artifact list
(with sha256) are fixed before anything is published.  Planning is always
PLAN_ONLY; publishing requires an explicit ``execute`` run, uses only the
narrow ``gh release`` lane from ``agent_hub.policies.safety``, and resumes
safely after a partial publish.  The host still never pushes, merges, or
deletes: this graph is the single, explicit exception to ``forbid_release``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent_hub.policies.safety import validate_release_command
from agent_hub.projects.adapters import get_adapter

LOGGER = logging.getLogger(__name__)

# Publish failures with durable per-artifact state can be retried through an
# explicit human decision; configuration/staging failures cannot.
RETRYABLE_RELEASE_BLOCKERS = frozenset({
    "RELEASE_CREATE_FAILED",
    "PARTIAL_PUBLISH",
    "RELEASE_VERIFY_MISMATCH",
})


class State(TypedDict, total=False):
    release_program: dict[str, object]
    project_context: dict[str, object]
    release_spec: dict[str, object]
    decision: dict[str, object]
    execute: bool
    publish_result: dict[str, object]
    verify_result: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> dict[str, object]:
    """Low-level runner kept separate so tests can stub every execution."""
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600)
        return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
    except FileNotFoundError:
        return {"returncode": 127, "stdout": "", "stderr": f"executable not found: {command[0]}"}
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "command timed out"}


def _gh(argv: list[str], github_repo: str) -> dict[str, object]:
    """Run one command only after the release lane accepts it."""
    verdict = validate_release_command(argv, github_repo)
    if verdict.get("status") != "PASS":
        return {"ok": False, "verdict": verdict, "returncode": -1, "stdout": "", "stderr": str(verdict.get("reason", ""))}
    result = _run([str(part) for part in argv])
    return {"ok": result["returncode"] == 0, "verdict": verdict, **result}


def _repository_root(program: dict[str, object], context: dict[str, object]) -> Path:
    primary = str(program.get("primary_repository_id") or context.get("primary_repository_id") or "primary")
    paths = context.get("repository_paths")
    if isinstance(paths, dict) and paths.get(primary):
        return Path(str(paths[primary])).resolve()
    return (Path(str(program.get("cluster_root") or context.get("cluster_root") or ".")) / primary).resolve()


def _block(program: dict[str, object], status: str, reason: str, **extra: object) -> dict[str, object]:
    program = dict(program)
    blocker: dict[str, object] = {"status": status, "reason": reason, **extra}
    if status in RETRYABLE_RELEASE_BLOCKERS:
        tag = str((program.get("release") or {}).get("tag") or "")
        blocker.update({"decision_id": f"retry:release:{tag}", "choices": ["retry"]})
    program["status"] = "PROGRAM_BLOCKED"
    program["execution_blocker"] = blocker
    return {"release_program": program}


def build_release_hosting_graph():
    graph = StateGraph(State)

    def reconcile(state: State):
        program = state.get("release_program")
        if not isinstance(program, dict):
            return {}
        program = dict(program)
        decision = state.get("decision")
        if isinstance(decision, dict) and decision.get("choice") == "retry":
            blocker = program.get("execution_blocker")
            decision_id = str(decision.get("decision_id", ""))
            if isinstance(blocker, dict) and blocker.get("decision_id") == decision_id and blocker.get("status") in RETRYABLE_RELEASE_BLOCKERS:
                release = dict(program.get("release") or {})
                artifacts = [
                    {**artifact, "status": "PENDING"} if artifact.get("status") == "FAILED" else artifact
                    for artifact in release.get("artifacts", [])
                ]
                release["artifacts"] = artifacts
                program["release"] = release
                program["status"] = "PLANNING_COMPLETE"
                program.pop("execution_blocker", None)
                program.pop("publish", None)
                program.setdefault("human_decisions", []).append({
                    "decision_id": decision_id,
                    "choice": "retry",
                    "reason": str(decision.get("reason", "")),
                    "status": "APPLIED",
                    "applied_at": datetime.now(UTC).isoformat(),
                })
                return {"release_program": program, "decision": {}, "publish_result": {}, "verify_result": {}}
        return {"release_program": program}

    def freeze(state: State):
        program = state.get("release_program")
        execute = bool(state.get("execute"))
        if isinstance(program, dict) and isinstance(program.get("release"), dict) and program.get("release"):
            # Already frozen: never re-plan, only reflect this run's mode.
            if program.get("status") != "PROGRAM_BLOCKED":
                program = {**program, "execution_mode": "EXECUTE" if execute else "PLAN_ONLY"}
            return {"release_program": program}
        context = state.get("project_context") if isinstance(state.get("project_context"), dict) else {}
        spec = state.get("release_spec") if isinstance(state.get("release_spec"), dict) else {}
        adapter = get_adapter(str(context.get("adapter") or "generic"))
        program = adapter.release_inventory(context, spec)
        if program.get("status") != "PROGRAM_BLOCKED":
            program["execution_mode"] = "EXECUTE" if execute else "PLAN_ONLY"
        return {"release_program": program}

    def verify_artifacts(state: State):
        program = state.get("release_program")
        if not isinstance(program, dict) or program.get("status") == "PROGRAM_BLOCKED":
            return {}
        release = program.get("release") or {}
        artifacts = release.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            return _block(program, "RELEASE_ARTIFACTS_MISSING", "frozen release has no artifacts to publish.")
        context = state.get("project_context") if isinstance(state.get("project_context"), dict) else {}
        root = _repository_root(program, context)
        verified = []
        for artifact in artifacts:
            relative = Path(str(artifact.get("path") or ""))
            full = (root / relative).resolve()
            if relative.is_absolute() or ".." in relative.parts or not str(full).startswith(str(root) + "/"):
                return _block(program, "ARTIFACT_PATH_ESCAPE", f"artifact path escapes the repository: {relative}")
            if not full.is_file():
                return _block(program, "ARTIFACT_MISSING", f"frozen artifact not found on disk: {relative}")
            digest = _sha256(full)
            frozen = str(artifact.get("sha256") or "").lower()
            if frozen and frozen != digest:
                return _block(program, "ARTIFACT_CHECKSUM_MISMATCH", f"sha256 mismatch for {relative}: frozen {frozen}, computed {digest}", artifact=str(relative))
            verified.append({**artifact, "sha256": digest, "size": full.stat().st_size})
        program = dict(program)
        program["release"] = {**release, "artifacts": verified}
        program["artifact_verification"] = {"status": "PASS", "verified_at": datetime.now(UTC).isoformat(), "artifacts": len(verified)}
        return {"release_program": program}

    def preflight(state: State):
        program = state.get("release_program")
        if not isinstance(program, dict) or program.get("status") == "PROGRAM_BLOCKED":
            return {}
        if program.get("execution_mode") != "EXECUTE" or not state.get("execute"):
            return {}
        github_repo = str(program.get("github_repo") or "").strip()
        if not github_repo:
            return _block(program, "RELEASE_NOT_CONFIGURED", "release.github_repo is not configured; refusing to publish.")
        release = program.get("release") or {}
        tag = str(release.get("tag") or "")
        auth = _gh(["gh", "auth", "status"], github_repo)
        if not auth["ok"]:
            reason = "gh CLI is not installed" if auth.get("returncode") == 127 else "gh auth status failed; run gh auth login with repo scope"
            return _block(program, "GH_CLI_MISSING" if auth.get("returncode") == 127 else "GH_AUTH_REQUIRED", f"{reason}: {str(auth.get('stderr', ''))[-300:]}")
        repository = _gh(["gh", "repo", "view", github_repo], github_repo)
        if not repository["ok"]:
            return _block(program, "RELEASE_REPO_UNREACHABLE", f"frozen GitHub repository is not accessible: {github_repo}: {str(repository.get('stderr', ''))[-300:]}")
        existing = _gh(["gh", "release", "view", tag, "--repo", github_repo, "--json", "tagName,assets,url,isDraft"], github_repo)
        program = dict(program)
        if existing["ok"]:
            try:
                payload = json.loads(str(existing.get("stdout") or "{}"))
            except ValueError:
                payload = {}
            assets = payload.get("assets") if isinstance(payload, dict) else []
            program["publish"] = {
                "mode": "RESUME",
                "release_url": str(payload.get("url") or ""),
                "existing_assets": [str(asset.get("name")) for asset in assets if isinstance(asset, dict)],
            }
        else:
            program["publish"] = {"mode": "CREATE", "existing_assets": []}
        return {"release_program": program}

    def publish(state: State):
        program = state.get("release_program")
        if not isinstance(program, dict) or program.get("status") == "PROGRAM_BLOCKED":
            return {}
        if program.get("execution_mode") != "EXECUTE" or not state.get("execute"):
            return {}
        github_repo = str(program.get("github_repo") or "").strip()
        release = program.get("release") or {}
        publish_state = program.get("publish") or {}
        tag = str(release.get("tag") or "")
        context = state.get("project_context") if isinstance(state.get("project_context"), dict) else {}
        root = _repository_root(program, context)
        program = dict(program)
        if publish_state.get("mode") == "CREATE":
            command = ["gh", "release", "create", tag, "--repo", github_repo, "--title", str(release.get("name") or tag), "--notes", str(release.get("notes") or "")]
            if release.get("draft"):
                command.append("--draft")
            if release.get("prerelease"):
                command.append("--prerelease")
            if release.get("target_commitish"):
                command += ["--target", str(release["target_commitish"])]
            created = _gh(command, github_repo)
            if not created["ok"]:
                LOGGER.warning("RELEASE_CREATE_FAILED tag=%s stderr=%s", tag, str(created.get("stderr", ""))[-300:])
                return {**_block(program, "RELEASE_CREATE_FAILED", f"gh release create failed: {str(created.get('stderr', ''))[-300:]}", tag=tag), "publish_result": {"status": "RELEASE_CREATE_FAILED", "tag": tag}}
        artifacts = []
        uploaded: list[str] = []
        for artifact in release.get("artifacts", []):
            artifact = dict(artifact)
            if artifact.get("status") == "UPLOADED":
                artifacts.append(artifact)
                uploaded.append(str(artifact.get("asset_name")))
                continue
            full = root / str(artifact.get("path"))
            upload = _gh(["gh", "release", "upload", tag, f"{full}#{artifact.get('asset_name')}", "--repo", github_repo, "--clobber"], github_repo)
            if not upload["ok"]:
                artifact["status"] = "FAILED"
                artifacts.append(artifact)
                program["release"] = {**release, "artifacts": artifacts}
                LOGGER.warning("PARTIAL_PUBLISH tag=%s asset=%s", tag, artifact.get("asset_name"))
                return {**_block(program, "PARTIAL_PUBLISH", f"asset upload failed for {artifact.get('asset_name')}: {str(upload.get('stderr', ''))[-300:]}", tag=tag, uploaded=uploaded, failed=str(artifact.get("asset_name"))), "publish_result": {"status": "PARTIAL_PUBLISH", "tag": tag, "uploaded": uploaded}}
            artifact["status"] = "UPLOADED"
            artifact["uploaded_at"] = datetime.now(UTC).isoformat()
            artifacts.append(artifact)
            uploaded.append(str(artifact.get("asset_name")))
        program["release"] = {**release, "artifacts": artifacts}
        program["status"] = "PUBLISHING"
        return {"release_program": program, "publish_result": {"status": "PUBLISH_COMPLETE", "tag": tag, "uploaded": uploaded}}

    def verify_release(state: State):
        program = state.get("release_program")
        publish_result = state.get("publish_result") or {}
        if not isinstance(program, dict) or publish_result.get("status") != "PUBLISH_COMPLETE":
            return {}
        github_repo = str(program.get("github_repo") or "").strip()
        release = program.get("release") or {}
        tag = str(release.get("tag") or "")
        view = _gh(["gh", "release", "view", tag, "--repo", github_repo, "--json", "tagName,assets,url"], github_repo)
        if not view["ok"]:
            return {**_block(program, "RELEASE_VERIFY_MISMATCH", f"release {tag} is not readable after publish: {str(view.get('stderr', ''))[-300:]}", tag=tag), "verify_result": {"status": "RELEASE_UNREADABLE", "tag": tag}}
        try:
            payload = json.loads(str(view.get("stdout") or "{}"))
        except ValueError:
            payload = {}
        remote = {str(asset.get("name")): int(asset.get("size") or 0) for asset in payload.get("assets", []) if isinstance(asset, dict)}
        expected = {str(artifact.get("asset_name")): int(artifact.get("size") or 0) for artifact in release.get("artifacts", [])}
        missing = sorted(name for name in expected if name not in remote)
        mismatched = sorted(name for name, size in expected.items() if name in remote and size and remote[name] != size)
        if missing or mismatched:
            return {**_block(program, "RELEASE_VERIFY_MISMATCH", f"remote release does not match the frozen manifest; missing: {missing or '—'}, size mismatch: {mismatched or '—'}", tag=tag, missing=missing, mismatched=mismatched), "verify_result": {"status": "MISMATCH", "tag": tag, "missing": missing, "mismatched": mismatched}}
        program = dict(program)
        artifacts = [{**artifact, "status": "VERIFIED"} for artifact in release.get("artifacts", [])]
        program["release"] = {**release, "artifacts": artifacts}
        program["status"] = "PUBLISHED"
        program["release_url"] = str(payload.get("url") or program.get("release_url") or "")
        program["published_at"] = datetime.now(UTC).isoformat()
        program.pop("execution_blocker", None)
        return {"release_program": program, "verify_result": {"status": "PASS", "tag": tag, "release_url": program["release_url"], "assets": sorted(expected)}}

    def route_after_preflight(state: State):
        program = state.get("release_program")
        if not isinstance(program, dict) or program.get("status") == "PROGRAM_BLOCKED":
            return END
        if program.get("execution_mode") == "EXECUTE" and state.get("execute"):
            return "publish"
        return END

    def route_after_publish(state: State):
        if (state.get("publish_result") or {}).get("status") == "PUBLISH_COMPLETE":
            return "verify_release"
        return END

    graph.add_node("reconcile", reconcile)
    graph.add_node("freeze", freeze)
    graph.add_node("verify_artifacts", verify_artifacts)
    graph.add_node("preflight", preflight)
    graph.add_node("publish", publish)
    graph.add_node("verify_release", verify_release)
    graph.add_edge(START, "reconcile")
    graph.add_edge("reconcile", "freeze")
    graph.add_edge("freeze", "verify_artifacts")
    graph.add_edge("verify_artifacts", "preflight")
    graph.add_conditional_edges("preflight", route_after_preflight, {"publish": "publish", END: END})
    graph.add_conditional_edges("publish", route_after_publish, {"verify_release": "verify_release", END: END})
    graph.add_edge("verify_release", END)
    return graph.compile()
