import os
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub.gateway.refactor_run import refactor_run


class RefactorRunTest(unittest.TestCase):
    @patch("agent_hub.gateway.refactor_run._ready", return_value=True)
    @patch("agent_hub.gateway.refactor_run.fetch_state")
    @patch("agent_hub.gateway.refactor_run._call")
    def test_attaches_without_creating_duplicate_run(self, call, state, _):
        call.return_value = {"ok": True}
        state.side_effect = [
            {"next": ["execute_code"], "tasks": [{}], "values": {"program": {"tasks": []}}},
            {"next": [], "tasks": [], "values": {"program": {"tasks": []}}},
        ]
        output = []
        self.assertEqual(refactor_run("http://server", "thread", Path.cwd(), output.append), 0)
        self.assertEqual(call.call_count, 1)

    @patch("agent_hub.gateway.refactor_run._ready", return_value=True)
    @patch("agent_hub.gateway.refactor_run.fetch_state")
    @patch("agent_hub.gateway.refactor_run._call")
    def test_accepts_string_root_and_sets_integration_worktree(self, call, state, _):
        call.return_value = {"ok": True}
        state.side_effect = [
            {"next": ["execute_code"], "tasks": [{}], "values": {"program": {"tasks": []}}},
            {"next": [], "tasks": [], "values": {"program": {"tasks": []}}},
        ]
        output = []
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(refactor_run("http://server", "thread", "/tmp/agent-hub", output.append), 0)
            self.assertEqual(
                os.environ["AGENT_HUB_INTEGRATION_WORKTREE"],
                "/tmp/agent-hub/.integration/flutter_forge",
            )

    @patch("agent_hub.gateway.refactor_run._ready", return_value=False)
    @patch("agent_hub.gateway.refactor_run._start_worker")
    @patch("agent_hub.gateway.refactor_run._call")
    def test_reports_worker_unavailable(self, call, _, __):
        call.return_value = {"ok": True}
        output = []
        self.assertEqual(refactor_run("http://server", "thread", Path.cwd(), output.append), 3)
        self.assertIn("WORKER_UNAVAILABLE", output)

    def test_failed_checkpoint_is_not_treated_as_an_active_run(self):
        from agent_hub.gateway.refactor_run import _active
        self.assertFalse(_active({"next": ["reconcile"], "tasks": [{"error": "FileNotFoundError"}]}))
