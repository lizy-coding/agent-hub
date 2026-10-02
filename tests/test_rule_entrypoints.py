"""Agent rule inheritance follows real file scopes within explicit intake."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from agent_hub.context.resolver import RuleResolver, ancestor_agent_rules
from agent_hub.graphs.context_analysis import build_context_analysis_graph
from agent_hub.schemas.models import DevelopmentUnit, Repository, RuleFile, Workspace
from agent_hub.workspace.config import WorkspaceConfig


class RuleEntrypointTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.cache = self.workspace / "registry.json"
        self.config = WorkspaceConfig(workspace_root=self.workspace, allowed_paths=[self.workspace], registry_path=self.cache, registry_storage_path=self.cache)
        self.unit = DevelopmentUnit(unit_id="repo:.", repo_id="repo", relative_path=".", unit_type="library/package")
        self.repository = Repository(repo_id="repo", path=self.repo, development_units=[self.unit])
        self.write_cache()

    def write_cache(self, others=()):
        self.cache.write_text(Workspace(workspace_root=self.workspace, allowed_paths=[self.workspace], excluded_paths=[], registry_path=self.cache, repositories=[self.repository, *others]).model_dump_json(), encoding="utf-8")

    def put(self, value, text="Scoped instructions.\n"):
        path = self.repo / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def guarded(self):
        stack = ExitStack()
        for target in ("os.walk", "pathlib.Path.glob", "pathlib.Path.rglob"):
            stack.enter_context(patch(target, side_effect=AssertionError("recursive discovery is prohibited")))
        return stack

    def context(self, paths, max_files=24):
        return build_context_analysis_graph(self.config).invoke({"requirement": "agent parser contract", "target_repository": "repo", "candidate_paths": paths, "limits": {"max_files": max_files}})["context_package"]

    def rules_for(self, context, target):
        return [rule for rule in context["rules"] if rule["applies_to"] == f"repo:{target}"]

    def test_root_fallback_metadata_still_resolves_selected_cli_ancestors(self):
        paths = ["AGENTS.md", "lib/AGENTS.md", "lib/src/AGENTS.md", "lib/src/cli/AGENTS.md", "lib/src/cli/scan.dart"]
        for path in paths:
            self.put(path)
        with self.guarded():
            context = self.context(paths)
        rules = self.rules_for(context, "lib/src/cli/scan.dart")
        self.assertEqual([rule["path"] for rule in rules], ["repo/AGENTS.md", "repo/lib/AGENTS.md", "repo/lib/src/AGENTS.md", "repo/lib/src/cli/AGENTS.md"])
        self.assertEqual([rule["scope"] for rule in rules], ["repo", "repo/lib", "repo/lib/src", "repo/lib/src/cli"])

    def test_unselected_ancestor_is_reported_without_reading_it(self):
        self.put("AGENTS.md")
        missing = self.put("lib/src/cli/AGENTS.md")
        self.put("lib/src/cli/scan.dart")
        original = Path.read_text
        reads = []

        def read(path, *args, **kwargs):
            reads.append(path)
            return original(path, *args, **kwargs)

        with self.guarded(), patch.object(Path, "read_text", new=read):
            context = self.context(["AGENTS.md", "lib/src/cli/scan.dart"])
        self.assertNotIn(missing, reads)
        self.assertEqual([rule["path"] for rule in self.rules_for(context, "lib/src/cli/scan.dart")], ["repo/AGENTS.md"])
        self.assertTrue(any(item["subject"] == "repo/lib/src/cli/AGENTS.md" and "not selected" in item["reason"] for item in context["unknowns"]))
        self.assertEqual(context["metrics"]["missing_rule_candidates"], 1)

    def test_app_generator_and_cached_context_use_actual_directory_scopes(self):
        paths = ["AGENTS.md", "CONTEXT.md", "apps/app/AGENTS.md", "apps/app/AI_ANALYSIS.md", "tool/generator/AGENTS.md", "apps/app/main.dart", "tool/generator/index.py", "docs/adr/private.md"]
        for path in paths:
            self.put(path)
        self.repository.rule_files = [
            RuleFile(path="repo/CONTEXT.md", scope="repo", provenance="cached_contract"),
            RuleFile(path="repo/apps/app/AI_ANALYSIS.md", scope="repo/apps/app", provenance="cached_contract"),
            RuleFile(path="repo/docs/adr/private.md", scope="repo/docs/adr", provenance="cached_adr"),
            RuleFile(path="repo/apps/app/AGENTS.md", scope="repo", provenance="stale_wrong_scope"),
        ]
        self.write_cache()
        with self.guarded():
            context = self.context(paths)
        app = [rule["path"] for rule in self.rules_for(context, "apps/app/main.dart")]
        generator = [rule["path"] for rule in self.rules_for(context, "tool/generator/index.py")]
        self.assertEqual(app, ["repo/AGENTS.md", "repo/apps/app/AGENTS.md", "repo/CONTEXT.md", "repo/apps/app/AI_ANALYSIS.md"])
        self.assertEqual(generator, ["repo/AGENTS.md", "repo/tool/generator/AGENTS.md", "repo/CONTEXT.md"])
        self.assertNotIn("repo/docs/adr/private.md", app)
        self.assertEqual(len(generator), len(set(generator)))

    def test_unreadable_selected_guide_is_not_an_active_rule(self):
        self.put("AGENTS.md")
        denied = self.put("lib/AGENTS.md")
        self.put("lib/parser.dart")
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path == denied:
                raise PermissionError("fixture denied")
            return original(path, *args, **kwargs)

        with self.guarded(), patch.object(Path, "read_text", new=read):
            context = self.context(["AGENTS.md", "lib/AGENTS.md", "lib/parser.dart"])
        self.assertEqual([rule["path"] for rule in self.rules_for(context, "lib/parser.dart")], ["repo/AGENTS.md"])
        self.assertTrue(any(item["subject"] == "repo/lib/AGENTS.md" and "could not be read" in item["reason"] for item in context["unknowns"]))

    def test_cached_symlink_rules_and_symlink_sources_are_rejected(self):
        source = self.put("lib/parser.dart")
        self.put("AGENTS.md")
        target = self.put("docs/real-context.md")
        (self.repo / "CONTEXT.md").symlink_to(target)
        (self.repo / "linked-lib").symlink_to(source.parent, target_is_directory=True)
        self.repository.rule_files = [RuleFile(path="repo/CONTEXT.md", scope="repo", provenance="cached_contract")]
        self.write_cache()
        with self.guarded():
            resolver = RuleResolver(self.config)
            rules = resolver.resolve_rules_for_path(source)
            linked = resolver.resolve_rules_for_path(self.repo / "linked-lib/parser.dart")
        self.assertEqual([rule.path for rule in rules], ["repo/AGENTS.md"])
        self.assertEqual(linked, [])

    def test_override_masks_same_directory_guide_and_preserves_ancestor_order(self):
        paths = ["AGENTS.md", "AGENTS.override.md", "lib/AGENTS.md", "lib/parser.dart"]
        for path in paths:
            self.put(path)
        with self.guarded():
            context = self.context(paths)
            ancestors = ancestor_agent_rules(self.repo, self.repo / "lib/parser.dart")
        self.assertEqual(ancestors, [self.repo / "AGENTS.override.md", self.repo / "lib/AGENTS.md"])
        rules = self.rules_for(context, "lib/parser.dart")
        self.assertEqual([rule["path"] for rule in rules], ["repo/AGENTS.override.md", "repo/lib/AGENTS.md"])
        self.assertEqual(rules[0]["provenance"], "filesystem_agent_override")

    def test_unselected_override_does_not_downgrade_to_selected_normal_guide(self):
        self.put("AGENTS.md")
        self.put("AGENTS.override.md")
        self.put("lib/parser.dart")
        with self.guarded():
            context = self.context(["AGENTS.md", "lib/parser.dart"])
        self.assertEqual(self.rules_for(context, "lib/parser.dart"), [])
        self.assertTrue(any(item["subject"] == "repo/AGENTS.override.md" and "not selected" in item["reason"] for item in context["unknowns"]))

    def test_invalid_override_is_rejected_and_cross_repository_cache_never_applies(self):
        source = self.put("lib/parser.dart")
        self.put("AGENTS.md")
        other_root = self.workspace / "other"
        other_root.mkdir()
        (other_root / "CONTEXT.md").write_text("Other repository rules.\n", encoding="utf-8")
        (other_root / "source.dart").write_text("class Parser {}\n", encoding="utf-8")
        (self.repo / "AGENTS.override.md").symlink_to(other_root / "CONTEXT.md")
        self.repository.rule_files = [RuleFile(path="other/CONTEXT.md", scope="repo", provenance="invalid_cross_repo")]
        self.write_cache([Repository(repo_id="other", path=other_root, development_units=[DevelopmentUnit(unit_id="other:.", repo_id="other", relative_path=".", unit_type="library/package")])])
        with self.guarded():
            context = self.context(["AGENTS.md", "lib/parser.dart"])
            foreign = ancestor_agent_rules(self.repo, other_root / "source.dart")
            escaped = ancestor_agent_rules(self.repo, self.repo / "../other/source.dart")
        self.assertEqual(self.rules_for(context, "lib/parser.dart"), [])
        self.assertEqual(foreign, [])
        self.assertEqual(escaped, [])
        self.assertTrue(any(item["subject"] == "repo/AGENTS.override.md" and "unsafe" in item["reason"] for item in context["unknowns"]))

    def test_public_unit_call_keeps_identity_and_excludes_unrelated_scoped_rules(self):
        self.put("AGENTS.md")
        self.put("lib/src/cli/AGENTS.md")
        self.put("lib/src/rules/AGENTS.md")
        self.repository.development_units.append(DevelopmentUnit(unit_id="repo:lib/src/cli", repo_id="repo", relative_path="lib/src/cli", unit_type="library/package"))
        self.repository.rule_files = [RuleFile(path="repo/lib/src/rules/AGENTS.md", scope="repo/lib/src/rules", provenance="cached_sibling")]
        self.write_cache()
        with self.guarded():
            rules = RuleResolver(self.config).resolve_rules_for_path("repo:lib/src/cli")
        self.assertEqual([rule.path for rule in rules], ["repo/AGENTS.md", "repo/lib/src/cli/AGENTS.md"])
        self.assertTrue(all(rule.applies_to == "repo:lib/src/cli" for rule in rules))

    def test_guide_outside_selected_budget_is_unknown_and_never_read(self):
        source = self.put("lib/parser.dart")
        guide = self.put("AGENTS.md")
        original = Path.read_text
        source_reads = []

        def read(path, *args, **kwargs):
            if self.repo in path.parents:
                source_reads.append(path)
            return original(path, *args, **kwargs)

        with self.guarded(), patch.object(Path, "read_text", new=read):
            context = self.context(["lib/parser.dart", "AGENTS.md"], max_files=1)
        self.assertEqual(source_reads, [source])
        self.assertNotIn(guide, source_reads)
        self.assertEqual(context["rules"], [])
        self.assertEqual(context["metrics"]["missing_rule_candidates"], 1)

    def test_override_metadata_denial_reports_unknown_without_downgrade(self):
        self.put("AGENTS.md")
        override = self.put("AGENTS.override.md")
        source = self.put("lib/parser.dart")
        original = Path.stat

        def stat(path, *args, **kwargs):
            if path == override:
                raise PermissionError("override metadata denied")
            return original(path, *args, **kwargs)

        with self.guarded(), patch.object(Path, "stat", new=stat):
            ancestors = ancestor_agent_rules(self.repo, source)
            context = self.context(["AGENTS.md", "lib/parser.dart"])
        self.assertEqual(ancestors, [override])
        self.assertEqual(self.rules_for(context, "lib/parser.dart"), [])
        self.assertTrue(any(item["subject"] == "repo/AGENTS.override.md" and "unsafe" in item["reason"] for item in context["unknowns"]))


if __name__ == "__main__":
    unittest.main()
