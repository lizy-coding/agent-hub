"""Content-bound integration with durable per-repository progress."""
from __future__ import annotations

import subprocess
from dataclasses import asdict
from pathlib import Path

from agent_hub.execution.completion_evidence import (
    CompletionContract, EvidenceBinding, ExecutionEvidence, Milestone, Outcome,
    ValidationEvidence, evaluate_completion,
)
from agent_hub.execution.control import ControlError, ExecutionStore, digest
from agent_hub.execution.validation import receipts_pass


def git(root: Path, *args: str, input: str | None = None) -> str:
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(root), *args],
                            input=input, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ControlError(f"GIT_OPERATION_FAILED:{args[0]}:{result.stderr[-300:]}")
    return result.stdout.rstrip("\n")


def changed(root: Path) -> list[str]:
    # NUL parsing preserves names with spaces; reject ambiguous rename states.
    raw = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    values = []
    for entry in raw.split("\0"):
        if not entry:
            continue
        if entry[0] in "RC" or entry[1] in "RC":
            raise ControlError("INTEGRATION_RENAME_STATE_UNSUPPORTED")
        values.append(entry[3:])
    return sorted(values)


def scope_ok(paths: list[str], allowed: list[str]) -> bool:
    return all(any(path == value or path.startswith(value.rstrip("/") + "/")
                   for value in allowed) for path in paths)


def completion_gate(request: dict, repository: str, result: dict, milestone: Milestone,
                    root: Path | None = None, commit: str | None = None):
    source = next(item["base_revision"] for item in request["repositories"] if item["repository"] == repository)
    binding = EvidenceBinding(request["project_id"], repository, request["task_id"],
                              request["contract_sha256"], source, result["output_tree_oid"])
    required = tuple(digest(item) for item in request["validation_by_repository"][repository])
    paths = tuple(result["changed_files"])
    contract = CompletionContract(binding, paths, required, allow_no_effect=not paths)
    execution = ExecutionEvidence(binding, Outcome.SUCCESS, paths, True, True)
    receipts = tuple(ValidationEvidence(binding, digest({key: item[key] for key in
                                                         ("check_id", "cwd", "timeout_seconds")}),
                                        item["status"] == "PASS", item["log_sha256"],
                                        str(item["environment"])) for item in result["validation_receipts"])
    return evaluate_completion(contract, milestone, execution, validations=receipts,
                               repository_root=root, commit_oid=commit)


def validate_result(store: ExecutionStore, request: dict, worker: dict) -> list[str]:
    try:
        record = store.verify(request)
        saved = record.get("result")
        if not saved or not store.result_matches(request, worker):
            return ["STALE_EXECUTION_RESULT"]
        if digest({key: worker.get(key) for key in saved}) != digest(saved):
            return ["WORKER_RECEIPT_MISMATCH"]
        results = worker.get("repositories", {})
        if set(results) != {item["repository"] for item in request["repositories"]}:
            return ["REPOSITORY_RESULTS_MISMATCH"]
        issues = []
        if worker.get("status") != "SUCCESS" or worker.get("scope_guard") != "PASS":
            issues.append("WORKER_NOT_VALIDATED")
        if not any(value.get("changed_files") for value in results.values()):
            issues.append("MIGRATION_NO_EFFECT")
        for repository, result in results.items():
            if not scope_ok(result["changed_files"], request["allowed_paths_by_repository"][repository]):
                issues.append(f"SCOPE_VIOLATION:{repository}")
            if not receipts_pass(request["validation_by_repository"][repository],
                                 result.get("validation_receipts", []), result.get("output_tree_oid", "")):
                issues.append(f"REQUIRED_VALIDATION_MISSING_OR_FAILED:{repository}")
            else:
                issues.extend(completion_gate(request, repository, result, Milestone.VALIDATED).issues)
        return issues
    except (ControlError, KeyError, TypeError, ValueError) as error:
        return [str(error) or "INVALID_EXECUTION_RESULT"]


def integrate(store: ExecutionStore, request: dict, worker: dict, roots: dict[str, Path]) -> dict:
    with store.repositories(request):
        record = store.verify(request)
        issues = validate_result(store, request, worker)
        if issues:
            raise ControlError(";".join(issues))
        results = worker["repositories"]
        if set(roots) != set(results):
            raise ControlError("INTEGRATION_ROOTS_MISMATCH")
        progress = record.setdefault("integration", {})
        message = f"refactor: {request['task_id']} [{request['task_id']}] attempt:{request['attempt_id']}"
        # Preflight every repository before applying the first diff.
        for repository in sorted(roots):
            root, result = roots[repository], results[repository]
            base = next(item["base_revision"] for item in request["repositories"] if item["repository"] == repository)
            step = progress.setdefault(repository, {"phase": "PENDING", "base_revision": base,
                                                   "expected_tree": result["output_tree_oid"]})
            head = git(root, "rev-parse", "HEAD")
            if head != base:
                # Repair the exact crash window after commit and before journal save.
                if (git(root, "show", "-s", "--format=%P", head) != base
                        or git(root, "show", "-s", "--format=%B", head) != message
                        or git(root, "rev-parse", f"{head}^{{tree}}") != step["expected_tree"]):
                    raise ControlError(f"INTEGRATION_HEAD_CHANGED:{repository}")
                step.update(phase="COMMITTED", commit=head)
            dirty = changed(root)
            if dirty and (step["phase"] != "APPLYING" or dirty != sorted(result["changed_files"])):
                raise ControlError(f"INTEGRATION_WORKSPACE_DIRTY:{repository}")
            if not dirty and step["phase"] != "COMMITTED" and result["diff"]:
                git(root, "apply", "--check", "--whitespace=nowarn", "-", input=result["diff"])
        record["phase"] = "INTEGRATING"
        store.save(request, record)
        for repository in sorted(roots):
            root, result, step = roots[repository], results[repository], progress[repository]
            if step["phase"] != "COMMITTED":
                step["phase"] = "APPLYING"
                store.save(request, record)
                if not changed(root) and result["diff"]:
                    git(root, "apply", "--whitespace=nowarn", "-", input=result["diff"])
                if changed(root) != sorted(result["changed_files"]):
                    raise ControlError(f"INTEGRATION_DIFF_MISMATCH:{repository}")
                if result["changed_files"]:
                    git(root, "--literal-pathspecs", "add", "--all", "--", *result["changed_files"])
                if git(root, "write-tree") != result["output_tree_oid"]:
                    raise ControlError(f"INTEGRATION_TREE_MISMATCH:{repository}")
                if git(root, "rev-parse", "HEAD") != step["base_revision"]:
                    raise ControlError(f"INTEGRATION_HEAD_CHANGED:{repository}")
                if result["changed_files"]:
                    git(root, "commit", "--no-verify", "-m", message)
                step.update(phase="COMMITTED", commit=git(root, "rev-parse", "HEAD"))
                store.save(request, record)
            gate = completion_gate(request, repository, result, Milestone.INTEGRATED, root, step["commit"])
            step["gate"] = {**asdict(gate), "passed": gate.passed}
            store.save(request, record)
            if not gate.passed:
                raise ControlError(";".join(gate.issues))
        record["phase"] = "INTEGRATED"
        store.save(request, record)
        return {"status": "INTEGRATED", "attempt_id": request["attempt_id"],
                "commits": {name: step["commit"] for name, step in progress.items()},
                "repositories": progress}
