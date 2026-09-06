import unittest
from agent_hub.projects.decomposition_config import load_decomposition_project
from agent_hub.projects.flutter_forge_adapter import build_program


class GcodeOwnershipTest(unittest.TestCase):
    def test_forge_references_independent_owner(self):
        project = load_decomposition_project('flutter-forge')
        program = build_program(project.cluster_root, project.graph_input())
        capability = next(c for c in program['capabilities'] if c['capability_id'] == 'gcode-parser-toolpath')
        self.assertEqual(capability['current_owners'], ['gcode_core'])
        self.assertNotIn('packages/gcode_core', [c['package_id'] for c in program['package_candidates']])
        self.assertEqual(load_decomposition_project('gcode-core').primary_repository_id, 'gcode_core')
