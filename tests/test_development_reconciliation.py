import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent_hub.graphs.development import _complete, _apply_packaging_guard, _task_validation, apply_human_decision, reconcile_program


@contextmanager
def _canonical_repo_fixture():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "apps" / "flutter_forge").mkdir(parents=True)
        (root / "apps" / "flutter_forge" / "pubspec.yaml").write_text("name: flutter_forge_app\n")
        controller_dir = root / "apps" / "flutter_forge" / "lib" / "modules" / "ui" / "gcode_visualizer" / "state"
        controller_dir.mkdir(parents=True)
        (controller_dir / "gcode_player_controller.dart").write_text(
            "class GcodePlayerController {\n  void pickFilePathAndLoad() {}\n  AnimationController animation;\n}\n"
        )
        yield root


class DevelopmentReconciliationTest(unittest.TestCase):
    @patch("agent_hub.graphs.development._git")
    def test_primary_dirty_checkpoint_recovers_git_proven_router_task(self, git):
        git.side_effect = lambda _root, *args: (
            "130c602\x00refactor: inline app router facade [app-router-private-facade]"
            if args[:2] == ("log", "--format=%H%x00%s") else "130c602"
        )
        old = {"repository": "flutter_forge", "base_revision": "930bd47", "tasks": [{"task_id": "app-router-private-facade", "status": "BLOCKED"}], "completed_tasks": [], "blocked_tasks": [{"status": "PRIMARY_DIRTY", "changed_files": ["lib/app/app.dart"]}], "architecture_issues": []}
        with patch("agent_hub.graphs.development._new_program_for_reconciliation") as rebuilt:
            rebuilt.return_value = {"repository": "flutter_forge", "tasks": [{"task_id": "app-router-private-facade", "status": "DONE", "commit_hash": "130c602"}], "completed_tasks": ["app-router-private-facade"], "blocked_tasks": [], "architecture_issues": []}
            recovered = reconcile_program(old, Path("/integration"))
        self.assertEqual(recovered["tasks"][0]["status"], "DONE")
        self.assertEqual(recovered["blocked_tasks"], [])

    def test_incomplete_inventory_is_not_complete_when_ready_is_empty(self):
        self.assertFalse(_complete({"development_units": [{"inventory_completed": False}], "architecture_issues": [], "tasks": [], "final_rescan_completed": True}))

    def test_unnormalized_issue_is_not_complete(self):
        self.assertFalse(_complete({"development_units": [{"inventory_completed": True}], "architecture_issues": [{"status": "unknown"}], "tasks": [], "final_rescan_completed": True}))

    def test_recovery_handles_the_removed_router_source_file(self):
        with _canonical_repo_fixture() as root, patch("agent_hub.graphs.development._git", return_value="130c602"):
            from agent_hub.graphs.development import _new_program_for_reconciliation
            program = _new_program_for_reconciliation(root, "flutter_forge", ["app-router-private-facade"])
        self.assertEqual(program["tasks"][0]["status"], "DONE")

    def test_blocked_decision_prevents_completion(self):
        self.assertFalse(_complete({"development_units": [{"inventory_completed": True}], "architecture_issues": [], "tasks": [], "blocked_tasks": [{"task_id": "ownership"}], "final_rescan_completed": True}))

    def test_gcode_decision_creates_evidence_backed_task(self):
        with _canonical_repo_fixture() as root:
            program = {"repository": "flutter_forge", "tasks": [], "blocked_tasks": [{"task_id": "gcode-controller-ownership"}], "architecture_issues": [{"issue_id": "gcode-controller-ownership", "status": "BLOCKED_DECISION"}]}
            updated, status = apply_human_decision(program, {"decision_id": "gcode-controller-ownership", "choice": "controller-as-orchestrator"}, root, "thread")
        self.assertEqual(status, "DECISION_ACCEPTED")
        self.assertEqual(updated["tasks"][0]["task_id"], "gcode-controller-file-picking-capability")
        self.assertFalse(updated["blocked_tasks"])


class DevelopmentTaskContractTest(unittest.TestCase):
    def test_app_level_task_emits_flutter_build(self):
        self.assertEqual(
            _task_validation(["apps/flutter_forge/lib/app/app.dart"]),
            ["flutter_analyze", "flutter_build"],
        )

    def test_module_level_task_emits_flutter_build(self):
        self.assertEqual(
            _task_validation(["apps/flutter_forge/lib/modules/platform/usb_detector/module_entry.dart"]),
            ["flutter_analyze", "flutter_build"],
        )

    def test_package_only_task_omits_flutter_build(self):
        self.assertEqual(
            _task_validation(["packages/gcode_core/lib/gcode_core.dart"]),
            ["flutter_analyze"],
        )

    def test_protected_path_without_flag_is_stripped_and_blocked(self):
        task = _apply_packaging_guard({"candidate_paths": ["lib/x.dart", "tool/quality_gate.sh", ".github/workflows/ci.yml"]})
        self.assertEqual(task["candidate_paths"], ["lib/x.dart"])
        self.assertEqual(task["blocked"]["reason"], "protected_packaging_flow")
        self.assertEqual(task["blocked"]["protected"], [".github/workflows/ci.yml", "tool/quality_gate.sh"])
        self.assertNotIn("manual_review", task)

    def test_protected_path_with_flag_forces_manual_review(self):
        task = _apply_packaging_guard({"candidate_paths": ["tool/quality_gate.sh"], "packaging_change": True})
        self.assertEqual(task["candidate_paths"], ["tool/quality_gate.sh"])
        self.assertTrue(task["manual_review"])
        self.assertNotIn("blocked", task)

    def test_unprotected_path_untouched(self):
        task = _apply_packaging_guard({"candidate_paths": ["lib/x.dart"]})
        self.assertEqual(task["candidate_paths"], ["lib/x.dart"])
        self.assertNotIn("blocked", task)
