"""Explicit graph intakes must never discover or search neighboring sources."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from agent_hub.capability.analyzer import CapabilityAnalyzer
from agent_hub.context.resolver import ContextLimits, ContextResolver
from agent_hub.graphs.capability_analysis import build_capability_analysis_graph
from agent_hub.graphs.context_analysis import build_context_analysis_graph
from agent_hub.schemas.models import Dependency, DevelopmentUnit, Evidence, Repository, RuleFile, Workspace
from agent_hub.workspace.config import WorkspaceConfig


class BoundedContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.workspace = root / "workspace"
        self.repo = self.workspace / "repo"
        (self.repo / "lib/src").mkdir(parents=True)
        self.source = self.repo / "lib/src/scaffold.dart"
        self.source.write_text("class LearningScaffold extends StatelessWidget {\n final Widget content;\n Widget build() => Scaffold(body: content);\n}\n", encoding="utf-8")
        self.barrel = self.repo / "lib/repo.dart"
        self.barrel.write_text("export 'src/scaffold.dart';\n", encoding="utf-8")
        self.unlisted = self.repo / "lib/src/unlisted.dart"
        self.unlisted.write_text("class UnlistedParser {}\n", encoding="utf-8")
        (self.repo / "pubspec.yaml").write_text("name: repo\n", encoding="utf-8")
        self.plan = self.repo / "REFACTOR_PLAN.md"
        self.plan.write_text(json.dumps({"work_queue": [{"id": "scaffold-update", "status": "pending", "targets": ["lib/src/scaffold.dart"]}]}), encoding="utf-8")
        neighbor = self.workspace / "neighbor"
        neighbor.mkdir()
        (neighbor / "parser.dart").write_text("class NeighborParser {}\n", encoding="utf-8")
        edge = Dependency(source="repo:.", target="neighbor:.", kind="path_dependency", evidence=Evidence(source="fixture", path="repo/pubspec.yaml", discovered_at="fixture"))
        unit = DevelopmentUnit(unit_id="repo:.", repo_id="repo", relative_path=".", unit_type="library/package", manifests=["repo/pubspec.yaml"], dependencies=[edge])
        repositories = [
            Repository(repo_id="repo", path=self.repo, development_units=[unit], rule_files=[RuleFile(path="repo/REFACTOR_PLAN.md", scope="repo", provenance="fixture")]),
            Repository(repo_id="neighbor", path=neighbor, development_units=[DevelopmentUnit(unit_id="neighbor:.", repo_id="neighbor", relative_path=".", unit_type="library/package")]),
        ]
        registry = root / "registry.json"
        registry.write_text(Workspace(workspace_root=self.workspace, allowed_paths=[self.workspace], excluded_paths=[], registry_path=registry, repositories=repositories).model_dump_json(), encoding="utf-8")
        self.config = WorkspaceConfig(workspace_root=self.workspace, allowed_paths=[self.workspace], registry_path=registry, registry_storage_path=registry)

    def guarded(self):
        stack = ExitStack()
        for target in ("agent_hub.context.resolver.os.walk", "pathlib.Path.glob", "pathlib.Path.rglob"):
            stack.enter_context(patch(target, side_effect=AssertionError("source traversal is prohibited")))
        return stack

    def track_source_reads(self, stack):
        reads = []
        original = Path.read_text

        def read(path, *args, **kwargs):
            if self.workspace in path.parents:
                reads.append(path)
            return original(path, *args, **kwargs)

        stack.enter_context(patch.object(Path, "read_text", new=read))
        return reads

    def test_both_graphs_only_read_explicit_candidates(self):
        state = {"requirement": "Widget scaffold", "target_repository": "repo", "candidate_paths": ["lib/src/scaffold.dart"], "limits": {"max_files": 1, "max_symbols": 1}}
        with self.guarded() as stack:
            reads = self.track_source_reads(stack)
            context = build_context_analysis_graph(self.config).invoke(state)["context_package"]
            analysis = build_capability_analysis_graph(self.config).invoke(state)["capability_analysis"]
        self.assertEqual(set(reads), {self.source})
        self.assertEqual(context["scope"]["development_units"], ["repo:."])
        self.assertEqual(context["scope"]["repositories"], ["repo"])
        self.assertEqual(context["dependencies"][0]["target"], "neighbor:.")
        self.assertEqual(context["metrics"]["searched_files"], 1)
        self.assertLessEqual(len(context["symbols"]), 1)
        self.assertEqual(context["planned_capabilities"], [])
        self.assertEqual(len(analysis["capabilities"]), 1)
        self.assertEqual(analysis["capabilities"][0]["ownership"], "ui_only")

    def test_empty_intake_does_not_fall_back_to_search(self):
        state = {"requirement": "parser", "target_repository": "repo", "candidate_paths": []}
        with self.guarded() as stack:
            reads = self.track_source_reads(stack)
            context = build_context_analysis_graph(self.config).invoke(state)["context_package"]
            analysis = build_capability_analysis_graph(self.config).invoke(state)["capability_analysis"]
        self.assertEqual(reads, [])
        self.assertEqual(context["files"], [])
        self.assertEqual(analysis["capabilities"], [])

    def test_public_export_requires_explicit_barrel_evidence(self):
        with self.guarded() as stack:
            reads = self.track_source_reads(stack)
            analysis = CapabilityAnalyzer(self.config).analyze_capabilities("Widget scaffold", "repo", candidate_paths=["lib/src/scaffold.dart", "lib/repo.dart"])
        node = next(node for node in analysis.capabilities if node.files == ["repo/lib/src/scaffold.dart"])
        self.assertEqual(node.ownership, "reusable_capability")
        self.assertEqual(set(reads), {self.source, self.barrel})

    def test_plan_is_read_only_when_it_is_explicit_and_selected(self):
        state = {"requirement": "scaffold", "target_repository": "repo", "candidate_paths": ["lib/src/scaffold.dart", "REFACTOR_PLAN.md"]}
        with self.guarded() as stack:
            reads = self.track_source_reads(stack)
            package = build_context_analysis_graph(self.config).invoke(state)["context_package"]
        self.assertEqual(set(reads), {self.source, self.plan})
        self.assertEqual(package["planned_capabilities"][0]["task_id"], "scaffold-update")
        with self.guarded() as stack:
            reads = self.track_source_reads(stack)
            package = build_context_analysis_graph(self.config).invoke({**state, "limits": {"max_files": 1}})["context_package"]
        self.assertEqual(set(reads), {self.source})
        self.assertEqual(package["planned_capabilities"], [])

    def test_invalid_candidates_fail_without_discovery(self):
        (self.repo / "link.dart").symlink_to(self.source)
        (self.repo / "linked-dir").symlink_to(self.repo / "lib", target_is_directory=True)
        invalid = [str(self.source), "../neighbor/parser.dart", "lib", "missing.dart", "link.dart", "linked-dir/src/scaffold.dart"]
        with self.guarded():
            resolver = ContextResolver(self.config)
            for path in invalid:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    resolver.resolve_context("parser", "repo", candidate_paths=[path])
            with self.assertRaises(ValueError):
                resolver.resolve_context("parser", candidate_paths=[])
            with self.assertRaises(ValueError):
                resolver.resolve_context("parser", "unknown", candidate_paths=[])

    def test_limits_apply_to_files_actually_read(self):
        with self.guarded() as stack:
            reads = self.track_source_reads(stack)
            package = ContextResolver(self.config).resolve_context("parser scaffold", "repo", ContextLimits(max_files=1, max_symbols=0), candidate_paths=["lib/src/scaffold.dart", "lib/src/unlisted.dart"])
        self.assertEqual(reads, [self.source])
        self.assertEqual(package.symbols, [])
        self.assertEqual(package.metrics["candidate_files"], 2)

    def test_legacy_call_without_candidates_remains_supported(self):
        with patch("agent_hub.context.resolver.RepositorySearcher._source_files", return_value=[self.source]), patch.object(Path, "glob", return_value=[self.barrel]):
            resolver = ContextResolver(self.config)
            context = resolver.resolve_context("Widget scaffold", "repo", ContextLimits(max_files=2, max_symbols=3))
            analysis = CapabilityAnalyzer(self.config).analyze_capabilities("Widget scaffold", "repo")
        self.assertTrue(context.files)
        self.assertNotIn("candidate_paths", context.request)
        self.assertTrue(analysis.capabilities)


if __name__ == "__main__":
    unittest.main()
