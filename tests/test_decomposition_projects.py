import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.gateway.decomposition_state import load, save, validate
from agent_hub.projects.decomposition_config import load_decomposition_project


class DecompositionProjectConfigTest(unittest.TestCase):
    def test_registry_resolves_project_through_workspace_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repository = root / "product"
            repository.mkdir()
            workspace = root / "workspace.json"
            workspace.write_text(json.dumps({
                "workspace_root": str(root),
                "allowed_paths": [str(root)],
                "registry_path": str(root / "registry.json"),
                "runtime": {
                    "primary_repository_id": "product",
                    "repositories": {
                        "product": {
                            "runtime_path": str(repository),
                            "role": "PRIMARY",
                            "managed": True,
                            "writable": True,
                        }
                    },
                },
            }))
            registry = root / "projects.json"
            registry.write_text(json.dumps({
                "default_project": "product",
                "projects": {
                    "product": {
                        "adapter": "generic_test",
                        "program_id": "product-decomposition-program",
                        "workspace_config": str(workspace),
                    }
                },
            }))

            project = load_decomposition_project(registry_path=registry)

        self.assertEqual(project.project_id, "product")
        self.assertEqual(project.primary_repository_id, "product")
        self.assertEqual(project.repository_paths["product"], repository.resolve())
        self.assertEqual(project.program_id, "product-decomposition-program")
        self.assertEqual(project.refactor_program_id, "product-refactor-program")

    def test_unknown_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            registry = Path(raw) / "projects.json"
            registry.write_text(json.dumps({"default_project": "known", "projects": {}}))
            with self.assertRaises(KeyError):
                load_decomposition_project("missing", registry_path=registry)

    def test_snapshot_namespace_isolated_by_project(self):
        state = {"values": {"decomposition_program": {
            "project_id": "alpha",
            "program_id": "alpha-decomposition-program",
            "cluster_root": "/workspace",
            "migration_tasks": [{"task_id": "t"}],
            "managed_worktrees": [],
        }}}
        with tempfile.TemporaryDirectory() as raw:
            from unittest.mock import patch
            with patch("agent_hub.gateway.decomposition_state.ROOT", Path(raw)):
                save("thread", state, "alpha")
                self.assertIsNotNone(load("thread", "alpha"))
                self.assertIsNone(load("thread", "beta"))
                snapshot = load("thread", "alpha")
                self.assertIsNone(validate(snapshot, "thread", "/workspace", "alpha-decomposition-program", "alpha"))


if __name__ == "__main__":
    unittest.main()
