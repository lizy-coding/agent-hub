import unittest

from agent_hub.projects.flutter_forge_adapter import proposal_inventory


class FlutterSceneProposalTest(unittest.TestCase):
    def test_freezes_new_module_platform_and_generated_contract_paths(self):
        program = {
            "primary_repository_id": "flutter_forge",
            "repositories": [
                {
                    "repository_id": "flutter_forge",
                    "path": "/Users/forest/code/langGraph/flutter_forge",
                },
            ],
        }
        spec = {
            "task_id": "add-flutter-scene-3d-learning-module",
            "execution_instructions": ["implement the scoped learning module"],
            "acceptance": ["quality gate passes"],
        }

        task = proposal_inventory(program, spec)

        self.assertEqual(task["status"], "READY")
        self.assertTrue(task["target_creation_allowed"])
        paths = task["allowed_paths_by_repository"]["flutter_forge"]
        self.assertIn(
            "apps/flutter_forge/lib/modules/ui/flutter_scene_3d",
            paths,
        )
        self.assertIn("apps/flutter_forge/macos/Runner/Info.plist", paths)
        self.assertIn("apps/flutter_forge/windows/runner/main.cpp", paths)
        self.assertIn("tool/generate_agent_indexes.js", paths)
        self.assertNotIn(".github/workflows/ci.yml", paths)
        self.assertEqual(
            task["execution_instructions"],
            spec["execution_instructions"],
        )


if __name__ == "__main__":
    unittest.main()
