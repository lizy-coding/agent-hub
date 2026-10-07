import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent_hub.execution.control import ControlError, ExecutionStore, atomic_json, digest
from agent_hub.execution.decomposition_worker import DecompositionCodeExecutor
from agent_hub.execution.integration import integrate, validate_result
from agent_hub.execution.validation import freeze_checks
from agent_hub.graphs.decomposition import build_decomposition_graph
from agent_hub.graphs.migration_execution import build_migration_execution_graph


class ExecutionControlTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hub-control-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = ExecutionStore(self.root / 'control')
        self.repos = {}
        self.bases = {}
        for name in ('a', 'b'):
            repo = self.root / name; repo.mkdir(); self.repos[name] = repo
            self.git(repo, 'init', '-q')
            self.git(repo, 'config', 'user.email', 'fixture@example.invalid')
            self.git(repo, 'config', 'user.name', 'Fixture')
            (repo / 'model.txt').write_text('old')
            (repo / 'test_suite.py').write_text('''import unittest
from pathlib import Path
class TestModel(unittest.TestCase):
 def test_value(self): self.assertEqual(Path('model.txt').read_text(), 'new')
''')
            self.git(repo, 'add', '.')
            self.git(repo, 'commit', '-qm', 'base')
            self.bases[name] = self.git(repo, 'rev-parse', 'HEAD')
        self.fake = self.root / 'fake-codex'
        self.fake.write_text(f'#!{sys.executable}\n' + '''import sys
from pathlib import Path
for i, value in enumerate(sys.argv):
 if value == '--add-dir': (Path(sys.argv[i+1]) / 'model.txt').write_text('new')
''')
        self.fake.chmod(0o755)
        self.checks = {name: [{'check_id': 'python_unittest:test_suite', 'cwd': '.', 'timeout_seconds': 30}]
                       for name in self.repos}
        self.request = {'execution_kind': 'decomposition_migration', 'project_id': 'fixture', 'adapter': 'generic',
                        'task_id': 'change', 'cluster_root': str(self.root),
                        'repository_paths': {name: str(repo) for name, repo in self.repos.items()},
                        'repositories': [{'repository': name, 'base_revision': self.bases[name], 'writable': True} for name in self.repos],
                        'writable_repositories': [{'repository': name, 'writable': True, 'allowed_paths': ['model.txt']} for name in self.repos],
                        'allowed_paths_by_repository': {name: ['model.txt'] for name in self.repos},
                        'validation_by_repository': self.checks}
        self.executor = DecompositionCodeExecutor(codex_binary=str(self.fake), control_root=self.store.root)

    def git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()

    def execute(self):
        request = self.store.reserve(self.request)
        worker = self.executor.execute(request)
        self.assertEqual(worker['status'], 'SUCCESS', worker)
        return request, worker

    def test_real_worker_tests_and_integration_bind_the_same_tree(self):
        request, worker = self.execute()
        self.assertEqual(validate_result(self.store, request, worker), [])
        result = integrate(self.store, request, worker, self.repos)
        self.assertEqual(result['status'], 'INTEGRATED')
        for name, repo in self.repos.items():
            self.assertEqual((repo / 'model.txt').read_text(), 'new')
            self.assertEqual(self.git(repo, 'rev-parse', 'HEAD^{tree}'), worker['repositories'][name]['output_tree_oid'])
        self.assertEqual(integrate(self.store, request, worker, self.repos)['commits'], result['commits'])

    def test_duplicate_request_returns_durable_result_without_reexecuting(self):
        request, worker = self.execute()
        with patch.object(self.executor, '_execute', side_effect=AssertionError('duplicate execution')):
            self.assertEqual(self.executor.execute(request), worker)

    def test_mutated_contract_and_old_attempt_are_rejected(self):
        request, worker = self.execute()
        changed = deepcopy(request); changed['allowed_paths_by_repository']['a'].append('outside')
        self.assertEqual(self.executor.execute(changed)['status'], 'WORKER_CONTROL_REJECTED')
        new = self.store.reserve(self.request, previous=request)
        self.assertGreater(new['generation'], request['generation'])
        self.assertEqual(self.executor.execute(request)['reason'], 'STALE_EXECUTION_RESULT')
        self.assertIn('STALE_EXECUTION_RESULT', validate_result(self.store, new, worker))

    def test_new_run_cannot_steal_reserved_attempt(self):
        self.store.reserve(self.request)
        with self.assertRaisesRegex(ControlError, 'EXECUTION_ALREADY_RESERVED'):
            self.store.reserve(self.request)

    def test_os_lock_blocks_competing_process_and_releases_after_exit(self):
        source = Path(__file__).resolve().parents[1] / 'src'
        code = '''import json,sys
from pathlib import Path
from agent_hub.execution.control import ExecutionStore,ControlError
store=ExecutionStore(Path(sys.argv[1]))
try:
 with store.repositories(json.loads(sys.argv[2])): print('ACQUIRED')
except ControlError as e: print(e)
'''
        env = {**os.environ, 'PYTHONPATH': str(source)}
        with self.store.repositories(self.request):
            out = subprocess.check_output([sys.executable, '-c', code, str(self.store.root), json.dumps(self.request)], env=env).decode()
        self.assertIn('EXECUTION_BUSY', out)
        out = subprocess.check_output([sys.executable, '-c', code, str(self.store.root), json.dumps(self.request)], env=env).decode()
        self.assertIn('ACQUIRED', out)

    def test_failed_check_never_reaches_integration(self):
        self.fake.write_text(self.fake.read_text().replace("write_text('new')", "write_text('wrong')"))
        request = self.store.reserve(self.request)
        worker = self.executor.execute(request)
        self.assertEqual(worker['status'], 'VALIDATION_FAILED')
        with self.assertRaises(ControlError): integrate(self.store, request, worker, self.repos)
        for name, repo in self.repos.items():self.assertEqual(self.git(repo, 'rev-parse', 'HEAD'), self.bases[name])

    def test_missing_check_and_tampered_receipt_are_rejected(self):
        request, worker = self.execute()
        changed = deepcopy(worker); changed['repositories']['a']['validation_receipts'] = []
        self.assertEqual(validate_result(self.store, request, changed), ['WORKER_RECEIPT_MISMATCH'])
        changed = deepcopy(worker); changed['repositories']['a']['validation_receipts'][0]['output_tree_oid'] = 'f' * 40
        self.assertEqual(validate_result(self.store, request, changed), ['WORKER_RECEIPT_MISMATCH'])
        with self.assertRaisesRegex(ControlError, 'REQUIRED_VALIDATION_MISSING'):
            freeze_checks({}, ['a'])

    def test_validation_mutating_output_is_rejected(self):
        for repo in self.repos.values():
            (repo / 'test_suite.py').write_text("from pathlib import Path\nPath('model.txt').write_text('mutated')\n")
            self.git(repo, 'add', 'test_suite.py'); self.git(repo, 'commit', '-qm', 'mutating check')
        for item in self.request['repositories']: item['base_revision'] = self.git(self.repos[item['repository']], 'rev-parse', 'HEAD')
        request = self.store.reserve(self.request)
        self.assertEqual(self.executor.execute(request)['reason'], 'validation_changed_output')

    def test_all_repositories_are_preflighted_before_any_write(self):
        request, worker = self.execute()
        (self.repos['b'] / 'model.txt').write_text('user edit')
        with self.assertRaisesRegex(ControlError, 'INTEGRATION_WORKSPACE_DIRTY'):
            integrate(self.store, request, worker, self.repos)
        self.assertEqual(self.git(self.repos['a'], 'rev-parse', 'HEAD'), self.bases['a'])
        self.assertEqual((self.repos['a'] / 'model.txt').read_text(), 'old')

    def test_partial_commit_progress_is_durable_and_retry_does_not_repeat(self):
        request, worker = self.execute()
        from agent_hub.execution import integration
        original = integration.git
        def fail_second(root, *args, **kwargs):
            if root == self.repos['b'] and args[0] == 'commit': raise ControlError('injected commit failure')
            return original(root, *args, **kwargs)
        with patch.object(integration, 'git', side_effect=fail_second), self.assertRaisesRegex(ControlError, 'injected'):
            integrate(self.store, request, worker, self.repos)
        first = self.git(self.repos['a'], 'rev-parse', 'HEAD')
        record = self.store.verify(request)
        self.assertEqual(record['integration']['a']['commit'], first)
        self.assertEqual(record['integration']['b']['phase'], 'APPLYING')
        result = integrate(self.store, request, worker, self.repos)
        self.assertEqual(result['commits']['a'], first)
        self.assertEqual(self.git(self.repos['a'], 'rev-list', '--count', 'HEAD'), '2')

    def test_crash_after_commit_before_journal_save_is_reconciled(self):
        request, worker = self.execute()
        original = self.store.save
        def fail_save(request, record):
            if record['integration'].get('a', {}).get('phase') == 'COMMITTED': raise ControlError('crash before persistence')
            original(request, record)
        with patch.object(self.store, 'save', side_effect=fail_save), self.assertRaisesRegex(ControlError, 'crash'):
            integrate(self.store, request, worker, self.repos)
        first = self.git(self.repos['a'], 'rev-parse', 'HEAD')
        self.assertEqual(integrate(self.store, request, worker, self.repos)['commits']['a'], first)

    def test_missing_repository_map_never_falls_back_to_default_project(self):
        missing = deepcopy(self.request); missing['repository_paths'].pop('b')
        with self.assertRaisesRegex(ControlError, 'REPOSITORY_MAPPING_MISMATCH'): self.store.reserve(missing)

    def test_unimplemented_graph_reports_failure_explicitly(self):
        result = build_migration_execution_graph().invoke({})['execution_result']
        self.assertEqual(result['status'], 'EXECUTION_NOT_IMPLEMENTED')
        self.assertFalse(result['complete'])

    def test_different_worktrees_of_same_git_repository_share_writer_lock(self):
        linked = self.root / 'linked-a'
        self.git(self.repos['a'], 'worktree', 'add', '--detach', str(linked), self.bases['a'])
        other = deepcopy(self.request); other['task_id'] = 'other'
        other['repository_paths']['a'] = str(linked)
        with self.store.repositories(self.request), self.assertRaisesRegex(ControlError, 'EXECUTION_BUSY'):
            with self.store.repositories(other): pass

    def test_partial_integration_cannot_be_discarded_by_new_attempt(self):
        request, worker = self.execute()
        from agent_hub.execution import integration
        original = integration.git
        def fail_second(root, *args, **kwargs):
            if root == self.repos['b'] and args[0] == 'commit': raise ControlError('failure')
            return original(root, *args, **kwargs)
        with patch.object(integration, 'git', side_effect=fail_second), self.assertRaises(ControlError):
            integrate(self.store, request, worker, self.repos)
        with self.assertRaisesRegex(ControlError, 'INTEGRATION_RECOVERY_REQUIRED'):
            self.store.reserve(self.request, previous=request)

    def test_development_graph_uses_the_same_verified_execution_lane(self):
        from agent_hub.graphs.development import build_development_graph
        from agent_hub.workspace.config import WorkspaceConfig
        config = WorkspaceConfig(workspace_root=self.root, allowed_paths=[self.root],
                                 registry_path=self.root/'registry.json',
                                 runtime={'primary_repository_id':'a','repositories':{'a':{
                                     'runtime_path':str(self.repos['a']), 'managed':True,'writable':True,'role':'PRIMARY'}}})
        with patch('agent_hub.graphs.development._integration_root', return_value=self.repos['a']), \
             patch('agent_hub.graphs.development.reconcile_program', side_effect=lambda program, root: program), \
             patch('agent_hub.graphs.development._call_worker', side_effect=lambda request, *_: self.executor.execute(request)):
            result = build_development_graph(config, self.store.root).invoke({
                'repository_id':'a','development_task':{'task_id':'develop','requirement':'change',
                'allowed_paths':['model.txt'],'validation':['python_unittest:test_suite']}})['result']
        self.assertEqual(result['status'], 'PROGRAM_COMPLETED', result)
        self.assertEqual(result['program']['tasks'][0]['status'], 'DONE')
        self.assertEqual((self.repos['a']/'model.txt').read_text(), 'new')

    def test_dashboard_exposes_partial_repository_progress(self):
        from agent_hub.gateway.decomposition import render
        text = render({'values':{'decomposition_program':{'migration_tasks':[{
            'task_id':'change','maintenance_progress':{'a':{'phase':'COMMITTED','commit':'abc'},
                                                      'b':{'phase':'APPLYING'}}}]}}})
        self.assertIn('change / a: COMMITTED', text)
        self.assertIn('change / b: APPLYING', text)

    def test_late_worker_does_not_change_new_attempt_and_same_attempt_can_resume(self):
        old, old_worker=self.execute()
        current=self.store.reserve(self.request, previous=old)
        task={'task_id':'change','status':'DISPATCHING','execution_request':current,
              'source_units':['a/lib','b/lib'],'target_units':['a/lib','b/lib']}
        program={'project_id':'fixture','adapter':'generic','primary_repository_id':'a',
                 'status':'DISPATCHING','current_migration_task':'change','migration_tasks':[task]}
        with patch('agent_hub.graphs.decomposition._worker',side_effect=AssertionError('late result must not dispatch')):
            rejected=build_decomposition_graph(self.store.root).invoke({'execute':True,'worker_result':old_worker,'decomposition_program':program})
        active=rejected['decomposition_program']['migration_tasks'][0]
        self.assertEqual(active['status'],'DISPATCHING')
        self.assertEqual(active['execution_request']['attempt_id'],current['attempt_id'])
        with patch('agent_hub.graphs.decomposition._ensure_worktree',side_effect=lambda name,*_: (self.repos[name],'fixture')), \
             patch('agent_hub.graphs.decomposition._worker',side_effect=lambda request,*_: self.executor.execute(request)):
            resumed=build_decomposition_graph(self.store.root).invoke({**rejected,'execute':True})
        self.assertEqual(resumed['decomposition_program']['migration_tasks'][0]['status'],'DONE')
        self.assertEqual(self.store.verify(current)['request']['attempt_id'],current['attempt_id'])

    def test_graph_recovery_after_integration_before_done_does_not_reexecute(self):
        request, worker = self.execute()
        result = integrate(self.store, request, worker, self.repos)
        task = {'task_id':'change','status':'RUNNING','execution_request':request,
                'source_units':['a/lib','b/lib'],'target_units':['a/lib','b/lib'],
                'allowed_paths_by_repository':request['allowed_paths_by_repository']}
        program = {'project_id':'fixture','adapter':'generic','primary_repository_id':'a',
                   'cluster_root':str(self.root),'current_migration_task':'change','migration_tasks':[task]}
        with patch('agent_hub.graphs.decomposition._ensure_worktree',side_effect=lambda name,*_: (self.repos[name],'fixture')), \
             patch('agent_hub.graphs.decomposition._worker',side_effect=AssertionError('must not redispatch')):
            recovered = build_decomposition_graph(self.store.root).invoke({'execute':True,'decomposition_program':program})
        self.assertEqual(recovered['integration_result']['commits'], result['commits'])
        self.assertEqual(recovered['decomposition_program']['migration_tasks'][0]['status'],'DONE')

    def test_plan_only_recovery_never_integrates_saved_success(self):
        request, worker = self.execute()
        task={'task_id':'change','status':'RUNNING','execution_request':request}
        program={'current_migration_task':'change','migration_tasks':[task]}
        with patch('agent_hub.graphs.decomposition.integrate_verified',side_effect=AssertionError('read only')):
            build_decomposition_graph(self.store.root).invoke({'execute':False,'decomposition_program':program})
        self.assertEqual((self.repos['a']/'model.txt').read_text(),'old')

    def test_no_runnable_task_with_unfinished_dependencies_is_not_complete(self):
        task={'task_id':'change','status':'READY','depends_on':['unknown']}
        result=build_decomposition_graph(self.store.root).invoke({'execute':True,'decomposition_program':{'migration_tasks':[task]}})
        self.assertEqual(result['decomposition_program']['status'],'PROGRAM_BLOCKED')
        self.assertEqual(result['decomposition_program']['execution_blocker']['status'],'PROGRAM_INCOMPLETE')

    def test_graph_freeze_worker_validate_review_integrate_closed_loop(self):
        task = {'task_id': 'change', 'title': 'change', 'status': 'READY', 'depends_on': [],
                'source_units': ['a/lib', 'b/lib'], 'target_units': ['a/lib', 'b/lib'],
                'allowed_operations': ['MOVE'], 'allowed_paths_by_repository': self.request['allowed_paths_by_repository'],
                'validation_by_repository': self.checks}
        program = {'project_id': 'fixture', 'adapter': 'generic', 'primary_repository_id': 'a',
                   'cluster_root': str(self.root), 'migration_tasks': [task],
                   'repositories': [{'repository_id': name, 'path': str(repo)} for name, repo in self.repos.items()]}
        with patch('agent_hub.graphs.decomposition._ensure_worktree', side_effect=lambda name, *_: (self.repos[name], 'fixture')), \
             patch('agent_hub.graphs.decomposition._worker', side_effect=lambda request, *_: self.executor.execute(request)):
            result = build_decomposition_graph(self.store.root).invoke({'execute': True, 'decomposition_program': program})
        self.assertEqual(result['integration_result']['status'], 'COMMITTED', result)
        self.assertEqual(result['decomposition_program']['migration_tasks'][0]['status'], 'DONE')
        self.assertEqual(set(result['decomposition_program']['migration_tasks'][0]['maintenance_progress']), {'a', 'b'})


if __name__ == '__main__': unittest.main()
