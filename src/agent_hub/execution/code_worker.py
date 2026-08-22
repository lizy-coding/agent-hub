"""Small local-only bridge for a frozen Flutter development task.

The hosted graph never receives a local checkout path.  This module is the
Mac-side boundary that owns that path and rejects any request outside its
single-repository, exact-path contract.
"""

from __future__ import annotations

import os
import platform
import signal
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
import yaml


DEFAULT_PRIMARY_REPOSITORY = os.environ.get("AGENT_HUB_PRIMARY_REPOSITORY", "primary")
CODEX_TIMEOUT_SECONDS = int(os.environ.get("AGENT_HUB_CODEX_TIMEOUT_SECONDS", "900"))
CODEX_PROFILE = os.environ.get("AGENT_HUB_CODEX_PROFILE", "")
BUILD_TIMEOUT_SECONDS = int(os.environ.get("AGENT_HUB_BUILD_TIMEOUT_SECONDS", "900"))

_ALLOWED_VALIDATION_COMMANDS = {"flutter_analyze", "flutter_build", "flutter_build:macos", "flutter_build:windows", "flutter_build:apk"}

_BUILD_COMMANDS = {
    "macos": ["flutter", "build", "macos", "--debug"],
    "windows": ["flutter", "build", "windows", "--debug"],
    "apk": ["flutter", "build", "apk", "--debug"],
}


def _build_target(command: str) -> str:
    """Map a validation token to a build target.  Bare flutter_build is the
    macOS alias so pre-existing app-level tasks keep their current behavior."""
    return "macos" if command == "flutter_build" else command.removeprefix("flutter_build:")


@dataclass(frozen=True)
class WorkerRequest:
    repository: str
    base_revision: str
    task_id: str
    requirement: str
    allowed_paths: list[str]
    validation: list[str]

    @classmethod
    def from_json(cls, value: dict[str, object], expected_repository: str) -> "WorkerRequest":
        allowed = value.get("allowed_paths")
        validation = value.get("validation", [])
        if value.get("repository") != expected_repository:
            raise ValueError("invalid_repository")
        if not isinstance(allowed, list) or not allowed or not all(isinstance(p, str) for p in allowed):
            raise ValueError("invalid_allowed_paths")
        if not isinstance(validation, list) or not all(isinstance(command, str) for command in validation):
            raise ValueError("invalid_validation")
        for path in allowed:
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts or path.startswith(".hermes/"):
                raise ValueError("invalid_allowed_paths")
        # Commands are identifiers chosen by the DevelopmentTask, not shell.
        if any(command not in _ALLOWED_VALIDATION_COMMANDS and not command.startswith("flutter_test:") for command in validation):
            raise ValueError("arbitrary_shell_forbidden")
        return cls(
            repository=expected_repository,
            base_revision=str(value.get("base_revision", "")),
            task_id=str(value.get("task_id", "")),
            requirement=str(value.get("requirement", "")),
            allowed_paths=list(allowed),
            validation=list(validation),
        )


def _changed_files(worktree: Path) -> list[str]:
    tracked = subprocess.check_output(["git", "diff", "--name-only"], cwd=worktree, text=True).splitlines()
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=worktree, text=True).splitlines()
    return sorted(set(tracked + untracked))


def _complete_diff(worktree: Path, changed: list[str]) -> str:
    tracked = subprocess.check_output(["git", "diff", "--"], cwd=worktree, text=True)
    pieces = [tracked] if tracked else []
    for path in changed:
        if path in subprocess.check_output(["git", "diff", "--name-only"], cwd=worktree, text=True).splitlines():
            continue
        content = (worktree / path).read_text(encoding="utf-8")
        pieces.append(f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(content.splitlines())} @@\n" + "".join(f"+{line}\n" for line in content.splitlines()))
    return "".join(pieces)


def _diagnostic_counts(output: str) -> tuple[int, int]:
    return (sum(1 for line in output.splitlines() if line.lstrip().startswith("error")), sum(1 for line in output.splitlines() if line.lstrip().startswith("warning")))


class LocalCodeExecutor:
    """MVP-L2 execution sequence, intentionally limited to one local primary."""

    def __init__(self, repository_path: Path, codex_binary: str = "codex", repository_id: str = DEFAULT_PRIMARY_REPOSITORY) -> None:
        self.repository_path = repository_path.resolve()
        self.codex_binary = codex_binary
        self.repository_id = repository_id

    def _result(self, request: WorkerRequest, status: str, **values: object) -> dict[str, object]:
        return {"status": status, "task_id": getattr(request, "task_id", ""), "repository": request.repository, "base_revision": request.base_revision, "exit_code": values.pop("exit_code", None), "changed_files": values.pop("changed_files", []), "diff": values.pop("diff", ""), "validation": values.pop("validation", {}), "scope_guard": values.pop("scope_guard", "NOT_RUN"), "stdout_tail": values.pop("stdout_tail", ""), "stderr_tail": values.pop("stderr_tail", ""), **values}

    def _codex_run(self, worktree: Path, request: WorkerRequest) -> tuple[str, int | None, str, str]:
        command = [self.codex_binary, "exec"]
        if CODEX_PROFILE:
            command.extend(["--profile", CODEX_PROFILE])
        command.extend(["--sandbox", "workspace-write", "--skip-git-repo-check", "--cd", str(worktree), self._codex_prompt(request)])
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=CODEX_TIMEOUT_SECONDS)
            return ("completed", process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            # The CLI can spawn children.  End the entire session before
            # draining pipes so an inherited descriptor cannot hold this HTTP
            # request open forever.
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                stdout, stderr = process.communicate()
            return ("timeout", process.returncode, stdout, stderr)

    def execute(self, request: WorkerRequest) -> dict[str, object]:
        if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repository_path, text=True).strip() != request.base_revision:
            return self._result(request, "CODEX_EXECUTION_FAILED", reason="base_revision_mismatch")
        root = Path(tempfile.mkdtemp(prefix="agent-hub-worker-"))
        worktree = root / request.repository
        try:
            subprocess.run(["git", "worktree", "add", "--detach", str(worktree), request.base_revision], cwd=self.repository_path, check=True, capture_output=True, text=True)
            self._link_path_dependencies(worktree, root)
            preflight = subprocess.run(["flutter", "pub", "get"], cwd=worktree, capture_output=True, text=True)
            if preflight.returncode:
                return self._result(request, "CODEX_EXECUTION_FAILED", reason="dependency_preflight", exit_code=preflight.returncode, stderr_tail=preflight.stderr[-2000:])
            baseline = subprocess.run(["flutter", "analyze"], cwd=worktree, capture_output=True, text=True)
            baseline_errors, baseline_warnings = _diagnostic_counts(baseline.stdout + baseline.stderr)
            outcome, exit_code, stdout, stderr = self._codex_run(worktree, request)
            if outcome == "timeout":
                return self._result(request, "CODEX_EXECUTION_TIMEOUT", exit_code=exit_code, stdout_tail=stdout[-2000:], stderr_tail=stderr[-2000:], scope_guard="NOT_RUN")
            if exit_code:
                return self._result(request, "CODEX_EXECUTION_FAILED", reason="codex", exit_code=exit_code, stdout_tail=stdout[-2000:], stderr_tail=stderr[-2000:], scope_guard="NOT_RUN")
            changed = _changed_files(worktree)
            unauthorized = sorted(set(changed) - set(request.allowed_paths))
            if unauthorized:
                return self._result(request, "SCOPE_VIOLATION", exit_code=exit_code, changed_files=changed, unauthorized_files=unauthorized, scope_guard="FAILED", stdout_tail=stdout[-2000:], stderr_tail=stderr[-2000:])
            dart_files = [path for path in changed if path.endswith(".dart")]
            if dart_files:
                subprocess.run(["dart", "format", *dart_files], cwd=worktree, check=True, capture_output=True, text=True)
            # A frozen task may legitimately rewrite an explicitly allowed
            # path dependency. Rebuild external topology before validation.
            self._link_path_dependencies(worktree, root)
            changed = _changed_files(worktree)
            unauthorized = sorted(set(changed) - set(request.allowed_paths))
            if unauthorized:
                return self._result(request, "SCOPE_VIOLATION", exit_code=exit_code, changed_files=changed, unauthorized_files=unauthorized, scope_guard="FAILED", stdout_tail=stdout[-2000:], stderr_tail=stderr[-2000:])
            tests: dict[str, int] = {}
            for command in request.validation:
                if command.startswith("flutter_test:"):
                    path = command.removeprefix("flutter_test:")
                    tests[path] = subprocess.run(["flutter", "test", path], cwd=worktree).returncode
            analyze = {"new_errors": 0, "new_warnings": 0, "status": "NOT_REQUIRED"}
            if "flutter_analyze" in request.validation:
                final = subprocess.run(["flutter", "analyze"], cwd=worktree, capture_output=True, text=True)
                errors, warnings = _diagnostic_counts(final.stdout + final.stderr)
                analyze = {"new_errors": max(0, errors-baseline_errors), "new_warnings": max(0, warnings-baseline_warnings), "status": "PASS" if errors <= baseline_errors and warnings <= baseline_warnings else "FAIL_REGRESSION"}
            build = {"status": "NOT_REQUIRED"}
            build_commands = [command for command in request.validation if command == "flutter_build" or command.startswith("flutter_build:")]
            if build_commands:
                build = self._run_builds(worktree, build_commands)
            if any(code != 0 for code in tests.values()):
                return self._result(request, "VALIDATION_FAILED", exit_code=exit_code, changed_files=changed, diff=_complete_diff(worktree, changed), validation={"tests": tests, "analyze": analyze, "build": build}, scope_guard="PASS", stdout_tail=stdout[-2000:], stderr_tail=stderr[-2000:])
            if analyze["status"] == "FAIL_REGRESSION":
                return self._result(request, "VALIDATION_FAILED", exit_code=exit_code, changed_files=changed, diff=_complete_diff(worktree, changed), validation={"tests": tests, "analyze": analyze, "build": build}, scope_guard="PASS", stdout_tail=stdout[-2000:], stderr_tail=stderr[-2000:])
            if build["status"] == "FAIL":
                return self._result(request, "VALIDATION_FAILED", exit_code=exit_code, changed_files=changed, diff=_complete_diff(worktree, changed), validation={"tests": tests, "analyze": analyze, "build": build}, scope_guard="PASS", stdout_tail=stdout[-2000:], stderr_tail=stderr[-2000:])
            return self._result(request, "SUCCESS" if changed else "NO_CHANGE_REQUIRED", exit_code=exit_code, changed_files=changed, diff=_complete_diff(worktree, changed), validation={"tests": tests, "analyze": analyze, "build": build}, scope_guard="PASS", stdout_tail=stdout[-2000:], stderr_tail=stderr[-2000:], review="APPROVED" if changed else "CHANGES_REQUIRED")
        except Exception as error:
            changed = _changed_files(worktree) if worktree.exists() else []
            return self._result(request, "CODEX_EXECUTION_FAILED", reason="worker_exception", changed_files=changed, stderr_tail=str(error)[-2000:])
        finally:
            if worktree.exists():
                subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=self.repository_path, capture_output=True)
            shutil.rmtree(root, ignore_errors=True)

    def _build_target_available(self, target: str) -> bool:
        if target == "macos":
            return platform.system() == "Darwin"
        if target == "windows":
            return platform.system() == "Windows"
        if target == "apk":
            return shutil.which("adb") is not None or shutil.which("java") is not None
        return False

    def _build_unavailable_reason(self, target: str) -> str:
        if target == "windows":
            return "non_windows_host"
        if target == "apk":
            return "android_toolchain_unavailable"
        return "non_darwin_host"

    def _run_build(self, worktree: Path, target: str = "macos") -> dict[str, object]:
        """Target-qualified packaging smoke test.

        The host must be capable of the requested target.  Non-capable hosts
        skip (SKIPPED is non-fatal); CI remains the authoritative packaging
        gate.  A real build failure or timeout is fatal (FAIL ->
        VALIDATION_FAILED) so packaging-breaking changes are caught inside
        agent-hub runs instead of only at CI time.
        """
        if target not in _BUILD_COMMANDS:
            return {"status": "FAIL", "reason": "unsupported_build_target", "target": target}
        if not self._build_target_available(target):
            return {"status": "SKIPPED", "reason": self._build_unavailable_reason(target), "target": target}
        try:
            process = subprocess.run(
                _BUILD_COMMANDS[target],
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=BUILD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "reason": "timeout", "exit_code": None, "target": target}
        if process.returncode == 0:
            return {"status": "PASS", "exit_code": 0, "target": target}
        return {"status": "FAIL", "exit_code": process.returncode, "stderr_tail": process.stderr[-2000:], "target": target}

    def _run_builds(self, worktree: Path, commands: list[str]) -> dict[str, object]:
        """Aggregate a target-qualified build matrix.  Any target failing is a
        validation failure; a build where every target is skipped is SKIPPED."""
        results = [self._run_build(worktree, _build_target(command)) for command in commands]
        if results and all(result.get("status") == "SKIPPED" for result in results):
            return {"status": "SKIPPED", "reason": ";".join(sorted({str(result.get("reason")) for result in results})), "targets": [result.get("target") for result in results]}
        failed = [result for result in results if result.get("status") == "FAIL"]
        if failed:
            first = failed[0]
            return {"status": "FAIL", "exit_code": first.get("exit_code"), "stderr_tail": first.get("stderr_tail", ""), "target": first.get("target"), "results": results}
        return {"status": "PASS", "exit_code": 0, "results": results}

    def _link_path_dependencies(self, worktree: Path, root: Path) -> None:
        # Workspace members can declare external path dependencies too. Scan
        # tracked manifests and recreate only dependencies that resolve outside
        # the isolated repository; internal package paths travel with it.
        manifests = subprocess.check_output(
            ["git", "ls-files", "*/pubspec.yaml", "pubspec.yaml"],
            cwd=worktree,
            text=True,
        ).splitlines()
        for relative_manifest in manifests:
            manifest = worktree / relative_manifest
            payload = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            for section in ("dependencies", "dev_dependencies", "dependency_overrides"):
                for name, value in (payload.get(section) or {}).items():
                    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
                        continue
                    relative = value["path"]
                    target = (manifest.parent / relative).resolve()
                    if worktree == target or worktree in target.parents:
                        continue
                    configured = os.environ.get(
                        f"AGENT_HUB_PATH_DEPENDENCY_{str(name).upper().replace('-', '_')}"
                    )
                    source_manifest = self.repository_path / relative_manifest
                    source = Path(configured).resolve() if configured else (source_manifest.parent / relative).resolve()
                    if source.is_dir() and not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.symlink_to(source, target_is_directory=True)

    @staticmethod
    def _codex_prompt(request: WorkerRequest) -> str:
        return "Frozen DevelopmentTask. Modify only: " + ", ".join(request.allowed_paths) + ". Requirement: " + request.requirement + ". Manifest or dependency changes are allowed only when their exact files are frozen above. No commit, push, merge, release, or arbitrary shell-command changes."


def execute_request(payload: dict[str, object], executor: LocalCodeExecutor) -> dict[str, object]:
    try:
        request = WorkerRequest.from_json(payload, executor.repository_id)
    except ValueError as error:
        return {"status": "CODEX_EXECUTION_FAILED", "task_id": str(payload.get("task_id", "")), "repository": str(payload.get("repository", "")), "base_revision": str(payload.get("base_revision", "")), "exit_code": None, "changed_files": [], "diff": "", "validation": {}, "scope_guard": "NOT_RUN", "stdout_tail": "", "stderr_tail": str(error)}
    return executor.execute(request)
