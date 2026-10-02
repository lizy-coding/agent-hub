import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent_hub.projects.adapters import get_adapter
from agent_hub.projects.gcode_core_adapter import _android_contract, _maintainer_acceptance


class GcodeCoreAdapterTest(unittest.TestCase):
    def build_program(self, root):
        def git_output(args, **kwargs):
            return '' if args[1] == 'status' else 'revision\n'

        with patch('agent_hub.projects.gcode_core_adapter.subprocess.check_output', side_effect=git_output):
            return get_adapter('gcode_core').build_program(
                root.parent,
                {'primary_repository_id': 'gcode_core', 'repository_paths': {'gcode_core': str(root)}},
            )

    def write_acceptance(self, root, version='0.2.1'):
        path = root / f'docs/evidence/{version}-maintainer-acceptance.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'# {version} maintainer acceptance\n\n'
            'Date: 2026-09-30. Source baseline: 7d561e3.\n\n'
            'The maintainer explicitly confirmed that macOS and Android manual acceptance\n'
            f'passed and authorized publication as {version}. This records that confirmation; no\n'
            'new automated native runtime validation was performed for this release.\n\n'
            'The confirmation did not include device/OS details, API-level coverage, Flutter\n'
            'revision, picker results, screenshots, or frame/memory measurements. Those\n'
            'details remain unrecorded. Android scope remains API 29+ and ARM64-only.\n'
            'Sustained 60 fps and long-running GPU memory behavior are not asserted.\n'
        )
        return path

    def test_root_package_and_example_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pubspec.yaml').write_text('name: gcode_core\nversion: 0.2.1\nenvironment:\n  flutter: ">=3.47.2"\ndependencies:\n  flutter_gpu:\n    sdk: flutter\nflutter:\n  assets: [shaders/toolpath.shaderbundle]\n')
            (root / 'example/android/app').mkdir(parents=True)
            (root / 'example/pubspec.yaml').write_text('name: example\n')
            (root / 'example/android/app/build.gradle.kts').write_text('minSdk = 29\nabiFilters += "arm64-v8a"\n')
            (root / 'docs/evidence/macos-gpu-only').mkdir(parents=True)
            (root / 'docs/evidence/macos-gpu-only/report.json').write_text('{}')
            manifest = root / 'example/android/app/src/main/AndroidManifest.xml'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                '<application><meta-data android:name="io.flutter.embedding.android.EnableFlutterGPU" '
                'android:value="true" /></application></manifest>'
            )
            self.write_acceptance(root)
            program = self.build_program(root)
        self.assertEqual(program['repositories'][0]['role'], 'PACKAGE')
        self.assertEqual(program['package_version'], '0.2.1')
        self.assertEqual(program['observed_worktree']['status'], 'CLEAN')
        self.assertEqual(program['target_dependency_graph']['edges'], [['example', '.']])
        self.assertEqual(program['build_requirements']['environment']['flutter'], '>=3.47.2')
        self.assertFalse(program['capabilities'][0]['native_dependency'])
        self.assertTrue(program['capabilities'][1]['native_dependency'])
        self.assertEqual(program['package_candidates'][1]['owned_capabilities'], ['gcode-example-session-playback'])
        self.assertEqual(program['platform_contract']['android']['minimum_api'], 29)
        self.assertEqual(program['platform_contract']['android']['abis'], ['arm64-v8a'])
        self.assertTrue(program['platform_contract']['android']['flutter_gpu_enabled'])
        self.assertEqual(program['platform_contract']['macos']['status'], 'BUILD_READY_RUNTIME_PENDING')
        self.assertEqual(program['platform_contract']['macos']['detailed_acceptance'], 'PENDING')
        historical = program['platform_contract']['macos']['historical_runtime_evidence']
        self.assertEqual(historical['status'], 'RECORDED')
        self.assertEqual(historical['current_revision_binding'], 'UNVERIFIED')
        acceptance = program['maintainer_acceptance']
        self.assertEqual(acceptance['status'], 'MAINTAINER_CONFIRMED')
        self.assertEqual(acceptance['source_baseline'], '7d561e3')
        self.assertEqual(acceptance['date'], '2026-09-30')
        self.assertEqual(acceptance['scope'], 'MANUAL_ACCEPTANCE_ONLY')
        self.assertEqual(acceptance['detailed_acceptance'], 'PENDING')
        self.assertIn('gcode_core/lib/src/models', program['capabilities'][0]['source_paths'])
        reader = next(capability for capability in program['capabilities'] if capability['capability_id'] == 'native-gcode-file-reading')
        self.assertEqual(reader['dependencies'], ['dart:io'])
        self.assertTrue(reader['platform_dependency'])
        self.assertTrue(reader['native_dependency'])
        self.assertFalse(reader['flutter_dependency'])
        self.assertEqual(program['migration_tasks'][1]['status'], 'PARTIAL')
        self.assertIn('docs/evidence/0.2.1-maintainer-acceptance.md', program['migration_tasks'][1]['evidence'])
        for task in program['migration_tasks']:
            self.assertEqual(task['allowed_operations'], [])
            self.assertEqual(task['allowed_paths_by_repository'], {})
        self.assertEqual(program['execution_mode'], 'PLAN_ONLY')

    def test_historical_report_does_not_validate_current_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pubspec.yaml').write_text('name: gcode_core\nversion: 0.2.2\n')
            path = root / 'docs/evidence/macos-gpu-only/report.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"fpsAcceptance":"PENDING"}')
            self.write_acceptance(root)
            program = self.build_program(root)
        self.assertEqual(program['maintainer_acceptance']['status'], 'UNKNOWN')
        self.assertEqual(program['maintainer_acceptance']['evidence'], [])
        self.assertEqual(program['platform_contract']['macos']['detailed_acceptance'], 'PENDING')
        self.assertEqual(program['platform_contract']['macos']['status'], 'BUILD_READY_RUNTIME_PENDING')
        self.assertEqual(program['migration_tasks'][0]['status'], 'DONE')
        self.assertEqual(program['migration_tasks'][0]['evidence_scope'], 'HISTORICAL_REPORT_ONLY')

    def test_acceptance_requires_current_version_statement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_acceptance(root).rename(root / 'docs/evidence/0.2.2-maintainer-acceptance.md')
            result = _maintainer_acceptance(root, '0.2.2')
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['platforms'], [])

    def test_acceptance_is_read_from_future_version_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_acceptance(root, '0.3.0')
            result = _maintainer_acceptance(root, '0.3.0')
        self.assertEqual(result['status'], 'MAINTAINER_CONFIRMED')
        self.assertEqual(result['version'], '0.3.0')
        self.assertEqual(result['detailed_acceptance'], 'PENDING')

    def test_gpu_metadata_must_be_enabled_inside_application(self):
        variants = [
            '<manifest />',
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application>'
            '<meta-data android:name="io.flutter.embedding.android.EnableFlutterGPU" android:value="false" />'
            '</application></manifest>',
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
            '<meta-data android:name="io.flutter.embedding.android.EnableFlutterGPU" android:value="true" />'
            '</manifest>',
            '<malformed',
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'example/android/app/src/main/AndroidManifest.xml'
            manifest.parent.mkdir(parents=True)
            for content in variants:
                with self.subTest(content=content):
                    manifest.write_text(content)
                    result = _android_contract(root)
                    self.assertFalse(result['flutter_gpu_enabled'])
                    self.assertEqual(result['host_configuration'], 'GPU_METADATA_MISSING_OR_INVALID')
                    self.assertEqual(result['detailed_acceptance'], 'PENDING')

    def test_missing_manifest_blocks_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            program = get_adapter('gcode_core').build_program(Path(directory), {'primary_repository_id':'gcode_core'})
        self.assertEqual(program['execution_blocker']['status'], 'MANIFEST_MISSING')
