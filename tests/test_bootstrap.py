import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.graphs.bootstrap import build_bootstrap_graph
from agent_hub.workspace.config import WorkspaceConfig


class BootstrapGraphTest(unittest.TestCase):
    def test_accepts_a_registry_with_a_contained_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            repository.mkdir()
            registry = root / "registry.json"
            registry.write_text(
                json.dumps({"repositories": [{"repo_id": "example", "absolute_path": str(repository)}]}),
                encoding="utf-8",
            )
            config = WorkspaceConfig(
                workspace_root=root,
                allowed_paths=[root],
                excluded_paths=[],
                registry_path=registry,
            )
            result = build_bootstrap_graph(config).invoke({})["result"]
            self.assertTrue(result["ok"])
            self.assertEqual(result["repository_count"], 1)

    def test_rejects_a_repository_outside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "workspace"
            root.mkdir()
            outside = Path(temporary_directory) / "outside"
            outside.mkdir()
            registry = root / "registry.json"
            registry.write_text(
                json.dumps({"repositories": [{"repo_id": "outside", "absolute_path": str(outside)}]}),
                encoding="utf-8",
            )
            config = WorkspaceConfig(
                workspace_root=root,
                allowed_paths=[root],
                excluded_paths=[],
                registry_path=registry,
            )
            result = build_bootstrap_graph(config).invoke({})["result"]
            self.assertFalse(result["ok"])
            self.assertFalse(result["checks"]["repository_paths_valid"])


if __name__ == "__main__":
    unittest.main()
