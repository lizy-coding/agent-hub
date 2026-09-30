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
                'delivery_stage': {
                    'stage_id': 'cross-platform-foundation-v1',
                    'status': 'COMPLETE',
                    'supported_platforms': ['windows', 'macos', 'android', 'web'],
                    'next_stage': 'feature-expansion',
                    'next_stage_status': 'READY_FOR_PROPOSALS',
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
        web_capability = next(
            capability for capability in program['capabilities']
            if capability['capability_id'] == 'flutter-web-application-host'
        )
        self.assertEqual(web_capability['supported_platforms'], ['web'])
        self.assertFalse(web_capability['native_dependency'])
        app = next(candidate for candidate in program['package_candidates'] if candidate['package_id'] == 'apps/flutter_forge')
        self.assertIn('flutter-web-application-host', app['owned_capabilities'])
        self.assertEqual(tasks['web_host_readiness']['depends_on'], ['responsive_navigation_policy'])
        self.assertEqual(tasks['web_host_readiness']['status'], 'DONE')
        self.assertEqual(
            tasks['cross_platform_foundation_v1']['acceptance'],
            [
                'windows_support_baseline',
                'macos_support_baseline',
                'android_support_baseline',
                'web_support_baseline',
            ],
        )
        self.assertEqual(tasks['cross_platform_foundation_v1']['status'], 'DONE')
        self.assertEqual(tasks['feature_expansion_intake']['status'], 'PLANNED')
        self.assertEqual(tasks['feature_expansion_intake']['allowed_paths_by_repository'], {})
        self.assertTrue(program['next_phase']['execution_requires_frozen_proposal'])
        scene_capability = next(
            capability for capability in program['capabilities']
            if capability['capability_id'] == 'interactive-flutter-scene-3d-viewer'
        )
        self.assertEqual(
            scene_capability['supported_platforms'],
            ['android', 'macOS', 'windows'],
        )
        self.assertEqual(scene_capability['interaction_modes']['android'], 'view_only')
        self.assertIn('interactive-flutter-scene-3d-viewer', app['owned_capabilities'])
        self.assertIn('flutter_scene', app['dependencies'])
        self.assertIn('vector_math', app['dependencies'])
        self.assertEqual(tasks['flutter_scene_3d_macos_baseline']['status'], 'DONE')
        self.assertEqual(tasks['flutter_scene_3d_interaction_acceptance']['status'], 'PARTIAL')
        self.assertEqual(tasks['flutter_scene_3d_windows_admission']['status'], 'PARTIAL')
        self.assertEqual(tasks['flutter_scene_3d_android_view_only_admission']['status'], 'PARTIAL')
        self.assertEqual(
            tasks['flutter_scene_3d_android_view_only_admission']['allowed_paths_by_repository'],
            {},
        )
        video_capability = next(
            capability for capability in program['capabilities']
            if capability['capability_id'] == 'windows-resilient-online-video-playback'
        )
        self.assertEqual(video_capability['supported_platforms'], ['android', 'macOS', 'windows'])
        self.assertTrue(video_capability['supports_web'])
        self.assertEqual(tasks['android_online_video_playback']['status'], 'PARTIAL')
        usb_capability = next(
            capability for capability in program['capabilities']
            if capability['capability_id'] == 'usb-device-observation'
        )
        self.assertEqual(usb_capability['supported_platforms'], [])
        self.assertEqual(usb_capability['availability'], 'DISABLED_PENDING_WORKFLOW')
        self.assertEqual(tasks['android_usb_permission_boundary']['status'], 'SUPERSEDED')
        file_picker_capability = next(
            capability for capability in program['capabilities']
            if capability['capability_id'] == 'cross-platform-file-picker-learning-flow'
        )
        self.assertIn('android', file_picker_capability['target_platforms'])
        self.assertEqual(file_picker_capability['excluded_platforms'], ['iOS'])
        snapshot_capability = next(
            capability for capability in program['capabilities']
            if capability['capability_id'] == 'immutable-platform-snapshot-and-route-guard'
        )
        self.assertFalse(snapshot_capability['native_dependency'])
        adaptive_capability = next(
            capability for capability in program['capabilities']
            if capability['capability_id'] == 'adaptive-creator-navigation-shell'
        )
        self.assertIn('adaptive_app_shell.dart', adaptive_capability['entrypoints'])
        self.assertEqual(program['orchestration_sync']['task_count'], 20)
        self.assertEqual(program['orchestration_sync']['source_worktree_status'], 'CLEAN')
        self.assertEqual(len(program['orchestration_sync']['source_revision']), 40)
        self.assertEqual(program['orchestration_sync']['source_changed_paths'], [])
        self.assertIn('platform_snapshot_guarded_routes', program['orchestration_sync']['completed'])
        self.assertIn('android_file_picker_admission', program['orchestration_sync']['open'])
        self.assertTrue(all(
            task['allowed_paths_by_repository'] == {}
            for task in program['project_work_queue']
        ))


if __name__ == '__main__':
    unittest.main()
