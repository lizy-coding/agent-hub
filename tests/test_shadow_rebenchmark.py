import unittest
from pathlib import Path
from agent_hub.benchmark.runner import ShadowBenchmarkRunner
from agent_hub.workspace.config import WorkspaceConfig
class ShadowRebenchmarkTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.runner=ShadowBenchmarkRunner(WorkspaceConfig.from_file(Path(__file__).parents[1]/'workspace/config.json'))
 def test_review_truth_is_separate_and_unknown_is_not_promoted(self):
  reviewed=self.runner.load_reviewed_goldens(); self.assertEqual(len(reviewed),8)
  metric=self.runner.run_shadow_suite()['architecture']; row=next(x for x in metric['goldens'] if x['id']=='GOLDEN_007')
  self.assertEqual(row['accepted_extraction'],'UNKNOWN'); self.assertFalse(row['unsupported_promotion'])
 def test_architecture_denominators_and_score_are_real(self):
  a=self.runner.run_shadow_suite()['architecture']; self.assertEqual(len(a['goldens']),8); self.assertIsNotNone(a['ownership_accuracy']); self.assertIsNotNone(a['extraction_accuracy'])
if __name__=='__main__':unittest.main()
