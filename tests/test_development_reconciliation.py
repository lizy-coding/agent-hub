import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub.graphs.development import _complete, apply_human_decision, reconcile_program


class DevelopmentReconciliationTest(unittest.TestCase):
    @patch("agent_hub.graphs.development._git")
    def test_primary_dirty_checkpoint_recovers_git_proven_router_task(self, git):
        git.side_effect = lambda _root, *args: (
            "130c602\x00refactor: inline app router facade [app-router-private-facade]"
            if args[:2] == ("log", "--format=%H%x00%s") else "130c602"
        )
        old = {"repository": "flutter_study", "base_revision": "930bd47", "tasks": [{"task_id": "app-router-private-facade", "status": "BLOCKED"}], "completed_tasks": [], "blocked_tasks": [{"status": "PRIMARY_DIRTY", "changed_files": ["lib/app/app.dart"]}], "architecture_issues": []}
        with patch("agent_hub.graphs.development._new_program_for_reconciliation") as rebuilt:
            rebuilt.return_value = {"repository": "flutter_study", "tasks": [{"task_id": "app-router-private-facade", "status": "DONE", "commit_hash": "130c602"}], "completed_tasks": ["app-router-private-facade"], "blocked_tasks": [], "architecture_issues": []}
            recovered = reconcile_program(old, Path("/integration"))
        self.assertEqual(recovered["tasks"][0]["status"], "DONE")
        self.assertEqual(recovered["blocked_tasks"], [])

    def test_incomplete_inventory_is_not_complete_when_ready_is_empty(self):
        self.assertFalse(_complete({"development_units": [{"inventory_completed": False}], "architecture_issues": [], "tasks": [], "final_rescan_completed": True}))

    def test_unnormalized_issue_is_not_complete(self):
        self.assertFalse(_complete({"development_units": [{"inventory_completed": True}], "architecture_issues": [{"status": "unknown"}], "tasks": [], "final_rescan_completed": True}))

    def test_recovery_handles_the_removed_router_source_file(self):
        with patch("agent_hub.graphs.development._git", return_value="130c602"):
            from agent_hub.graphs.development import _new_program_for_reconciliation
            root = Path(__file__).parents[1] / ".integration" / "flutter_study"
            program = _new_program_for_reconciliation(root, "flutter_study", ["app-router-private-facade"])
        self.assertEqual(program["tasks"][0]["status"], "DONE")

    def test_blocked_decision_prevents_completion(self):
        self.assertFalse(_complete({"development_units": [{"inventory_completed": True}], "architecture_issues": [], "tasks": [], "blocked_tasks": [{"task_id": "ownership"}], "final_rescan_completed": True}))

    def test_gcode_decision_creates_evidence_backed_task(self):
        root = Path(__file__).parents[1] / ".integration" / "flutter_study"
        program = {"repository": "flutter_study", "tasks": [], "blocked_tasks": [{"task_id": "gcode-controller-ownership"}], "architecture_issues": [{"issue_id": "gcode-controller-ownership", "status": "BLOCKED_DECISION"}]}
        updated, status = apply_human_decision(program, {"decision_id": "gcode-controller-ownership", "choice": "controller-as-orchestrator"}, root, "thread")
        self.assertEqual(status, "DECISION_ACCEPTED")
        self.assertEqual(updated["tasks"][0]["task_id"], "gcode-controller-file-picking-capability")
        self.assertFalse(updated["blocked_tasks"])
