import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent_hub.projects.adapters import get_adapter


class GcodeCoreAdapterTest(unittest.TestCase):
    def test_root_package_and_example_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pubspec.yaml').write_text('name: gcode_core\nenvironment:\n  flutter: ">=3.47.2"\ndependencies:\n  flutter_gpu:\n    sdk: flutter\nflutter:\n  assets: [shaders/toolpath.shaderbundle]\n')
            (root / 'example/android/app').mkdir(parents=True)
            (root / 'example/pubspec.yaml').write_text('name: example\n')
            (root / 'example/android/app/build.gradle.kts').write_text('minSdk = 29\nabiFilters += "arm64-v8a"\n')
            (root / 'docs/evidence/macos-gpu-only').mkdir(parents=True)
            (root / 'docs/evidence/macos-gpu-only/report.json').write_text('{}')
            with patch('agent_hub.projects.gcode_core_adapter.subprocess.check_output', return_value='revision\n'):
                program = get_adapter('gcode_core').build_program(root.parent, {'primary_repository_id':'gcode_core', 'repository_paths':{'gcode_core':str(root)}})
        self.assertEqual(program['repositories'][0]['role'], 'PACKAGE')
        self.assertEqual(program['target_dependency_graph']['edges'], [['example', '.']])
        self.assertEqual(program['build_requirements']['environment']['flutter'], '>=3.47.2')
        self.assertFalse(program['capabilities'][0]['native_dependency'])
        self.assertTrue(program['capabilities'][1]['native_dependency'])
        self.assertEqual(program['package_candidates'][1]['owned_capabilities'], ['gcode-example-session-playback'])
        self.assertEqual(program['platform_contract']['android']['minimum_api'], 29)
        self.assertEqual(program['platform_contract']['android']['abis'], ['arm64-v8a'])
        self.assertEqual(program['platform_contract']['macos']['status'], 'RUNTIME_VALIDATED')
        self.assertEqual(program['migration_tasks'][1]['status'], 'PARTIAL')
        self.assertEqual(program['execution_mode'], 'PLAN_ONLY')

    def test_missing_manifest_blocks_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            program = get_adapter('gcode_core').build_program(Path(directory), {'primary_repository_id':'gcode_core'})
        self.assertEqual(program['execution_blocker']['status'], 'MANIFEST_MISSING')
