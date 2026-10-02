"""Independent completion gates; no Graph, registry, worker or schema mutation.

Inputs must come from the trusted orchestrator, not be constructed by a worker.
Git proof is read back locally. Validation and platform receipts are attestations
from trusted collectors; this module neither runs tests nor operates devices.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath


class Milestone(str, Enum):
    EXECUTED = "EXECUTED"
    VALIDATED = "VALIDATED"
    INTEGRATED = "INTEGRATED"
    PLATFORM_ACCEPTED = "PLATFORM_ACCEPTED"


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


def _required(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identity and evidence fields must be nonempty strings")


def _oid(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise ValueError("Git identity must be a full lowercase object ID")


def _sha256(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("digest must be a lowercase SHA256")


def _paths(values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or len(set(values)) != len(values):
        raise ValueError("paths must be an immutable tuple of unique exact paths")
    for value in values:
        _required(value)
        path = PurePosixPath(value)
        if (path.is_absolute() or ".." in path.parts or path.as_posix() != value
                or value == "." or "\\" in value or any(c in value for c in "\n\r\0")):
            raise ValueError("paths must be normalized repository-relative file paths")


@dataclass(frozen=True)
class EvidenceBinding:
    project_id: str
    repository_id: str
    task_id: str
    contract_sha256: str
    source_revision: str
    output_tree_oid: str

    def __post_init__(self) -> None:
        for value in (self.project_id, self.repository_id, self.task_id):
            _required(value)
        _sha256(self.contract_sha256)
        _oid(self.source_revision)
        _oid(self.output_tree_oid)


@dataclass(frozen=True)
class CompletionContract:
    binding: EvidenceBinding
    allowed_paths: tuple[str, ...]
    required_checks: tuple[str, ...]
    required_platforms: tuple[str, ...] = ()
    allow_no_effect: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.binding, EvidenceBinding):
            raise ValueError("binding must be an EvidenceBinding")
        _paths(self.allowed_paths)
        if not self.required_checks:
            raise ValueError("at least one frozen validation check is required")
        for values in (self.required_checks, self.required_platforms):
            if not isinstance(values, tuple) or len(set(values)) != len(values):
                raise ValueError("requirements must be unique immutable tuples")
            for value in values:
                _required(value)
        if type(self.allow_no_effect) is not bool:
            raise ValueError("allow_no_effect must be a boolean")


@dataclass(frozen=True)
class ExecutionEvidence:
    binding: EvidenceBinding
    outcome: Outcome
    changed_paths: tuple[str, ...]
    scope_passed: bool
    review_approved: bool

    def __post_init__(self) -> None:
        if not isinstance(self.binding, EvidenceBinding):
            raise ValueError("binding must be an EvidenceBinding")
        _paths(self.changed_paths)
        if not isinstance(self.outcome, Outcome):
            raise ValueError("execution outcome must be an Outcome")
        if type(self.scope_passed) is not bool or type(self.review_approved) is not bool:
            raise ValueError("gate results must be booleans")


@dataclass(frozen=True)
class ValidationEvidence:
    binding: EvidenceBinding
    check_id: str
    passed: bool
    evidence_ref: str
    environment: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding, EvidenceBinding):
            raise ValueError("binding must be an EvidenceBinding")
        for value in (self.check_id, self.evidence_ref, self.environment):
            _required(value)
        if type(self.passed) is not bool:
            raise ValueError("validation result must be a boolean")


@dataclass(frozen=True)
class ArtifactEvidence:
    binding: EvidenceBinding
    platform: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding, EvidenceBinding):
            raise ValueError("binding must be an EvidenceBinding")
        _required(self.platform)
        _sha256(self.sha256)


@dataclass(frozen=True)
class PlatformEvidence:
    binding: EvidenceBinding
    platform: str
    artifact_sha256: str
    passed: bool
    environment: str
    interaction_ref: str
    readback_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding, EvidenceBinding):
            raise ValueError("binding must be an EvidenceBinding")
        for value in (self.platform, self.environment, self.interaction_ref, self.readback_ref):
            _required(value)
        _sha256(self.artifact_sha256)
        if type(self.passed) is not bool:
            raise ValueError("platform result must be a boolean")


@dataclass(frozen=True)
class GateResult:
    milestone: Milestone
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


class _GitProofError(Exception):
    pass


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", "--no-optional-locks", "-C", str(root), *args],
        capture_output=True, timeout=10, check=False,
    )
    if result.returncode:
        raise _GitProofError()
    return result.stdout


def _integration_issues(contract: CompletionContract, execution: ExecutionEvidence,
                        repository_root: Path | None, commit_oid: str | None) -> list[str]:
    if repository_root is None or commit_oid is None:
        return ["INTEGRATION_PROOF_MISSING"]
    try:
        _oid(commit_oid)
    except ValueError:
        return ["INTEGRATION_COMMIT_INVALID"]
    try:
        root = repository_root.resolve()
        actual_root = Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        if root != actual_root:
            return ["REPOSITORY_ROOT_MISMATCH"]
        issues = []
        head = _git(root, "rev-parse", "HEAD").decode().strip()
        if head != commit_oid:
            issues.append("INTEGRATION_NOT_CURRENT_HEAD")
        # Include ignored artifacts: they also invalidate clean Git-only proof.
        if _git(root, "status", "--porcelain", "--untracked-files=all", "--ignored"):
            issues.append("WORKSPACE_DIRTY")
        tree = _git(root, "rev-parse", f"{commit_oid}^{{tree}}").decode().strip()
        if tree != contract.binding.output_tree_oid:
            issues.append("INTEGRATION_TREE_MISMATCH")
        source = contract.binding.source_revision
        _git(root, "merge-base", "--is-ancestor", source, commit_oid)
        changed = tuple(p.decode("utf-8", errors="surrogateescape") for p in
                        _git(root, "diff", "--no-ext-diff", "--no-renames", "--name-only", "-z",
                             source, commit_oid, "--").split(b"\0") if p)
        if set(changed) != set(execution.changed_paths):
            issues.append("INTEGRATION_DIFF_MISMATCH")
        if set(changed) - set(contract.allowed_paths):
            issues.append("INTEGRATION_SCOPE_VIOLATION")
        if not changed and not contract.allow_no_effect:
            issues.append("MIGRATION_NO_EFFECT")
        return issues
    except (OSError, subprocess.TimeoutExpired, _GitProofError):
        return ["GIT_PROOF_UNAVAILABLE"]


def evaluate_completion(
    contract: CompletionContract,
    milestone: Milestone,
    execution: ExecutionEvidence,
    *,
    validations: tuple[ValidationEvidence, ...] = (),
    repository_root: Path | None = None,
    commit_oid: str | None = None,
    artifacts: tuple[ArtifactEvidence, ...] = (),
    platforms: tuple[PlatformEvidence, ...] = (),
) -> GateResult:
    """Evaluate one milestone, including its prerequisites, without writes.

    A PASS applies only to this milestone and the supplied trusted binding.
    Input identity must be independently captured by the caller. No freshness
    claim is made about the mutable worktree for EXECUTED or VALIDATED.
    """
    if not isinstance(milestone, Milestone):
        raise ValueError("milestone must be a Milestone")
    issues = []
    if execution.binding != contract.binding:
        issues.append("EXECUTION_BINDING_MISMATCH")
    if execution.outcome != Outcome.SUCCESS:
        issues.append(f"EXECUTION_{execution.outcome.value}")
    if not execution.scope_passed:
        issues.append("SCOPE_NOT_PASSED")
    if set(execution.changed_paths) - set(contract.allowed_paths):
        issues.append("EXECUTION_SCOPE_VIOLATION")
    if not execution.changed_paths and not contract.allow_no_effect:
        issues.append("MIGRATION_NO_EFFECT")
    if milestone != Milestone.EXECUTED:
        for check in contract.required_checks:
            matches = [item for item in validations if item.check_id == check]
            if not matches:
                issues.append(f"VALIDATION_MISSING:{check}")
            elif len(matches) != 1:
                issues.append(f"VALIDATION_AMBIGUOUS:{check}")
            elif matches[0].binding != contract.binding:
                issues.append(f"VALIDATION_BINDING_MISMATCH:{check}")
            elif not matches[0].passed:
                issues.append(f"VALIDATION_FAILED:{check}")
    if milestone in (Milestone.INTEGRATED, Milestone.PLATFORM_ACCEPTED):
        if not execution.review_approved:
            issues.append("REVIEW_NOT_APPROVED")
        issues.extend(_integration_issues(contract, execution, repository_root, commit_oid))
    if milestone == Milestone.PLATFORM_ACCEPTED:
        if not contract.required_platforms:
            issues.append("PLATFORM_REQUIREMENTS_MISSING")
        for platform in contract.required_platforms:
            builds = [item for item in artifacts if item.platform == platform]
            receipts = [item for item in platforms if item.platform == platform]
            if len(builds) != 1:
                issues.append(f"ARTIFACT_MISSING_OR_AMBIGUOUS:{platform}")
            elif builds[0].binding != contract.binding:
                issues.append(f"ARTIFACT_BINDING_MISMATCH:{platform}")
            if len(receipts) != 1:
                issues.append(f"PLATFORM_MISSING_OR_AMBIGUOUS:{platform}")
            elif receipts[0].binding != contract.binding:
                issues.append(f"PLATFORM_BINDING_MISMATCH:{platform}")
            elif not receipts[0].passed:
                issues.append(f"PLATFORM_FAILED:{platform}")
            if len(builds) == len(receipts) == 1 and builds[0].sha256 != receipts[0].artifact_sha256:
                issues.append(f"PLATFORM_ARTIFACT_MISMATCH:{platform}")
    return GateResult(milestone, tuple(dict.fromkeys(issues)))
