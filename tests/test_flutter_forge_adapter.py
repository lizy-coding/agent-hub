import unittest
from pathlib import Path

from agent_hub.projects.flutter_forge_adapter import build_program


class FlutterForgeAdapterTest(unittest.TestCase):
    def test_android_readiness_tasks_have_ordered_boundaries(self):
        program = build_program(
            Path('/Users/forest/code/langGraph'),
            {
                'project_id': 'flutter-forge',
                'program_id': 'flutter-forge-decomposition-program',
                'primary_repository_id': 'flutter_forge',
                'repository_paths': {
                    'flutter_forge': '/Users/forest/code/langGraph/flutter_forge',
                },
            },
        )
        tasks = {task['task_id']: task for task in program['migration_tasks']}

        self.assertEqual(tasks['responsive_navigation_policy']['depends_on'], [])
        self.assertEqual(
            tasks['android_mobile_navigation_baseline']['depends_on'],
            ['responsive_navigation_policy'],
        )
        self.assertEqual(
            tasks['android_host_readiness']['depends_on'],
            ['android_mobile_navigation_baseline'],
        )
        self.assertEqual(
            tasks['pc_build_matrix']['depends_on'],
            ['pc_window_lifecycle_baseline'],
        )
        self.assertIn(
            'apps/flutter_forge/macos',
            tasks['pc_window_lifecycle_baseline']['allowed_paths_by_repository']['flutter_forge'],
        )
        self.assertIn(
            'apps/flutter_forge/lib/app/navigation_policy.dart',
            tasks['responsive_navigation_policy']['allowed_paths_by_repository']['flutter_forge'],
        )
        self.assertIn(
            'apps/flutter_forge/android',
            tasks['android_host_readiness']['allowed_paths_by_repository']['flutter_forge'],
        )


if __name__ == '__main__':
    unittest.main()
