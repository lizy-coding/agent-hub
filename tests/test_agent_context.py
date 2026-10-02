"""The managed-project refresh entrypoint uses bounded files, never discovery."""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from agent_hub.projects.agent_context import refresh_agent_contexts
from agent_hub.schemas.models import DevelopmentUnit, Repository, Workspace


class AgentContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        (self.repo / "lib").mkdir(parents=True)
        (self.repo / "pubspec.yaml").write_text("name: repo\nversion: 1.0.0+1\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("Parser ownership remains in this package.\n", encoding="utf-8")
        (self.repo / "lib/parser.dart").write_text("class Parser { int parse() => 1; }\n", encoding="utf-8")
        (self.repo / "unmonitored.md").write_text("unrelated content\n", encoding="utf-8")
        self.git("init", "-b", "main")
        self.git("add", "--", "pubspec.yaml", "AGENTS.md", "lib/parser.dart", "unmonitored.md")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture baseline")
        self.source_sha = self.git("rev-parse", "HEAD").strip()
        (self.repo / "lib/parser.dart").write_text("class Parser { int parse() => 2; }\n", encoding="utf-8")
        (self.repo / "unmonitored.md").write_text("unrelated dirty content\n", encoding="utf-8")
        (self.repo / "lib/binary.dart").write_bytes(b"\0binary")
        (self.repo / "NEW_AGENT.md").write_text("Untracked explicit control document.\n", encoding="utf-8")
        (self.repo / "link.dart").symlink_to(self.repo / "lib/parser.dart")
        self.cache = self.root / "cache.json"
        self.workspace_config = self.root / "config.json"
        self.workspace_config.write_text(json.dumps({"workspace_root": str(self.root), "allowed_paths": [str(self.repo)], "registry_path": str(self.root / "bootstrap.json"), "registry_storage_path": str(self.cache), "runtime": {"primary_repository_id": "repo", "repositories": {"repo": {"runtime_path": str(self.repo), "managed": True, "writable": False}}}}), encoding="utf-8")
        self.project_registry = self.root / "projects.json"
        self.project_registry.write_text(json.dumps({"default_project": "fixture", "projects": {"fixture": {"adapter": "generic", "workspace_config": str(self.workspace_config), "agent_context": {"seed_files": ["pubspec.yaml", "AGENTS.md", "lib/missing.dart", "lib", "link.dart", "lib/binary.dart", "NEW_AGENT.md"], "change_prefixes": ["lib/"]}}}}), encoding="utf-8")
        self.output = self.root / "context.json"
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        for key in ("AGENT_HUB_PROJECT_REGISTRY", "AGENT_HUB_PROJECT", "AGENT_HUB_WORKSPACE_ROOT", "AGENT_HUB_CHECKOUT_ROOT", "AGENT_HUB_PRIMARY_REPOSITORY"):
            os.environ.pop(key, None)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True)
        return result.stdout

    def guarded(self):
        stack = ExitStack()
        for target in ("os.walk", "pathlib.Path.glob", "pathlib.Path.rglob", "agent_hub.projects.workspace_registry.WorkspaceRegistry.refresh", "agent_hub.projects.discovery.discover"):
            stack.enter_context(patch(target, side_effect=AssertionError("repository discovery is prohibited")))
        return stack

    def track_reads(self, stack):
        reads = set()
        for method in ("read_bytes", "read_text"):
            original = getattr(Path, method)

            def read(path, *args, original=original, **kwargs):
                if self.repo in path.parents:
                    reads.add(path.relative_to(self.repo).as_posix())
                return original(path, *args, **kwargs)

            stack.enter_context(patch.object(Path, method, new=read))
        return reads

    def test_entrypoint_graphs_read_only_bounded_files_and_record_worktree(self):
        with self.guarded() as stack:
            reads = self.track_reads(stack)
            snapshot = refresh_agent_contexts(output_path=self.output, max_files=6, registry_path=self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(snapshot, json.loads(self.output.read_text(encoding="utf-8")))
        self.assertTrue(snapshot["no_walk"])
        self.assertEqual(snapshot["snapshot_scope"], "scoped_snapshot_not_full_registry")
        self.assertFalse(snapshot["acceptance"])
        self.assertEqual(project["source_sha"], self.source_sha)
        self.assertEqual(project["branch"], "main")
        self.assertEqual(project["version"], "1.0.0+1")
        self.assertIn("lib/parser.dart", project["workspace_dirty_paths"])
        self.assertIn("unmonitored.md", project["workspace_dirty_paths"])
        self.assertLessEqual(len(reads), 6)
        self.assertNotIn("unmonitored.md", reads)
        parser = next(item for item in project["selected_files"] if item["path"] == "lib/parser.dart")
        self.assertTrue(parser["dirty_tracked"])
        self.assertEqual(parser["sha256"], hashlib.sha256((self.repo / "lib/parser.dart").read_bytes()).hexdigest())
        self.assertEqual(project["registry_metadata_mode"], "EXPLICIT_ROOT_FALLBACK")
        reasons = {item["reason"] for item in project["ignored_candidates"]}
        self.assertTrue({"MISSING_OR_DELETED", "DIRECTORY_OR_NONREGULAR_FILE", "SYMLINK", "BINARY_OR_UNREADABLE_FILE", "OUTSIDE_MONITORED_CHANGE_PREFIXES"}.issubset(reasons))
        self.assertTrue(any("UNTRACKED_EXPLICIT_FILE" in gap for gap in project["unknowns"]))
        self.assertTrue(any("DIRTY_WORKSPACE" in gap for gap in project["unknowns"]))
        self.assertEqual(project["scope"]["repositories"], ["repo"])

    def test_mandatory_guide_priority_and_hard_file_budget(self):
        with self.guarded() as stack:
            reads = self.track_reads(stack)
            snapshot = refresh_agent_contexts(["fixture"], self.output, 1, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(reads, {"AGENTS.md"})
        self.assertEqual([item["path"] for item in project["selected_files"]], ["AGENTS.md"])
        self.assertEqual(project["metrics"]["inspected_files"], 1)
        self.assertTrue(any(item["reason"] == "FILE_BUDGET_EXHAUSTED" for item in project["ignored_candidates"]))
        self.assertTrue(any("FILE_BUDGET_EXHAUSTED: pubspec.yaml" in gap for gap in project["unknowns"]))

    def test_root_fallback_intake_includes_existing_multilevel_agent_guides(self):
        source = self.repo / "lib/feature/parser.dart"
        source.parent.mkdir()
        source.write_text("class Parser { int parse() => 3; }\n", encoding="utf-8")
        (self.repo / "lib/AGENTS.md").write_text("Library parsing contract.\n", encoding="utf-8")
        (source.parent / "AGENTS.md").write_text("Feature parsing contract.\n", encoding="utf-8")
        payload = json.loads(self.project_registry.read_text(encoding="utf-8"))
        payload["projects"]["fixture"]["agent_context"] = {"seed_files": ["lib/feature/parser.dart"], "change_prefixes": []}
        self.project_registry.write_text(json.dumps(payload), encoding="utf-8")
        with self.guarded() as stack:
            reads = self.track_reads(stack)
            snapshot = refresh_agent_contexts(["fixture"], self.output, 4, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(project["registry_metadata_mode"], "EXPLICIT_ROOT_FALLBACK")
        self.assertEqual(reads, {"AGENTS.md", "lib/AGENTS.md", "lib/feature/AGENTS.md", "lib/feature/parser.dart"})
        self.assertEqual([item["path"] for item in project["selected_files"]], ["AGENTS.md", "lib/AGENTS.md", "lib/feature/AGENTS.md", "lib/feature/parser.dart"])
        self.assertEqual(project["metrics"]["inspected_files"], 4)
        rules = {rule["path"] for rule in project["context_package"]["rules"]}
        self.assertEqual(rules, {"AGENTS.md", "lib/AGENTS.md", "lib/feature/AGENTS.md"})

    def test_multilevel_guides_exhaust_budget_without_reading_unguarded_source(self):
        source = self.repo / "lib/feature/parser.dart"
        source.parent.mkdir()
        source.write_text("class Parser { int parse() => 3; }\n", encoding="utf-8")
        (self.repo / "lib/AGENTS.md").write_text("Library parsing contract.\n", encoding="utf-8")
        (source.parent / "AGENTS.md").write_text("Feature parsing contract.\n", encoding="utf-8")
        payload = json.loads(self.project_registry.read_text(encoding="utf-8"))
        payload["projects"]["fixture"]["agent_context"] = {"seed_files": ["lib/feature/parser.dart"], "change_prefixes": []}
        self.project_registry.write_text(json.dumps(payload), encoding="utf-8")
        with self.guarded() as stack:
            reads = self.track_reads(stack)
            snapshot = refresh_agent_contexts(["fixture"], self.output, 2, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(reads, {"AGENTS.md", "lib/AGENTS.md"})
        self.assertEqual(project["metrics"]["inspected_files"], 2)
        self.assertEqual(project["metrics"]["max_files"], 2)
        ignored = {item["path"]: item["reason"] for item in project["ignored_candidates"]}
        self.assertEqual(ignored["lib/feature/parser.dart"], "FILE_BUDGET_EXHAUSTED")
        self.assertEqual(ignored["lib/feature/AGENTS.md"], "FILE_BUDGET_EXHAUSTED")
        self.assertIn("FILE_BUDGET_EXHAUSTED: lib/feature/parser.dart", project["unknowns"])

    def test_override_guide_masks_seeded_standard_guide_without_extra_reads(self):
        (self.repo / "lib/AGENTS.md").write_text("Superseded guidance.\n", encoding="utf-8")
        (self.repo / "lib/AGENTS.override.md").write_text("Active scoped guidance.\n", encoding="utf-8")
        payload = json.loads(self.project_registry.read_text(encoding="utf-8"))
        payload["projects"]["fixture"]["agent_context"] = {"seed_files": ["lib/AGENTS.md", "lib/parser.dart"], "change_prefixes": []}
        self.project_registry.write_text(json.dumps(payload), encoding="utf-8")
        with self.guarded() as stack:
            reads = self.track_reads(stack)
            snapshot = refresh_agent_contexts(["fixture"], self.output, 3, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(reads, {"AGENTS.md", "lib/AGENTS.override.md", "lib/parser.dart"})
        self.assertIn({"path": "lib/AGENTS.md", "reason": "AGENT_GUIDE_OVERRIDDEN", "origins": ["seed"]}, project["ignored_candidates"])
        rules = {rule["path"] for rule in project["context_package"]["rules"]}
        self.assertEqual(rules, {"AGENTS.md", "lib/AGENTS.override.md"})

    def test_unreadable_override_records_gap_and_blocks_source_without_fallback(self):
        (self.repo / "lib/AGENTS.md").write_text("Superseded guidance.\n", encoding="utf-8")
        override = self.repo / "lib/AGENTS.override.md"
        override.write_text("Active but unreadable guidance.\n", encoding="utf-8")
        payload = json.loads(self.project_registry.read_text(encoding="utf-8"))
        payload["projects"]["fixture"]["agent_context"] = {"seed_files": ["lib/parser.dart"], "change_prefixes": []}
        self.project_registry.write_text(json.dumps(payload), encoding="utf-8")
        original = Path.read_bytes

        def deny_override(path):
            if path == override:
                raise PermissionError("fixture guide permission denied")
            return original(path)

        with self.guarded() as stack:
            reads = self.track_reads(stack)
            stack.enter_context(patch.object(Path, "read_bytes", new=deny_override))
            snapshot = refresh_agent_contexts(["fixture"], self.output, 3, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(reads, {"AGENTS.md"})
        self.assertEqual([item["path"] for item in project["selected_files"]], ["AGENTS.md"])
        self.assertEqual(project["metrics"]["inspected_files"], 2)
        self.assertTrue(any("BINARY_OR_UNREADABLE_FILE: lib/AGENTS.override.md" in gap for gap in project["unknowns"]))
        ignored = {item["path"]: item for item in project["ignored_candidates"]}
        self.assertEqual(ignored["lib/parser.dart"]["reason"], "REQUIRED_AGENT_GUIDE_UNAVAILABLE")
        self.assertEqual(ignored["lib/parser.dart"]["required_guides"], ["lib/AGENTS.override.md"])

    def test_symlink_override_records_gap_and_never_falls_back_to_standard_guide(self):
        (self.repo / "lib/AGENTS.md").write_text("Superseded guidance.\n", encoding="utf-8")
        (self.repo / "lib/AGENTS.override.md").symlink_to(self.repo / "missing-guide.md")
        payload = json.loads(self.project_registry.read_text(encoding="utf-8"))
        payload["projects"]["fixture"]["agent_context"] = {"seed_files": ["lib/parser.dart"], "change_prefixes": []}
        self.project_registry.write_text(json.dumps(payload), encoding="utf-8")
        with self.guarded() as stack:
            reads = self.track_reads(stack)
            snapshot = refresh_agent_contexts(["fixture"], self.output, 3, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(reads, {"AGENTS.md"})
        self.assertEqual(project["metrics"]["inspected_files"], 1)
        self.assertIn("SYMLINK: lib/AGENTS.override.md", project["unknowns"])
        self.assertTrue(any("REQUIRED_AGENT_GUIDE_UNAVAILABLE: lib/parser.dart" in gap for gap in project["unknowns"]))

    def test_guide_metadata_permission_failure_is_a_specific_gap(self):
        (self.repo / "lib/AGENTS.md").write_text("Superseded guidance.\n", encoding="utf-8")
        override = self.repo / "lib/AGENTS.override.md"
        override.write_text("Active but inaccessible guidance.\n", encoding="utf-8")
        payload = json.loads(self.project_registry.read_text(encoding="utf-8"))
        payload["projects"]["fixture"]["agent_context"] = {"seed_files": ["lib/parser.dart"], "change_prefixes": []}
        self.project_registry.write_text(json.dumps(payload), encoding="utf-8")
        original = Path.is_file

        def deny_override_metadata(path):
            if path == override:
                raise PermissionError("fixture guide stat permission denied")
            return original(path)

        with self.guarded() as stack:
            reads = self.track_reads(stack)
            stack.enter_context(patch.object(Path, "is_file", new=deny_override_metadata))
            snapshot = refresh_agent_contexts(["fixture"], self.output, 3, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(project["status"], "REFRESHED_WITH_GAPS")
        self.assertEqual(reads, {"AGENTS.md"})
        self.assertIn("PATH_METADATA_UNREADABLE: lib/AGENTS.override.md", project["unknowns"])
        self.assertTrue(any("REQUIRED_AGENT_GUIDE_UNAVAILABLE: lib/parser.dart" in gap for gap in project["unknowns"]))

    def test_cached_target_metadata_is_scoped_and_preserved(self):
        unit = DevelopmentUnit(unit_id="repo:.", repo_id="repo", relative_path=".", unit_type="library/package", manifests=["repo/pubspec.yaml"])
        other = Repository(repo_id="unrelated", path=self.root / "unrelated")
        repository = Repository(repo_id="repo", path=self.repo, development_units=[unit])
        self.cache.write_text(Workspace(workspace_root=self.root, allowed_paths=[self.root], excluded_paths=[], registry_path=self.cache, repositories=[repository, other]).model_dump_json(), encoding="utf-8")
        before = self.cache.read_bytes()
        with self.guarded():
            snapshot = refresh_agent_contexts(["fixture"], self.output, 2, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(project["registry_metadata_mode"], "CACHED_TARGET_METADATA")
        self.assertEqual(project["scope"]["repositories"], ["repo"])
        self.assertEqual(self.cache.read_bytes(), before)
        with self.guarded(), self.assertRaises(ValueError):
            refresh_agent_contexts(["fixture"], self.cache, 1, self.project_registry)
        self.assertEqual(self.cache.read_bytes(), before)

    def test_unknown_project_is_reported(self):
        with self.guarded():
            snapshot = refresh_agent_contexts(["not-registered"], self.output, 2, self.project_registry)
        self.assertEqual(snapshot["projects"][0]["status"], "UNKNOWN_PROJECT_OR_CONTEXT_POLICY")
        self.assertEqual(snapshot["summary"]["refreshed"], 0)
        self.assertEqual(snapshot["summary"]["selected_files"], 0)

    def test_project_alias_uses_canonical_policy_and_deduplicates(self):
        payload = json.loads(self.project_registry.read_text(encoding="utf-8"))
        payload["aliases"] = {"forge": "fixture"}
        self.project_registry.write_text(json.dumps(payload), encoding="utf-8")
        with self.guarded():
            snapshot = refresh_agent_contexts(["forge", "fixture"], self.output, 1, self.project_registry)
        self.assertEqual(snapshot["summary"]["projects"], 1)
        self.assertEqual(snapshot["projects"][0]["project_id"], "fixture")
        self.assertEqual(snapshot["projects"][0]["selected_files"][0]["path"], "AGENTS.md")

    def test_app_version_and_consumer_pins_come_from_selected_manifests(self):
        core_sha = "22d" + "0" * 37
        guard_sha = "9f9" + "1" * 37
        (self.repo / "pubspec.yaml").write_text("name: fixture_workspace\nworkspace:\n  - apps/app\n", encoding="utf-8")
        app = self.repo / "apps/app"
        app.mkdir(parents=True)
        (app / "pubspec.yaml").write_text(f"name: app\nversion: 1.2.8+2\ndependencies:\n  gcode_core:\n    git:\n      url: https://example.invalid/gcode_core.git\n      ref: v0.2.1\ndev_dependencies:\n  flutterguard_cli:\n    git:\n      url: https://example.invalid/flutterguard.git\n      ref: {guard_sha}\n", encoding="utf-8")
        (self.repo / "pubspec.lock").write_text(f"packages:\n  gcode_core:\n    source: git\n    version: 0.2.1\n    description:\n      url: https://example.invalid/gcode_core.git\n      ref: v0.2.1\n      resolved-ref: {core_sha}\n  flutterguard_cli:\n    source: git\n    version: 0.6.0\n    description:\n      url: https://example.invalid/flutterguard.git\n      ref: {guard_sha}\n      resolved-ref: {guard_sha}\n", encoding="utf-8")
        payload = json.loads(self.project_registry.read_text(encoding="utf-8"))
        payload["projects"]["fixture"]["agent_context"]["seed_files"] = ["pubspec.yaml", "apps/app/pubspec.yaml", "pubspec.lock"]
        self.project_registry.write_text(json.dumps(payload), encoding="utf-8")
        with self.guarded() as stack:
            reads = self.track_reads(stack)
            snapshot = refresh_agent_contexts(["fixture"], self.output, 4, self.project_registry)
        project = snapshot["projects"][0]
        self.assertEqual(reads, {"AGENTS.md", "pubspec.yaml", "apps/app/pubspec.yaml", "pubspec.lock"})
        self.assertEqual(project["version"], "1.2.8+2")
        self.assertEqual(project["version_source"], "apps/app/pubspec.yaml")
        pins = {item["package"]: item for item in project["dependency_pins"]}
        self.assertEqual(pins["gcode_core"]["requested_ref"], "v0.2.1")
        self.assertEqual(pins["gcode_core"]["resolved_ref"], core_sha)
        self.assertEqual(pins["flutterguard_cli"]["requested_ref"], guard_sha)
        self.assertEqual(pins["flutterguard_cli"]["resolved_ref"], guard_sha)
        self.assertEqual(pins["flutterguard_cli"]["locked_version"], "0.6.0")
        self.assertTrue(all(item["binding_state"] == "DECLARED_AND_LOCKED" for item in pins.values()))
        self.assertTrue(all(item["consumer_manifest"] == "apps/app/pubspec.yaml" for item in pins.values()))

    def test_invalid_budgets_are_rejected(self):
        for value in (0, 65, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                refresh_agent_contexts(output_path=self.output, max_files=value, registry_path=self.project_registry)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
