"""Real Git fixtures for isolated completion gates; no business checkout reads."""
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_hub.execution.completion_evidence import (
    ArtifactEvidence, CompletionContract, EvidenceBinding, ExecutionEvidence,
    Milestone, Outcome, PlatformEvidence, ValidationEvidence, evaluate_completion,
)


class CompletionEvidenceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="completion-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.file = self.root / "model.txt"
        self.file.write_text("old\n")
        self.git("add", "model.txt")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.file.write_text("new\n")
        self.git("add", "model.txt")
        self.git("commit", "-qm", "result")
        self.commit = self.git("rev-parse", "HEAD")
        self.binding = EvidenceBinding("project", "repo", "task", "a" * 64,
                                       self.base, self.git("rev-parse", "HEAD^{tree}"))
        self.contract = CompletionContract(self.binding, ("model.txt",), ("unit",), ("android",))
        self.execution = ExecutionEvidence(self.binding, Outcome.SUCCESS, ("model.txt",), True, True)
        self.validation = ValidationEvidence(self.binding, "unit", True, "fixture:test-log", "python-host")
        self.artifact = ArtifactEvidence(self.binding, "android", "b" * 64)
        self.platform = PlatformEvidence(self.binding, "android", "b" * 64, True,
                                         "physical-device:fixture", "fixture:interaction", "fixture:readback")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def evaluate(self, milestone=Milestone.INTEGRATED, **changes):
        arguments = dict(contract=self.contract, milestone=milestone, execution=self.execution,
                         validations=(self.validation,), repository_root=self.root,
                         commit_oid=self.commit, artifacts=(self.artifact,), platforms=(self.platform,))
        arguments.update(changes)
        return evaluate_completion(**arguments)

    def assert_issue(self, issue, **changes):
        result = self.evaluate(**changes)
        self.assertFalse(result.passed)
        self.assertIn(issue, result.issues)

    def test_each_milestone_has_independent_success(self):
        for milestone in Milestone:
            with self.subTest(milestone=milestone):
                self.assertTrue(self.evaluate(milestone).passed)

    def test_execution_does_not_imply_validation(self):
        self.assertTrue(self.evaluate(Milestone.EXECUTED, validations=()).passed)
        self.assert_issue("VALIDATION_MISSING:unit", milestone=Milestone.VALIDATED, validations=())

    def test_validation_does_not_imply_integration(self):
        self.assertTrue(self.evaluate(Milestone.VALIDATED, commit_oid=None).passed)
        self.assert_issue("INTEGRATION_PROOF_MISSING", commit_oid=None)

    def test_integration_does_not_imply_platform_acceptance(self):
        self.assertTrue(self.evaluate(platforms=(), artifacts=()).passed)
        self.assert_issue("PLATFORM_MISSING_OR_AMBIGUOUS:android",
                          milestone=Milestone.PLATFORM_ACCEPTED, platforms=())

    def test_every_identity_field_is_bound(self):
        changes = dict(project_id="other", repository_id="other", task_id="other",
                       contract_sha256="c" * 64, source_revision="c" * 40, output_tree_oid="c" * 40)
        for key, value in changes.items():
            with self.subTest(key=key):
                stale = replace(self.binding, **{key: value})
                self.assert_issue("EXECUTION_BINDING_MISMATCH", execution=replace(self.execution, binding=stale))
                self.assert_issue("VALIDATION_BINDING_MISMATCH:unit", validations=(replace(self.validation, binding=stale),))

    def test_interrupted_and_failed_results_cannot_complete(self):
        for outcome in (Outcome.INTERRUPTED, Outcome.FAILED):
            with self.subTest(outcome=outcome):
                self.assert_issue(f"EXECUTION_{outcome.value}", execution=replace(self.execution, outcome=outcome))

    def test_scope_and_review_are_required(self):
        self.assert_issue("SCOPE_NOT_PASSED", execution=replace(self.execution, scope_passed=False))
        self.assert_issue("REVIEW_NOT_APPROVED", execution=replace(self.execution, review_approved=False))
        self.assert_issue("EXECUTION_SCOPE_VIOLATION", execution=replace(self.execution, changed_paths=("outside.txt",)))

    def test_failed_or_duplicate_validation_is_rejected(self):
        self.assert_issue("VALIDATION_FAILED:unit", validations=(replace(self.validation, passed=False),))
        self.assert_issue("VALIDATION_AMBIGUOUS:unit", validations=(self.validation, self.validation))

    def test_git_object_and_tree_are_read_back(self):
        self.assert_issue("GIT_PROOF_UNAVAILABLE", commit_oid="f" * 40)
        binding = replace(self.binding, output_tree_oid="d" * 40)
        self.assert_issue("INTEGRATION_TREE_MISMATCH", contract=replace(self.contract, binding=binding),
                          execution=replace(self.execution, binding=binding),
                          validations=(replace(self.validation, binding=binding),))

    def test_uncommitted_staged_untracked_and_ignored_changes_are_not_current_proof(self):
        self.file.write_text("dirty\n")
        self.assert_issue("WORKSPACE_DIRTY")
        self.git("add", "model.txt")
        self.assert_issue("WORKSPACE_DIRTY")
        self.git("reset", "--hard", self.commit)
        untracked = self.root / "untracked.txt"
        untracked.write_text("new")
        self.assert_issue("WORKSPACE_DIRTY")
        untracked.unlink()
        (self.root / ".git/info/exclude").write_text("ignored.txt\n")
        (self.root / "ignored.txt").write_text("artifact")
        self.assert_issue("WORKSPACE_DIRTY")

    def test_historical_commit_cannot_claim_current_acceptance(self):
        self.file.write_text("later\n")
        self.git("add", "model.txt")
        self.git("commit", "-qm", "later")
        self.assert_issue("INTEGRATION_NOT_CURRENT_HEAD")

    def test_divergent_commit_is_not_integration(self):
        self.git("checkout", "--orphan", "unrelated")
        self.git("commit", "-qm", "unrelated root")
        unrelated = self.git("rev-parse", "HEAD")
        self.assert_issue("GIT_PROOF_UNAVAILABLE", commit_oid=unrelated)

    def test_actual_diff_must_match_receipt_and_frozen_scope(self):
        self.assert_issue("INTEGRATION_DIFF_MISMATCH", execution=replace(self.execution, changed_paths=()))
        self.assert_issue("INTEGRATION_SCOPE_VIOLATION", contract=replace(self.contract, allowed_paths=("other.txt",)))

    def test_empty_diff_requires_explicit_no_effect_contract(self):
        binding = replace(self.binding, source_revision=self.commit)
        contract = replace(self.contract, binding=binding)
        execution = replace(self.execution, binding=binding, changed_paths=())
        arguments = dict(contract=contract, execution=execution,
                         validations=(replace(self.validation, binding=binding),))
        self.assert_issue("MIGRATION_NO_EFFECT", **arguments)
        arguments["contract"] = replace(contract, allow_no_effect=True)
        self.assertTrue(self.evaluate(**arguments).passed)

    def test_renamed_and_deleted_source_paths_remain_in_git_diff(self):
        self.git("mv", "model.txt", "renamed.txt")
        self.git("commit", "-qm", "rename")
        binding = replace(self.binding, source_revision=self.commit, output_tree_oid=self.git("rev-parse", "HEAD^{tree}"))
        contract = replace(self.contract, binding=binding, allowed_paths=("model.txt", "renamed.txt"))
        execution = replace(self.execution, binding=binding, changed_paths=("model.txt", "renamed.txt"))
        self.assertTrue(self.evaluate(contract=contract, execution=execution,
                                     validations=(replace(self.validation, binding=binding),),
                                     commit_oid=self.git("rev-parse", "HEAD")).passed)

    def test_subdirectory_is_not_an_authoritative_repository_root(self):
        child = self.root / "child"
        child.mkdir()
        self.assert_issue("REPOSITORY_ROOT_MISMATCH", repository_root=child)

    def test_platform_requires_bound_artifact_and_operation_readback(self):
        self.assert_issue("PLATFORM_ARTIFACT_MISMATCH:android", milestone=Milestone.PLATFORM_ACCEPTED,
                          platforms=(replace(self.platform, artifact_sha256="c" * 64),))
        self.assert_issue("PLATFORM_BINDING_MISMATCH:android", milestone=Milestone.PLATFORM_ACCEPTED,
                          platforms=(replace(self.platform, binding=replace(self.binding, source_revision="c" * 40)),))
        self.assert_issue("ARTIFACT_BINDING_MISMATCH:android", milestone=Milestone.PLATFORM_ACCEPTED,
                          artifacts=(replace(self.artifact, binding=replace(self.binding, task_id="other")),))
        self.assert_issue("PLATFORM_FAILED:android", milestone=Milestone.PLATFORM_ACCEPTED,
                          platforms=(replace(self.platform, passed=False),))
        with self.assertRaises(ValueError):
            replace(self.platform, readback_ref="")

    def test_empty_platform_requirements_do_not_claim_acceptance(self):
        self.assert_issue("PLATFORM_REQUIREMENTS_MISSING", milestone=Milestone.PLATFORM_ACCEPTED,
                          contract=replace(self.contract, required_platforms=()))

    def test_invalid_contracts_fail_closed(self):
        for paths in (("../other",), ("/absolute",), ("lib/",), ("a/./b",), ("a", "a"), ["a"]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                replace(self.contract, allowed_paths=paths)
        with self.assertRaises(ValueError):
            replace(self.binding, source_revision="HEAD")
        with self.assertRaises(ValueError):
            replace(self.validation, passed="PASS")
        with self.assertRaises(ValueError):
            self.evaluate(milestone="DONE")

    def test_empty_validation_requirements_and_untyped_bindings_are_rejected(self):
        with self.assertRaises(ValueError):
            replace(self.contract, required_checks=())
        for record in (self.contract, self.execution, self.validation, self.artifact, self.platform):
            with self.subTest(record=type(record).__name__), self.assertRaises(ValueError):
                replace(record, binding={"task_id": "task"})

    def test_duplicate_or_missing_artifacts_and_platforms_are_rejected(self):
        self.assert_issue("ARTIFACT_MISSING_OR_AMBIGUOUS:android", milestone=Milestone.PLATFORM_ACCEPTED,
                          artifacts=())
        self.assert_issue("ARTIFACT_MISSING_OR_AMBIGUOUS:android", milestone=Milestone.PLATFORM_ACCEPTED,
                          artifacts=(self.artifact, self.artifact))
        self.assert_issue("PLATFORM_MISSING_OR_AMBIGUOUS:android", milestone=Milestone.PLATFORM_ACCEPTED,
                          platforms=(self.platform, self.platform))

    def test_missing_git_and_timeout_preserve_unknown(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("git", 10)):
            with self.subTest(error=error), patch("agent_hub.execution.completion_evidence.subprocess.run", side_effect=error):
                self.assert_issue("GIT_PROOF_UNAVAILABLE")

    def test_evaluation_has_no_python_discovery_and_no_worktree_or_index_mutation(self):
        index = (self.root / ".git/index").read_bytes()
        content = self.file.read_bytes()
        with ExitStack() as stack:
            for target in ("os.walk", "pathlib.Path.glob", "pathlib.Path.rglob"):
                stack.enter_context(patch(target, side_effect=AssertionError("discovery forbidden")))
            self.assertTrue(self.evaluate(Milestone.PLATFORM_ACCEPTED).passed)
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        self.assertEqual(self.file.read_bytes(), content)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.commit)


if __name__ == "__main__":
    unittest.main()
