import unittest
from pathlib import Path
from agent_hub.benchmark.runner import ShadowBenchmarkRunner
from agent_hub.workspace.config import WorkspaceConfig
class ShadowBenchmarkTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.runner=ShadowBenchmarkRunner(WorkspaceConfig.from_file(Path(__file__).parents[1]/'workspace/config.json'))
 def test_scenarios_have_independent_expectations(self):
  cases=self.runner.load_scenarios(); self.assertEqual(len(cases),6)
  self.assertTrue(all('expected' in x and 'review_state' in x for x in cases))
  self.assertTrue(all(x['expected']['ownership']['scoring']=='unscored' for x in cases))
 def test_repeatable_suite_and_metrics(self):
  first=self.runner.run_shadow_suite(); second=self.runner.run_shadow_suite()
  self.assertEqual(first['repository_precision'],second['repository_precision'])
  self.assertEqual(first['false_positive_rate'],0.0)
  self.assertEqual([x['id'] for x in first['cases']],[x['id'] for x in second['cases']])
if __name__=='__main__':unittest.main()
