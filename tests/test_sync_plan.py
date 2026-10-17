"""Shared-budget synchronization, failure protocol, retirement and idempotence."""
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_agent_context as fixtures
from agent_hub.projects.sync_plan import build_sync_plan, project_queue, queue_delta


class SyncPlanTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AgentContextTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        self.policy(['pubspec.yaml'], ['lib/parser.dart'])

    def policy(self, required, optional):
        p=json.loads(self.f.project_registry.read_text())
        p['projects']['fixture']['sync_profiles']={'maintenance':{'required_files':required,'candidate_paths':optional}}
        self.f.project_registry.write_text(json.dumps(p))

    def run_plan(self, **options):
        return build_sync_plan(['fixture'], registry_path=self.f.project_registry, **options)

    def test_shared_budget_and_manifest_priority_under_query(self):
        self.policy(['pubspec.yaml'], ['lib/parser.dart', 'NEW_AGENT.md'])
        with self.f.guarded() as stack:
            reads=self.f.track_reads(stack)
            plan=self.run_plan(max_files=3, requirement='Parser')
        p=plan['projects'][0]
        self.assertEqual(p['version'], '1.0.0+1')
        self.assertEqual(p['status'], 'PARTIAL')
        self.assertEqual(plan['exit_code'], 1)
        self.assertLessEqual(len(reads), 3)
        self.assertLessEqual(p['metrics']['inspected_files'], 3)
        self.assertEqual({x['path'] for x in p['project_inventory']['files']}, {x['path'] for x in p['selected_files']})
        self.assertEqual(plan['allowed_paths_by_repository'], {})

    def test_missing_manifest_or_root_guide_blocks_not_package_fallback(self):
        for missing in ['pubspec.yaml', 'AGENTS.md']:
            target=self.f.repo/missing
            raw=target.read_bytes();target.unlink()
            with self.f.guarded():plan=self.run_plan(max_files=4)
            self.assertEqual(plan['exit_code'], 2)
            self.assertEqual(plan['projects'][0]['status'], 'BLOCKED')
            target.write_bytes(raw)

    def test_required_closure_cannot_partially_analyze(self):
        (self.f.repo/'lib/AGENTS.md').write_text('scoped rule')
        self.policy(['pubspec.yaml','lib/parser.dart'], [])
        with self.f.guarded():plan=self.run_plan(max_files=3)
        p=plan['projects'][0]
        self.assertEqual(p['status'], 'BLOCKED')
        self.assertNotIn('lib/parser.dart', {x['path'] for x in p['selected_files']})
        self.assertIn('REQUIRED_INPUT_NOT_OBSERVED: lib/parser.dart', p['blockers'])

    def test_historical_deletion_requires_git_proof_and_never_downgrades_required(self):
        retired=self.f.repo/'lib/old.dart';retired.write_text('class Old {}')
        self.f.git('add','lib/old.dart');self.f.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','add old')
        self.f.git('rm','lib/old.dart');self.f.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','remove old')
        with self.f.guarded():plan=self.run_plan(max_files=8)
        p=plan['projects'][0]
        self.assertEqual([x['path'] for x in p['retired_candidates']], ['lib/old.dart'])
        self.assertNotIn('MISSING_OR_DELETED: lib/old.dart', p['gaps'])
        self.policy(['pubspec.yaml','lib/old.dart'], [])
        with self.f.guarded():plan=self.run_plan(max_files=8)
        self.assertEqual(plan['projects'][0]['status'], 'BLOCKED')
        self.assertEqual(plan['projects'][0]['retired_candidates'], [])

    def test_one_invalid_project_preserves_other_projects(self):
        payload=json.loads(self.f.project_registry.read_text())
        payload['projects']['bad']={'adapter':'generic','workspace_config':str(self.f.root/'missing-config.json')}
        self.f.project_registry.write_text(json.dumps(payload))
        with self.f.guarded():plan=build_sync_plan(registry_path=self.f.project_registry, output_path=self.f.output, max_files=8)
        self.assertEqual(plan['exit_code'], 2)
        self.assertEqual(plan['projects'][1]['status'], 'BLOCKED')
        self.assertIn(plan['projects'][0]['status'], ['SUCCESS','PARTIAL'])
        self.assertEqual(json.loads(self.f.output.read_text())['plan_id'], plan['plan_id'])

    def test_same_capture_is_stable_policy_changes_identity(self):
        with self.f.guarded():
            first=self.run_plan(max_files=8)
            second=self.run_plan(max_files=8, previous=first)
            third=self.run_plan(max_files=9)
        p1,p2,p3=[p['projects'][0] for p in [first,second,third]]
        self.assertEqual(p1['source_snapshot_id'], p2['source_snapshot_id'])
        self.assertEqual(p1['source_snapshot_id'], p3['source_snapshot_id'])
        self.assertNotEqual(p1['plan_id'], p3['plan_id'])
        self.assertEqual(p2['queue_delta']['changed'], [])
        self.assertEqual(p2['runtime_checkpoint']['status'], 'NOT_INSPECTED')

    def test_optional_checkpoint_is_only_read_and_wrong_identity_blocks(self):
        file=self.f.root/'checkpoint.json'
        state={'schema_version':2,'project_id':'fixture','decomposition_program':{'project_id':'fixture','program_id':'fixture-decomposition-program','status':'PLANNING_COMPLETE'}}
        file.write_text(json.dumps(state));before=file.read_bytes()
        with self.f.guarded(), patch('agent_hub.gateway.decomposition._call',side_effect=AssertionError('no state mutations')):
            plan=self.run_plan(max_files=8,checkpoint_paths={'fixture':file})
        self.assertEqual(file.read_bytes(),before)
        self.assertEqual(plan['projects'][0]['runtime_checkpoint']['status'],'OBSERVED_LOCAL_FILE')
        state['decomposition_program']['project_id']='other';file.write_text(json.dumps(state))
        with self.f.guarded():plan=self.run_plan(max_files=8,checkpoint_paths={'fixture':file})
        self.assertEqual(plan['projects'][0]['status'],'BLOCKED')

    def test_config_change_during_capture_blocks(self):
        from agent_hub.projects import sync_plan
        real=sync_plan._refresh_project
        def changing(*a,**kw):
            result=real(*a,**kw)
            self.f.project_registry.write_text(self.f.project_registry.read_text()+'\n')
            return result
        with self.f.guarded(),patch.object(sync_plan,'_refresh_project',side_effect=changing):plan=self.run_plan(max_files=8)
        self.assertIn('CONFIG_CHANGED_DURING_CAPTURE',plan['projects'][0]['blockers'])

    def test_cli_exit_protocol_and_artifact_output_guard(self):
        with self.f.guarded(), self.assertRaises(ValueError):self.run_plan(output_path=self.f.repo/'pubspec.yaml')
        self.policy(['pubspec.yaml','missing.dart'],[])
        env={**os.environ,'AGENT_HUB_PROJECT_REGISTRY':str(self.f.project_registry),'PYTHONDONTWRITEBYTECODE':'1'}
        hub=Path(__file__).resolve().parents[1]
        result=subprocess.run([str(hub/'.venv/bin/python'),str(hub/'agent'),'sync-plan','--project','fixture','--output',str(self.f.output)],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        self.assertIn('BLOCKED',result.stdout)

    def test_queue_delta_preserves_declarations_and_invalid_queue(self):
        one=project_queue({'REFACTOR_PLAN.md':json.dumps({'work_queue':[{'id':'a','status':'pending'}]})})
        two=project_queue({'REFACTOR_PLAN.md':json.dumps({'work_queue':[{'id':'a','status':'completed'}]})})
        delta=queue_delta(two['tasks'],one['tasks'])
        self.assertEqual(len(delta['changed']),1)
        self.assertEqual(two['tasks'][0]['allowed_operations'],[])
        self.assertEqual(project_queue({'REFACTOR_PLAN.md':'broken'})['status'],'INVALID')

    def test_local_manifests_follow_declarations_in_same_round_and_missing_blocks(self):
        package=self.f.repo/'packages/plugin'
        package.mkdir(parents=True)
        (package/'pubspec.yaml').write_text('name: plugin\nversion: 0.1.0\n')
        (self.f.repo/'pubspec.yaml').write_text('name: repo\nversion: 1.0.0\ndependencies:\n  plugin:\n    path: packages/plugin\n')
        with self.f.guarded() as stack:
            reads=self.f.track_reads(stack)
            plan=self.run_plan(max_files=4)
        p=plan['projects'][0]
        self.assertIn('packages/plugin/pubspec.yaml',p['required_files'])
        self.assertIn('packages/plugin/pubspec.yaml',reads)
        self.assertLessEqual(len(reads),4)
        (package/'pubspec.yaml').unlink()
        with self.f.guarded():plan=self.run_plan(max_files=4)
        self.assertEqual(plan['projects'][0]['status'],'BLOCKED')

    def test_local_path_escape_blocks_without_reading_neighbor(self):
        (self.f.repo/'pubspec.yaml').write_text('name: repo\nversion: 1.0.0\ndependencies:\n  outside:\n    path: ../outside\n')
        with self.f.guarded():plan=self.run_plan(max_files=4)
        self.assertIn('REQUIRED_LOCAL_MANIFEST_UNSAFE',str(plan['projects'][0]['blockers']))

    def test_sync_output_cannot_overwrite_checkpoint(self):
        file=self.f.root/'checkpoint.json';file.write_text('{}')
        with self.f.guarded(),self.assertRaises(ValueError):self.run_plan(output_path=file,checkpoint_paths={'fixture':file})
        self.assertEqual(file.read_text(),'{}')

    def test_explicit_required_guide_uses_override_and_dirty_is_not_business_failure(self):
        (self.f.repo/'AGENTS.override.md').write_text('active scoped guide')
        self.policy(['pubspec.yaml','AGENTS.md'],[])
        with self.f.guarded():plan=self.run_plan(max_files=8)
        p=plan['projects'][0]
        self.assertIn('AGENTS.override.md',p['required_files'])
        self.assertNotIn('AGENTS.md',{x['path'] for x in p['selected_files']})
        self.assertNotIn('BLOCKED',[p['status']])
        self.assertIn('DIRTY_WORKSPACE',str(p['warnings']))

    def test_malformed_required_local_manifest_and_optional_queue_have_different_outcomes(self):
        self.policy(['pubspec.yaml','packages/plugin/pubspec.yaml'],['REFACTOR_PLAN.md'])
        folder=self.f.repo/'packages/plugin';folder.mkdir(parents=True)
        (folder/'pubspec.yaml').write_text('broken: [')
        with self.f.guarded():plan=self.run_plan(max_files=8)
        self.assertEqual(plan['projects'][0]['status'],'BLOCKED')
        self.assertIn('MANIFEST_INVALID',str(plan['projects'][0]['blockers']))
        (folder/'pubspec.yaml').write_text('name: plugin\nversion: 0.1.0\n')
        (self.f.repo/'REFACTOR_PLAN.md').write_text('broken')
        with self.f.guarded():plan=self.run_plan(max_files=8)
        self.assertEqual(plan['projects'][0]['status'],'PARTIAL')
        self.assertIn('QUEUE_INVALID',str(plan['projects'][0]['gaps']))
