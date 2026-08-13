import unittest
from unittest.mock import patch
from agent_hub.gateway.decomposition import plan, render, status
class DecompositionTest(unittest.TestCase):
 def test_dashboard_shows_plan_only(self):
  text=render({"values":{"decomposition_program":{"program_id":"p","execution_mode":"PLAN_ONLY","capabilities":[{"classification":"MERGE"}],"migration_tasks":[{"status":"READY"}],"package_candidates":[],"target_dependency_graph":{"nodes":[],"edges":[],"cycles":[]}}}})
  self.assertIn("PLAN_ONLY",text)
 @patch("agent_hub.gateway.decomposition._call")
 def test_plan_creates_thread_when_not_supplied(self, call):
  call.side_effect=[{"thread_id":"t"},[{"assistant_id":"a","graph_id":"decomposition"}],{"run_id":"r"}]
  output=[]
  self.assertEqual(plan("http://server",None,output.append),0)
  self.assertIn("Thread ID: t",output[0]); self.assertIn("Run ID: r",output[0])
  self.assertEqual(call.call_args_list[2].args[1],"http://server/threads/t/runs")
 @patch("agent_hub.gateway.decomposition._call")
 def test_status_does_not_select_refactor_thread(self, call):
  call.return_value=[{"thread_id":"ref","metadata":{"program_id":"flutter-study-refactor-program"}}]
  output=[]
  self.assertEqual(status("http://server",None,output.append),2)
  self.assertTrue(output[0].startswith("NO_DECOMPOSITION_PROGRAM"))
 @patch("agent_hub.gateway.decomposition._call")
 def test_explicit_refactor_thread_is_rejected(self, call):
  call.return_value={"thread_id":"ref","metadata":{"program_id":"flutter-study-refactor-program"}}
  output=[]
  self.assertEqual(status("http://server","ref",output.append),2)
  self.assertEqual(output[0],"WRONG_PROGRAM_TYPE")
