import json
import unittest
from pathlib import Path

class ArchitectureGoldensTest(unittest.TestCase):
 def test_pending_candidates_have_independent_evidence(self):
  cases=json.loads((Path(__file__).parents[1]/'benchmarks/architecture_goldens/candidates.json').read_text())
  self.assertEqual(len(cases),8)
  for case in cases:
   self.assertEqual(case['review']['state'],'pending_review')
   self.assertIsNone(case['review']['accepted_ownership'])
   self.assertTrue(any(case['evidence'][key] for key in ('files','symbols','callsites','manifests','contracts')))
 def test_name_only_and_auto_approval_are_absent(self):
  text=(Path(__file__).parents[1]/'benchmarks/architecture_goldens/candidates.json').read_text()
  self.assertNotIn('reviewed',text)
  self.assertNotIn('CapabilityAnalysis',text)
 def test_human_review_decisions_are_complete_and_do_not_promote_golden_007(self):
  decisions=json.loads((Path(__file__).parents[1]/'benchmarks/architecture_goldens/review-decisions.json').read_text())
  self.assertEqual(len(decisions),8)
  self.assertEqual(next(x for x in decisions if x['id']=='GOLDEN_007')['accepted_extraction'],'UNKNOWN')
if __name__=='__main__':unittest.main()
