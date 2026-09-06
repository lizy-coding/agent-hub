import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub.projects.flutter_forge_adapter import build_program, proposal_inventory
import json


class WebviewProposalTest(unittest.TestCase):
    def test_inventory_reads_platform_boundary_and_git_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / 'apps/flutter_forge/lib/modules/platform/webview'
            module.mkdir(parents=True)
            (module / 'AI_ANALYSIS.md').write_text(json.dumps({'route':'/webview', 'supported_platforms':['android','macOS','windows'], 'depends':['webview_flutter','webview_windows']}))
            with patch('agent_hub.projects.flutter_forge_adapter.subprocess.check_output', return_value='abc123\n'):
                program = build_program(root.parent, {'repository_paths':{'flutter_forge':str(root)}})
            capability = next(c for c in program['capabilities'] if c['capability_id'] == 'embedded-webview-navigation')
            self.assertEqual(capability['supported_platforms'], ['android', 'macOS', 'windows'])
            self.assertEqual(capability['route'], '/webview')
            task = next(t for t in program['migration_tasks'] if t['task_id'] == 'integrate-historical-webview-module')
            self.assertEqual(task['status'], 'DONE')
            self.assertEqual(task['allowed_paths_by_repository'], {})
            self.assertEqual(task['native_runtime_acceptance'], 'NOT_VERIFIED_BY_INVENTORY')

    def test_missing_module_is_not_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            program = build_program(Path(directory), {})
        self.assertNotIn('embedded-webview-navigation', [c['capability_id'] for c in program['capabilities']])

    def test_freezes_webview_paths_without_media_migration_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            program = {"primary_repository_id": "flutter_forge", "repositories": [{"repository_id": "flutter_forge", "path": directory}]}
            spec = {"task_id": "integrate-historical-webview-module", "execution_instructions": ["integrate source"], "acceptance": ["lifecycle tests pass"]}
            with patch("agent_hub.projects.flutter_forge_adapter.subprocess.check_output", return_value="AI_ANALYSIS.md\napps/flutter_forge/pubspec.yaml\n"):
                task = proposal_inventory(program, spec)
            self.assertEqual(task["status"], "READY")
            paths = task["allowed_paths_by_repository"]["flutter_forge"]
            self.assertIn("apps/flutter_forge/lib/modules/platform/webview/platforms/webview2_backend.dart", paths)
            self.assertFalse(any("online_video_player" in p for p in paths))
            self.assertNotIn(".github/workflows/ci.yml", paths)
            self.assertEqual(task["execution_instructions"], spec["execution_instructions"])
            self.assertTrue(task["target_creation_allowed"])
