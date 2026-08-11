import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.projects.workspace_registry import WorkspaceRegistry
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig


class WorkspaceRegistryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.config = WorkspaceConfig(workspace_root=self.root, allowed_paths=[self.root], excluded_paths=[], registry_path=self.root / "bootstrap.json", registry_storage_path=self.root / "registry.json")
        self.config.registry_path.write_text("{}")

    def tearDown(self): self.temp.cleanup()
    def write(self, relative, content):
        path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content); return path
    def repo(self, name):
        path = self.root / name; (path / ".git").mkdir(parents=True); return path

    def test_load_discovery_multi_unit_agents_dependencies_and_queries(self):
        self.repo("repo")
        self.write("repo/AGENTS.md", "rules")
        self.write("repo/pubspec.yaml", "name: root\ndependencies:\n  child:\n    path: packages/child\n")
        self.write("repo/packages/child/pubspec.yaml", "name: child\n")
        self.write("repo/packages/child/test/x_test.dart", "")
        registry = WorkspaceRegistry(self.config)
        self.assertEqual(registry.refresh()["added"], ["repo"])
        repo = registry.get_repository("repo")
        self.assertEqual(len(repo.development_units), 2)
        root_unit = registry.find_unit_by_path(self.root / "repo" / "lib")
        self.assertIsNotNone(root_unit)
        self.assertEqual(len(registry.get_dependencies(root_unit.unit_id)), 1)
        child = next(unit for unit in repo.development_units if unit.relative_path == "packages/child")
        self.assertEqual(registry.get_dependents(child.unit_id)[0].source, root_unit.unit_id)
        self.assertEqual(registry.get_rule_files(root_unit.unit_id)[0].path, "repo/AGENTS.md")
        self.assertTrue(registry.get_validation_commands(child.unit_id))

    def test_refresh_added_removed_changed_and_invalid_dependency(self):
        self.repo("one")
        manifest = self.write("one/pubspec.yaml", "name: one\ndependencies:\n  missing:\n    path: ../outside\n")
        registry = WorkspaceRegistry(self.config)
        self.assertEqual(registry.refresh()["added"], ["one"])
        self.assertEqual(registry.get_dependencies("one:."), [])
        self.write("two/.git/placeholder", "")
        self.write("two/pubspec.yaml", "name: two\n")
        self.assertEqual(registry.refresh()["added"], ["two"])
        manifest.write_text("name: one\nversion: 2.0.0\n")
        self.assertIn("one", registry.refresh()["changed"])
        for path in (self.root / "two").rglob("*"):
            if path.is_file(): path.unlink()
        (self.root / "two" / ".git").rmdir(); (self.root / "two").rmdir()
        self.assertEqual(registry.refresh()["removed"], ["two"])

    def test_boundaries_symlink_and_unknown_are_not_guessed(self):
        self.repo("repo")
        self.write("repo/pubspec.yaml", "name: repo\n")
        outside = Path(self.temp.name) / "outside"; outside.mkdir()
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        registry = WorkspaceRegistry(self.config)
        registry.refresh()
        self.assertFalse(is_allowed_business_path(self.root / ".." / "outside", self.config))
        self.assertFalse(is_allowed_business_path(self.root / "escape", self.config))
        unit = registry.get_development_unit("repo:.")
        self.assertEqual(unit.capabilities, ["repo"])
        self.assertEqual(registry.find_unit_by_path(outside), None)
        self.assertEqual(registry.validate_registry(), [])


if __name__ == "__main__": unittest.main()
