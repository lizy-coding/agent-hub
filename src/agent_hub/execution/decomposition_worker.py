"""Multi-repository adapter for a frozen decomposition MigrationTask.

It deliberately reuses the local Code Worker process and Codex invocation
model.  The only difference from the refactor worker is that a task can own
more than one isolated Git worktree.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from agent_hub.projects.decomposition_config import load_decomposition_project


CLUSTER_ROOT = Path(os.environ.get("AGENT_HUB_DECOMPOSITION_CLUSTER_ROOT", str(load_decomposition_project().cluster_root)))
CODEX_PROFILE = os.environ.get("AGENT_HUB_CODEX_PROFILE", "")
CODEX_TIMEOUT_SECONDS = int(os.environ.get("AGENT_HUB_CODEX_TIMEOUT_SECONDS", "1800"))


def _snapshot(worktree: Path) -> tuple[list[str], str]:
    # Normalize the index so staged moves, untracked additions and deletions
    # are all captured by the diff we hand to integration.  Rename detection
    # must stay off: a collapsed R100 hides the deleted source path, which the
    # integration/architecture guards rely on to prove the source is gone.
    subprocess.run(["git", "add", "-A"], cwd=worktree, check=True, capture_output=True, text=True)
    changed = subprocess.check_output(["git", "diff", "--cached", "--no-renames", "--name-only", "HEAD"], cwd=worktree, text=True).splitlines()
    # Integration applies the Worker artifact to a managed worktree.  Binary
    # application/host assets require Git's complete binary patch form.
    diff = subprocess.check_output(["git", "diff", "--cached", "--no-renames", "--binary", "HEAD"], cwd=worktree, text=True)
    return sorted(set(changed)), diff


class DecompositionCodeExecutor:
    """Run one frozen multi-repository task outside all managed worktrees."""

    def __init__(self, cluster_root: Path | None = None, codex_binary: str = "codex") -> None:
        project = load_decomposition_project()
        selected_root = cluster_root or Path(os.environ.get("AGENT_HUB_DECOMPOSITION_CLUSTER_ROOT", str(CLUSTER_ROOT)))
        self.cluster_root = selected_root.resolve()
        self.repository_paths = project.repository_paths
        self.codex_binary = codex_binary

    def execute(self, payload: dict[str, object]) -> dict[str, object]:
        task_id = str(payload.get("task_id", ""))
        repositories = payload.get("repositories")
        scope, scope_error = self._writable_scope(payload)
        if not task_id or not isinstance(repositories, list) or not repositories or scope_error:
            return self._result(task_id, "WORKER_SCOPE_CONFIGURATION_ERROR", scope_error or "invalid_migration_request")
        if {str(item.get("repository", "")) for item in repositories if isinstance(item, dict)} != set(scope):
            return self._result(task_id, "WORKER_SCOPE_CONFIGURATION_ERROR", "workspace_repositories_do_not_match_frozen_writable_scope")
        if any(not isinstance(item, dict) or not item.get("writable") for item in repositories):
            return self._result(task_id, "WORKER_SCOPE_CONFIGURATION_ERROR", "repository_missing_frozen_writable_role")
        execution_id = f"migration-{uuid4()}"
        root = Path(tempfile.mkdtemp(prefix="agent-hub-worker-"))
        worktrees: dict[str, Path] = {}
        try:
            for item in repositories:
                if not isinstance(item, dict):
                    return self._result(task_id, "WORKER_DISPATCH_FAILED", "invalid_repository_entry", execution_id, root)
                repository, base = str(item.get("repository", "")), str(item.get("base_revision", ""))
                source = self.repository_paths.get(repository, self.cluster_root / repository)
                if not repository or not base or not source.is_dir():
                    return self._result(task_id, "WORKER_DISPATCH_FAILED", "invalid_repository_source", execution_id, root)
                worktree = root / repository
                subprocess.run(["git", "worktree", "add", "--detach", str(worktree), base], cwd=source, check=True, capture_output=True, text=True)
                worktrees[repository] = worktree
            prompt = self._prompt(payload, worktrees)
            command = [self.codex_binary, "exec"]
            if CODEX_PROFILE:
                command.extend(["--profile", CODEX_PROFILE])
            command.extend(["--sandbox", "workspace-write", "--skip-git-repo-check", "--cd", str(root)])
            for repository in sorted(scope):
                command.extend(["--add-dir", str(worktrees[repository])])
            process = subprocess.Popen([*command, prompt], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=int(payload.get("timeout_seconds", CODEX_TIMEOUT_SECONDS)))
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                # Kill the entire session so a leaked codex/unified-exec child
                # cannot keep writing into a worktree we are about to remove.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    stdout, stderr = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    stdout, stderr = process.communicate()
                return self._result(task_id, "CODEX_EXECUTION_TIMEOUT", "timeout", execution_id, root, process.returncode, {}, (stdout or "")[-2000:], (stderr or "")[-2000:])
            results = {name: {"changed_files": changed, "diff": diff} for name, worktree in worktrees.items() for changed, diff in [_snapshot(worktree)]}
            if exit_code:
                return self._result(task_id, "CODEX_EXECUTION_FAILED", "codex", execution_id, root, exit_code, results, stdout, stderr)
            unauthorized = self._unauthorized(payload, results)
            if unauthorized:
                return self._result(task_id, "SCOPE_VIOLATION", "migration_scope_guard", execution_id, root, process.returncode, results, stdout, stderr, unauthorized)
            return self._result(task_id, "SUCCESS", "", execution_id, root, process.returncode, results, stdout, stderr)
        except subprocess.TimeoutExpired as error:
            return self._result(task_id, "CODEX_EXECUTION_TIMEOUT", "timeout", execution_id, root, None, {}, getattr(error, "stdout", "") or "", getattr(error, "stderr", "") or "")
        except Exception as error:
            return self._result(task_id, "WORKER_DISPATCH_FAILED", str(error), execution_id, root)
        finally:
            for repository, worktree in worktrees.items():
                source = self.repository_paths.get(repository, self.cluster_root / repository)
                subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=source, capture_output=True)
            shutil.rmtree(root, ignore_errors=True)

    @staticmethod
    def _writable_scope(payload: dict[str, object]) -> tuple[dict[str, list[str]], str]:
        declared = payload.get("writable_repositories")
        allowed = payload.get("allowed_paths_by_repository")
        if not isinstance(declared, list) or not isinstance(allowed, dict):
            return {}, "missing_frozen_writable_scope"
        scope: dict[str, list[str]] = {}
        for item in declared:
            if not isinstance(item, dict) or not item.get("writable"):
                return {}, "invalid_frozen_writable_repository"
            repository = str(item.get("repository", ""))
            paths = item.get("allowed_paths")
            if not repository or not isinstance(paths, list) or not paths or [str(path) for path in paths] != [str(path) for path in allowed.get(repository, [])]:
                return {}, "invalid_frozen_writable_paths"
            scope[repository] = [str(path) for path in paths]
        return scope, ""

    @staticmethod
    def _prompt(payload: dict[str, object], worktrees: dict[str, Path]) -> str:
        allowed = payload.get("allowed_paths_by_repository", {})
        places = "; ".join(f"{repo}: {', '.join(allowed.get(repo, []))}" for repo in worktrees) if isinstance(allowed, dict) else ""
        roles = payload.get("writable_repositories", [])
        role_text = "; ".join(f"{item.get('repository')}={item.get('role')}" for item in roles if isinstance(item, dict))
        instructions = payload.get("execution_instructions", [])
        instruction_text = " ".join(str(item) for item in instructions) if isinstance(instructions, list) else ""
        return ("Frozen Decomposition MigrationTask. Writable isolated repositories: "
                + ", ".join(worktrees) + ". Allowed paths: " + places + ". "
                + "Frozen roles: " + role_text + ". "
                + "Task: " + str(payload.get("requirement", "")) + ". Execution instructions: " + instruction_text + ". "
                + "Do not commit, push, merge, release, modify manifests outside the stated task, or touch ordinary user worktrees. "
                + "Move files without copying. Prefer `git mv`; when the isolated worktree sandbox cannot write the parent repository's worktree metadata, use a filesystem move instead. The Worker will stage and verify the resulting source deletions and destination additions after Codex exits. "
                + "After the move, verify with `git status --porcelain` that the source app directories (for example root lib/main.dart and root lib/app) no longer exist and no duplicates remain. "
                + "When rewriting manifest paths, keep every other declared workspace member (packages/*, plugins/*) untouched at the workspace root. "
                + "If verification fails or a file cannot be moved, keep working until `git status --porcelain` shows exactly the intended moved set; do not stop early.")

    @staticmethod
    def _unauthorized(payload: dict[str, object], results: dict[str, object]) -> list[str]:
        allowed = payload.get("allowed_paths_by_repository", {})
        if not isinstance(allowed, dict):
            return ["missing_allowed_paths"]
        unauthorized: list[str] = []
        for repository, result in results.items():
            prefixes = [str(value).rstrip("/") for value in allowed.get(repository, [])]
            for path in result.get("changed_files", []):
                if not any(prefix in {"", "."} or str(path) == prefix or str(path).startswith(prefix + "/") for prefix in prefixes):
                    unauthorized.append(f"{repository}:{path}")
        return unauthorized

    @staticmethod
    def _result(task_id: str, status: str, reason: str, execution_id: str = "", workspace: Path | None = None, exit_code: int | None = None, repositories: dict[str, object] | None = None, stdout: str = "", stderr: str = "", unauthorized: list[str] | None = None) -> dict[str, object]:
        return {"status": status, "task_id": task_id, "reason": reason, "worker_execution_id": execution_id, "worker_workspace": str(workspace) if workspace else "", "dispatched_at": datetime.now(UTC).isoformat(), "exit_code": exit_code, "repositories": repositories or {}, "scope_guard": "FAILED" if unauthorized else ("PASS" if status == "SUCCESS" else "NOT_RUN"), "unauthorized_files": unauthorized or [], "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]}
