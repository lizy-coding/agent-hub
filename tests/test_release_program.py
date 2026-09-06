import unittest
from pathlib import Path

from agent_hub.projects.release_program import is_flutter_forge_android_arm64, valid_release_tag
from agent_hub.projects.release_config import load_release_project


class ReleaseProgramTest(unittest.TestCase):
    def test_android_release_accepts_only_arm64_apk_and_aab(self):
        self.assertTrue(is_flutter_forge_android_arm64(Path("app-arm64-v8a-release.apk")))
        self.assertTrue(is_flutter_forge_android_arm64(Path("app-release.aab")))
        self.assertFalse(is_flutter_forge_android_arm64(Path("app-armeabi-v7a-release.apk")))
        self.assertFalse(is_flutter_forge_android_arm64(Path("app-x86_64-release.apk")))

    def test_release_tag_is_semver(self):
        self.assertTrue(valid_release_tag("v1.2.3"))
        self.assertFalse(valid_release_tag("latest"))

    def test_flutter_forge_build_matrix_is_arm64_only(self):
        matrix = load_release_project("flutter-forge").graph_input()["release"]["build_matrix"]
        self.assertEqual(list(matrix), ["android-arm64"])
        self.assertIn("--target-platform android-arm64", matrix["android-arm64"]["commands"][1])
        self.assertEqual(matrix["android-arm64"]["artifacts"], ["app-release.aab", "app-arm64-v8a-release.apk"])


if __name__ == "__main__":
    unittest.main()
