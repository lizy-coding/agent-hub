import json
import tempfile
import unittest
from pathlib import Path
from agent_hub.planning.authority_planner import AuthorityPlanner
from agent_hub.schemas.models import MigrationPlan

class AuthorityPlannerTest(unittest.TestCase):
 def test_authority_file_is_persisted_and_declares_canonical_targets(self):
  data=json.loads((Path(__file__).parents[1]/'architecture/flutter-study-plugin-authority.json').read_text())
  self.assertEqual(data['provenance'],'HUMAN_REVIEW_P6_3')
  self.assertEqual(len(data['canonical_targets']),2)
 def test_identical_comparison_is_not_a_source_move(self):
  # P6.3 task generation is restricted to dependency adoption plus host validation.
  plan=json.loads((Path(__file__).parents[1]/'plans/flutter-study-plugin-decomposition-p6-3.json').read_text())
  self.assertTrue(all(x['action_type'] in ('UPDATE_DEPENDENCY','VALIDATE_INTEGRATION') for x in plan['migration_tasks']))
  self.assertTrue(all(x['migration_delta']['status']=='ADOPTION_ONLY' for x in plan['migration_tasks']))
