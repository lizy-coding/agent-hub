"""Public context entrypoint preserves read-only and evidence identity."""
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub.projects.agent_context import refresh_agent_contexts
from tests import test_agent_context as context_fixtures


class AgentContextIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.fixture = context_fixtures.AgentContextTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def policy(self, seeds, prefixes=None):
        f = self.fixture
        payload = json.loads(f.project_registry.read_text())
        payload['projects']['fixture']['agent_context'] = {
            'seed_files': seeds, 'change_prefixes': prefixes or [],
        }
        f.project_registry.write_text(json.dumps(payload))

    def test_output_cannot_overwrite_any_managed_file_or_workspace_config(self):
        f = self.fixture
        for output in (f.repo / 'pubspec.yaml', f.repo / 'unmonitored.md', f.workspace_config):
            original = output.read_bytes()
            with self.subTest(output=output), f.guarded(), self.assertRaises(ValueError):
                refresh_agent_contexts(output_path=output, max_files=6, registry_path=f.project_registry)
            self.assertEqual(output.read_bytes(), original)

    def test_consumer_git_subdirectory_is_part_of_lock_binding(self):
        f = self.fixture
        self.policy(['AGENTS.md', 'pubspec.yaml', 'pubspec.lock'])
        (f.repo / 'pubspec.yaml').write_text('name: repo\nversion: 1.0.0\ndependencies:\n  tool:\n    git:\n      url: https://example.invalid/tool\n      ref: ' + 'a'*40 + '\n      path: packages/current\n')
        (f.repo / 'pubspec.lock').write_text('packages:\n  tool:\n    source: git\n    version: 1.0.0\n    description:\n      url: https://example.invalid/tool\n      ref: ' + 'a'*40 + '\n      resolved-ref: ' + 'a'*40 + '\n      path: packages/stale\n')
        with f.guarded():
            result = refresh_agent_contexts(output_path=f.output, max_files=3, registry_path=f.project_registry)
        pin = result['projects'][0]['dependency_pins'][0]
        self.assertEqual(pin['binding_state'], 'MANIFEST_LOCK_REF_MISMATCH')

    def test_unknown_project_cli_exits_nonzero_with_reason(self):
        f = self.fixture
        env = os.environ.copy()
        env['AGENT_HUB_PROJECT_REGISTRY'] = str(f.project_registry)
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([str(root/'.venv/bin/python'), str(root/'agent'), 'agent-context', '--project', 'missing-project', '--output', str(f.output)], cwd=root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('UNKNOWN_PROJECT_OR_CONTEXT_POLICY', result.stdout + result.stderr)

    def test_budget_packs_first_source_with_its_guides_before_other_branches(self):
        f = self.fixture
        self.policy(['lib/a.dart', 'beta/one.dart', 'gamma/two.dart'])
        (f.repo/'lib/a.dart').write_text('class Parser { int parse() => 1; }')
        for folder, name in [('beta', 'one.dart'), ('gamma', 'two.dart')]:
            directory = f.repo/folder
            directory.mkdir()
            (directory/'AGENTS.md').write_text('Scoped guide')
            (directory/name).write_text('class Widget {}')
        with f.guarded() as stack:
            reads = f.track_reads(stack)
            result = refresh_agent_contexts(output_path=f.output, max_files=3, registry_path=f.project_registry)
        selected = {x['path'] for x in result['projects'][0]['selected_files']}
        self.assertIn('lib/a.dart', selected)
        self.assertNotIn('beta/AGENTS.md', reads)
        self.assertNotIn('gamma/AGENTS.md', reads)
        self.assertLessEqual(len(reads), 3)

    def test_task_intake_follows_explicit_exports_without_walking(self):
        f = self.fixture
        self.policy(['AGENTS.md', 'lib/entry.dart'])
        (f.repo/'lib/entry.dart').write_text("export 'parser.dart';")
        with f.guarded():
            result = refresh_agent_contexts(output_path=f.output, max_files=4, registry_path=f.project_registry, requirement='解析文本的解析器')
        self.assertIn('lib/parser.dart', {x['path'] for x in result['projects'][0]['selected_files']})

    def test_disk_change_after_capture_does_not_change_analyzed_text(self):
        f = self.fixture
        self.policy(['AGENTS.md', 'lib/parser.dart'])
        from agent_hub.projects import agent_context
        real_factory = agent_context.build_context_analysis_graph

        def changed_disk(config):
            (f.repo/'lib/parser.dart').write_text('class Widget {}')
            return real_factory(config)

        with f.guarded(), patch.object(agent_context, 'build_context_analysis_graph', side_effect=changed_disk):
            result = refresh_agent_contexts(output_path=f.output, max_files=3, registry_path=f.project_registry)
        project = result['projects'][0]
        symbols = {x['name'] for x in project['context_package']['symbols']}
        self.assertIn('parser', symbols)
        self.assertNotIn('widget', symbols)
        self.assertEqual(project['evidence_mode'], 'FROZEN_SOURCE_TEXTS')


if __name__ == '__main__':
    unittest.main()
