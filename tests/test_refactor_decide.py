import unittest
from unittest.mock import patch

from agent_hub.gateway.refactor_decide import refactor_decide


class RefactorDecideTest(unittest.TestCase):
    @patch("agent_hub.gateway.refactor_decide._call")
    def test_submits_a_structured_decision(self, call):
        call.side_effect = [[{"assistant_id": "a", "graph_id": "development"}], {"run_id": "r"}]
        output = []
        self.assertEqual(refactor_decide("http://server", "thread", "gcode-controller-ownership", "controller-as-orchestrator", "because", output.append), 0)
        self.assertIn("DECISION_SUBMITTED: r", output)
        self.assertEqual(call.call_args_list[1].args[2]["input"]["decision"]["choice"], "controller-as-orchestrator")
