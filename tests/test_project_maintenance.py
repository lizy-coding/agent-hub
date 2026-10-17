"""Regression fixtures for metadata automation without repository discovery."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from agent_hub.projects.inventory import manifest_versions, project_inventory, read_project_inventory, merge_inventory
from agent_hub.projects.registry_check import check_project_registry
from agent_hub.projects.release_config import load_release_project


class ProjectMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'product'
        self.repo.mkdir()
        self.workspace = self.root / 'workspace.json'
        self.workspace.write_text(json.dumps({'workspace_root': str(self.root), 'registry_path': str(self.root/'unused.json'),
            'runtime': {'primary_repository_id': 'product', 'repositories': {'product': {'runtime_path': str(self.repo), 'managed': True, 'writable': False}}}}))
        self.registry = self.root/'projects.json'
        self.payload = {'default_project': 'custom', 'aliases': {'alias': 'custom'}, 'projects': {'custom': {'adapter': 'generic', 'workspace_config': str(self.workspace), 'release': {'github_repo': 'org/product'}}}}
        self.save()
        self.env = patch.dict('os.environ', {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def save(self):
        self.registry.write_text(json.dumps(self.payload))

    def guarded(self):
        stack = ExitStack()
        for target in ['os.walk', 'pathlib.Path.glob', 'pathlib.Path.rglob', 'agent_hub.projects.workspace_registry.WorkspaceRegistry.refresh']:
            stack.enter_context(patch(target, side_effect=AssertionError('no discovery')))
        return stack

    def test_release_uses_runtime_identity_and_alias(self):
        with self.guarded():
            config = load_release_project('alias', registry_path=self.registry)
        self.assertEqual(config.repository_path, self.repo)
        self.assertEqual(config.primary_repository_id, 'product')
        self.assertEqual(config.graph_input()['adapter'], 'generic')
        self.assertTrue(check_project_registry(self.registry)['ok'])

    def test_registry_rejects_duplicate_namespace_unsafe_intake_and_unmanaged_write(self):
        entry = self.payload['projects']['custom']
        entry['snapshot_namespace'] = 'shared'
        entry['project_inventory'] = {'candidate_paths': ['../escape'], 'max_files': 0}
        self.payload['projects']['other'] = dict(entry)
        self.save()
        workspace = json.loads(self.workspace.read_text())
        workspace['runtime']['repositories']['product'].update(writable=True, managed=False)
        self.workspace.write_text(json.dumps(workspace))
        with self.guarded():
            result = check_project_registry(self.registry)
        reasons = str(result['errors'])
        self.assertFalse(result['ok'])
        for term in ['duplicate snapshot_namespace', 'unsafe candidate_paths', 'not managed', 'max_files']:
            self.assertIn(term, reasons)

    def test_version_is_order_independent_and_never_falls_back_to_package(self):
        texts = {'packages/plugin/pubspec.yaml': 'name: plugin\nversion: 9.9.9\n', 'apps/app/pubspec.yaml': 'name: app\nversion: 1.2.3+4\n'}
        for values in [texts, dict(reversed(list(texts.items())))]:
            result = manifest_versions(values, 'apps/app/pubspec.yaml')
            self.assertEqual(result['version'], '1.2.3+4')
            self.assertEqual(len(result['manifest_versions']), 2)
        result = manifest_versions({'packages/plugin/pubspec.yaml': texts['packages/plugin/pubspec.yaml']}, 'apps/app/pubspec.yaml')
        self.assertIsNone(result['version'])
        self.assertIn('PRIMARY_VERSION_NOT_OBSERVED', str(result['unknowns']))

    def texts(self):
        return {'apps/app/pubspec.yaml': 'name: app\nversion: 1.0.0\ndependencies:\n  battery:\n    path: ../../packages/battery\n',
                'packages/battery/pubspec.yaml': 'name: battery\nversion: 0.1.0\n',
                'apps/app/lib/battery/AI_ANALYSIS.md': json.dumps({'mode': 'module_contract', 'node': {'id': 'app.battery', 'status': 'pending'}, 'owns': ['session'], 'depends': ['battery'], 'platform_support': {'target_platforms': ['macos', 'web'], 'excluded_platforms': ['web']}})}

    def test_inventory_projects_owner_platform_dependency_and_preserves_policy(self):
        inventory = project_inventory(self.texts(), 'product', 'apps/app/pubspec.yaml')
        capability = inventory['capabilities'][0]
        self.assertEqual(capability['target_package'], 'apps/app')
        self.assertEqual(capability['supported_platforms'], ['macos'])
        self.assertEqual(capability['declared_status'], 'pending')
        self.assertEqual(inventory['target_dependency_graph']['edges'], [['apps/app', 'packages/battery']])
        self.assertFalse(inventory['acceptance'])
        program = {'capabilities': [{**capability, 'capability_id': 'legacy', 'classification': 'CUSTOM'}], 'package_candidates': [], 'migration_tasks': [{'status': 'PARTIAL'}]}
        merge_inventory(program, inventory)
        self.assertEqual(program['capabilities'][0]['capability_id'], 'legacy')
        self.assertEqual(program['capabilities'][0]['classification'], 'CUSTOM')
        self.assertEqual(program['migration_tasks'], [{'status': 'PARTIAL'}])

    def test_bounded_reader_counts_guides_and_reports_missing_and_budget(self):
        (self.repo/'AGENTS.md').write_text('root guide')
        for path, text in self.texts().items():
            target = self.repo/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        (self.repo/'apps/AGENTS.override.md').write_text('override')
        (self.repo/'apps/AGENTS.md').write_text('masked')
        with self.guarded():
            result = read_project_inventory(self.repo, 'product', {'candidate_paths': list(self.texts())+['missing.yaml'], 'max_files': 3}, 'apps/app/pubspec.yaml')
        self.assertEqual(result['metrics']['inspected_files'], 3)
        self.assertIn('BUDGET_EXHAUSTED', str(result['unknowns']))
        self.assertNotIn('apps/AGENTS.md', [x['path'] for x in result['files']])
        with self.guarded():
            result = read_project_inventory(self.repo, 'product', {'candidate_paths': ['missing.yaml'], 'max_files': 3}, 'pubspec.yaml')
        self.assertIn('FILE_UNAVAILABLE: missing.yaml', str(result['unknowns']))

    def test_git_pin_does_not_create_local_dependency_edge(self):
        texts = self.texts()
        texts['apps/app/pubspec.yaml'] = 'name: app\nversion: 1.0.0\ndependencies:\n  battery:\n    git:\n      url: https://example.invalid/battery\n      ref: pinned\n'
        result = project_inventory(texts, 'product', 'apps/app/pubspec.yaml')
        self.assertEqual(result['target_dependency_graph']['edges'], [])

    def test_forge_adapter_consumes_explicit_inventory_without_task_authority(self):
        from agent_hub.projects.flutter_forge_adapter import build_program
        (self.repo/'AGENTS.md').write_text('root guide')
        for path, text in self.texts().items():
            target = self.repo/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        with self.guarded():
            program = build_program(self.root, {'primary_repository_id': 'product', 'repository_paths': {'product': str(self.repo)},
                'primary_manifest': 'apps/app/pubspec.yaml', 'project_inventory': {'candidate_paths': list(self.texts()), 'max_files': 8}})
        self.assertIn('app.battery', [c['capability_id'] for c in program['capabilities']])
        self.assertIn('packages/battery', [c['package_id'] for c in program['package_candidates']])
        self.assertEqual(program['observed_dependency_graph']['edges'], [['apps/app', 'packages/battery']])
        self.assertEqual(program['execution_mode'], 'PLAN_ONLY')
        self.assertEqual(program['project_inventory']['allowed_paths_by_repository'], {})

    def test_invalid_contract_cycle_and_path_escape_remain_explicit(self):
        texts = self.texts()
        texts['packages/battery/pubspec.yaml'] += 'dependencies:\n  app:\n    path: ../../apps/app\n'
        texts['bad/AI_ANALYSIS.md'] = '{bad'
        result = project_inventory(texts, 'product', 'apps/app/pubspec.yaml')
        self.assertTrue(result['target_dependency_graph']['cycles'])
        self.assertIn('CONTRACT_INVALID', str(result['unknowns']))
        with self.guarded():
            result = read_project_inventory(self.repo, 'product', {'candidate_paths': ['../workspace.json'], 'max_files': 4}, 'pubspec.yaml')
        self.assertIn('UNSAFE_CANDIDATE', str(result['unknowns']))


if __name__ == '__main__':
    unittest.main()
