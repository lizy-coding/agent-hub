import unittest

from agent_hub.gateway.refactor_dashboard import render, status


class DashboardTest(unittest.TestCase):
    def test_completed_program_can_remain_graph_active(self):
        text = render({"values": {"program": {"program_id": "p", "status": "COMPLETED", "development_units": [{}], "tasks": [{"task_id": "done", "status": "DONE"}]}, "worker_result": {"status": "SUCCESS", "scope_guard": "PASS", "validation": {"analyze": {"status": "PASS"}}, "review": "APPROVED"}}, "next": ["execute_code"], "tasks": [{}], "metadata": {"thread_id": "t", "run_id": "r", "step": 3}})
        self.assertIn("PROGRAM COMPLETED / GRAPH ACTIVE", text)
        self.assertIn("Progress: 100%", text)

    def test_unavailable_server_is_reported_without_traceback(self):
        output = []
        self.assertEqual(status("http://127.0.0.1:1", "missing", output.append), 2)
        self.assertTrue(output[0].startswith("DISCONNECTED:"))

    def test_integration_workflow_does_not_render_retired_primary_apply(self):
        text = render({"values": {"program": {"program_id": "p", "integration_branch": "refactor/langgraph-global", "base_revision": "abc", "tasks": [{"task_id": "router", "status": "DONE", "commit_hash": "abc"}]}, "integration_apply": {"status": "COMMITTED"}}})
        self.assertIn("Integration: refactor/langgraph-global @ abc", text)
        self.assertIn("Integration commit: COMMITTED", text)
        self.assertNotIn("PRIMARY apply", text)

    def test_inventory_and_git_proven_commit_are_projected(self):
        text = render({"values": {"program": {"program_id": "p", "development_units": [{"inventory_completed": True}, {"inventory_completed": True}], "tasks": [{"task_id": "router", "status": "DONE", "commit_hash": "130c602"}]}}})
        self.assertIn("Inventory: 2/2", text)
        self.assertIn("Commit Integration=DONE", text)
