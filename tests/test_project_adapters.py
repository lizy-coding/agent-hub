import tempfile
import unittest
from pathlib import Path

from agent_hub.graphs.decomposition import build_decomposition_graph
from agent_hub.projects.adapters import get_adapter, list_adapters


class ProjectAdapterTest(unittest.TestCase):
    def test_registry_exposes_flutter_forge_and_generic_adapters(self):
        self.assertIn("flutter_forge", list_adapters())
        self.assertIn("generic", list_adapters())

    def test_generic_adapter_builds_a_project_neutral_plan(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repository = root / "product"
            (repository / "packages" / "shared").mkdir(parents=True)
            (repository / "pubspec.yaml").write_text("name: product\n")
            (repository / "packages" / "shared" / "pubspec.yaml").write_text("name: shared\n")
            program = get_adapter("generic").build_program(
                root,
                {
                    "project_id": "product",
                    "program_id": "product-decomposition-program",
                    "adapter": "generic",
                    "primary_repository_id": "product",
                    "repository_paths": {"product": str(repository)},
                },
            )

        self.assertEqual(program["project_id"], "product")
        self.assertEqual(program["adapter"], "generic")
        self.assertEqual(program["migration_tasks"], [])
        self.assertEqual(program["package_candidates"][0]["package_id"], "packages/shared")

    def test_graph_initializes_a_registered_generic_project_without_flutter_rules(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repository = root / "product"
            repository.mkdir()
            (repository / "pubspec.yaml").write_text("name: product\n")
            state = build_decomposition_graph().invoke(
                {
                    "cluster_root": str(root),
                    "project_context": {
                        "project_id": "product",
                        "program_id": "product-decomposition-program",
                        "adapter": "generic",
                        "primary_repository_id": "product",
                        "repository_paths": {"product": str(repository)},
                    },
                }
            )

        program = state["decomposition_program"]
        self.assertEqual(program["project_id"], "product")
        self.assertEqual(program["adapter"], "generic")
        self.assertEqual(program["migration_tasks"], [])

    def test_unknown_adapter_is_rejected(self):
        with self.assertRaises(ValueError):
            get_adapter("not-installed")


if __name__ == "__main__":
    unittest.main()
