import unittest
from pathlib import Path
from agent_hub.planning.migration_planner import MigrationPlanner
from agent_hub.schemas.models import CapabilityAnalysis, CapabilityNode, CouplingProfile, ExtractionAssessment
from agent_hub.workspace.config import WorkspaceConfig

class MigrationPlannerTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.planner=MigrationPlanner(WorkspaceConfig.from_file(Path(__file__).parents[1]/'workspace/config.json'))
 def _analysis(self, decision, target=None, ownership='shared_core'):
  node=CapabilityNode(capability_id='capability:synthetic',label='x',target_repo='flutter_study',development_units=['flutter_study:.'],files=['flutter_study/lib/x.dart'],ownership=ownership,coupling=CouplingProfile(),evidence_refs=['flutter_study/lib/x.dart:1'])
  assessment=ExtractionAssessment(capability_id=node.capability_id,decision=decision,target_repo='flutter_study' if target else None,target_unit=target,evidence_refs=node.evidence_refs)
  return CapabilityAnalysis(requirement='synthetic',target_repository='flutter_study',context_ref={},capabilities=[node],extraction_assessments=[assessment])
 def test_keep_and_adapter_do_not_move(self):
  self.assertEqual(self.planner.build_plan('x','flutter_study',self._analysis('KEEP_IN_APPLICATION')).migration_tasks,[])
  plan=self.planner.build_plan('x','flutter_study',self._analysis('ADAPTER_ONLY',ownership='adapter'))
  self.assertEqual(plan.migration_tasks,[])
 def test_unknown_and_already_owned_are_not_executable(self):
  blocked=self.planner.build_plan('x','flutter_study',self._analysis('UNKNOWN'))
  self.assertEqual(len(blocked.blocked_items),1)
  plan=self.planner.build_plan('x','flutter_study',self._analysis('MOVE_TO_EXISTING_UNIT','flutter_study:packages/gcode_core'))
  self.assertEqual(plan.migration_tasks,[])
  self.assertEqual(self.planner.validate_plan(plan),[])
 def test_validator_rejects_synthetic_self_move(self):
  from agent_hub.schemas.models import MigrationDelta, MigrationTask, MigrationPlan
  delta=MigrationDelta(capability_id='x',current_owner_repo='flutter_study',current_owner_unit='flutter_study:.',current_paths=['/Users/forest/code/langGraph/flutter_study/lib/x.dart'],intended_owner_repo='flutter_study',intended_owner_unit='flutter_study:.',destination_paths=['/Users/forest/code/langGraph/flutter_study/lib/x.dart'],status='REAL_MIGRATION')
  task=MigrationTask(task_id='self',title='x',action_type='MOVE_CORE_LOGIC',source_repo='flutter_study',target_repo='flutter_study',allowed_paths=delta.current_paths,rollback_boundary='x',risk='HIGH',migration_delta=delta)
  plan=MigrationPlan(plan_id='x',requirement='x',target_repository='flutter_study',source_analysis_ref={},migration_tasks=[task],dependency_dag={'self':[]},status='READY_FOR_HUMAN_PLAN_REVIEW')
  self.assertIn('self move: self',self.planner.validate_plan(plan))
