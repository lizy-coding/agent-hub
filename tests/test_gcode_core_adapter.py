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
            (root / 'example').mkdir()
            (root / 'example/pubspec.yaml').write_text('name: example\n')
            with patch('agent_hub.projects.gcode_core_adapter.subprocess.check_output', return_value='revision\n'):
                program = get_adapter('gcode_core').build_program(root.parent, {'primary_repository_id':'gcode_core', 'repository_paths':{'gcode_core':str(root)}})
        self.assertEqual(program['repositories'][0]['role'], 'PACKAGE')
        self.assertEqual(program['target_dependency_graph']['edges'], [['example', '.']])
        self.assertEqual(program['build_requirements']['environment']['flutter'], '>=3.47.2')
        self.assertTrue(program['capabilities'][0]['native_dependency'])
        self.assertEqual(program['migration_tasks'], [])

    def test_missing_manifest_blocks_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            program = get_adapter('gcode_core').build_program(Path(directory), {'primary_repository_id':'gcode_core'})
        self.assertEqual(program['execution_blocker']['status'], 'MANIFEST_MISSING')
