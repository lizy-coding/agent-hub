import unittest
from pathlib import Path

from agent_hub.context.resolver import ContextLimits, ContextResolver
from agent_hub.projects import api as registry_api
from agent_hub.workspace.config import WorkspaceConfig


class ContextResolverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = WorkspaceConfig.from_file(Path(__file__).parents[1] / "workspace/config.json")
        cls.resolver = ContextResolver(cls.config)

    def test_requirement_returns_bounded_valid_package(self):
        package = self.resolver.resolve_context("GCode package import callsite", "flutter_forge", ContextLimits(max_files=3, max_symbols=5))
        self.assertLessEqual(len(package.files), 3)
        self.assertLessEqual(len(package.symbols), 5)
        self.assertTrue(package.dependencies)
        self.assertEqual(self.resolver.validate_context_package(package), [])

    def test_symbol_callsite_rules_and_dependency_queries(self):
        unit_id = "flutter_forge:apps/flutter_forge"
        self.assertTrue(self.resolver.search_symbols(unit_id, "gcode"))
        self.assertTrue(self.resolver.search_callsites(unit_id, "gcode_core"))
        self.assertTrue(self.resolver.resolve_rules_for_path("flutter_forge:."))

    def test_name_only_is_not_confirmed(self):
        package = self.resolver.resolve_context("unmatched_term_xyz", "flutter_forge")
        self.assertTrue(package.unknowns)
        self.assertTrue(all(candidate.confidence in {"LOW", "BLOCKED"} for candidate in package.candidates if candidate.classification == "unknown"))

    def test_workspace_boundary_and_registry_storage_independence(self):
        self.assertIsNone(registry_api.find_unit_by_path(self.config, Path("/Users/forest/code/agent-hub")))
        source_text = "\n".join(path.read_text() for path in Path(__file__).parents[1].joinpath("src/agent_hub/context").rglob("*.py"))
        self.assertNotIn("registry.json", source_text)


if __name__ == "__main__": unittest.main()
