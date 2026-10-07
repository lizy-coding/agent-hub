"""Public capability analysis uses bounded, typed, query-relevant evidence."""

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from agent_hub.capability.analyzer import CapabilityAnalyzer
from agent_hub.context.resolver import ContextLimits
from agent_hub.schemas.models import DevelopmentUnit, Repository, Workspace
from agent_hub.workspace.config import WorkspaceConfig


class CapabilityEvidenceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        registry = self.root / "registry.json"
        unit = DevelopmentUnit(unit_id="repo:.", repo_id="repo", relative_path=".", unit_type="library/package")
        workspace = Workspace(workspace_root=self.root, allowed_paths=[self.root], excluded_paths=[], registry_path=registry, repositories=[Repository(repo_id="repo", path=self.repo, development_units=[unit])])
        registry.write_text(workspace.model_dump_json(), encoding="utf-8")
        self.config = WorkspaceConfig(workspace_root=self.root, registry_path=registry, registry_storage_path=registry)
        self.analyzer = CapabilityAnalyzer(self.config)

    def write(self, relative, text):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def analyze(self, query, paths, **kwargs):
        with ExitStack() as stack:
            for target in ("agent_hub.context.resolver.os.walk", "pathlib.Path.glob", "pathlib.Path.rglob"):
                stack.enter_context(patch(target, side_effect=AssertionError("recursive discovery is prohibited")))
            return self.analyzer.analyze_capabilities(query, "repo", candidate_paths=paths, **kwargs)

    def test_same_basename_has_unique_repository_relative_identity(self):
        paths = ["lib/a/parser.dart", "lib/b/parser.dart"]
        for relative in paths:
            self.write(relative, "class Parser { int parse(String value) => 0; }\n")
        analysis = self.analyze("parser", paths)
        self.assertEqual({node.capability_id for node in analysis.capabilities}, {f"capability:repo:{relative}" for relative in paths})

    def test_guidance_and_config_are_context_evidence_without_business_nodes(self):
        controls = ["AGENTS.md", "lib/AGENTS.md", "AI_ANALYSIS.md", "lib/AI_ANALYSIS.md", "README.md", "pubspec.yaml", "contract.json", "pubspec.lock", "settings.gradle.kts"]
        for relative in controls:
            self.write(relative, "native ffi MethodChannel controller parser Widget service pipeline\n")
        analysis = self.analyze("native parser", controls)
        self.assertEqual(analysis.capabilities, [])
        self.assertEqual(analysis.extraction_candidates, [])
        self.assertEqual(set(analysis.context_ref["evidence_kinds"]), set(controls))
        self.assertEqual(analysis.context_ref["evidence_kinds"]["AGENTS.md"], "guidance")
        self.assertEqual(analysis.context_ref["evidence_kinds"]["pubspec.yaml"], "configuration")

    def test_suffix_and_current_platform_do_not_imply_ffi_coupling(self):
        self.write("lib/model.dart", "class Model { String suffix = ''; String currentPlatform = 'native ffi platform'; }\n")
        analysis = self.analyze("model", ["lib/model.dart"])
        node = analysis.capabilities[0]
        self.assertEqual(node.coupling.platform, "NONE")
        self.assertEqual(node.ownership, "shared_core")

    def test_real_ffi_import_and_api_are_platform_evidence(self):
        self.write("lib/bindings.dart", "import 'dart:ffi' as ffi;\nclass Bindings { final ffi.DynamicLibrary library; Bindings(this.library); }\n")
        node = self.analyze("bindings", ["lib/bindings.dart"]).capabilities[0]
        self.assertEqual(node.coupling.platform, "HIGH")
        self.assertEqual(node.ownership, "platform_plugin")

    def test_import_shaped_strings_and_comments_are_not_native_evidence(self):
        self.write("lib/parser.dart", '''class Parser { String example = "import 'dart:ffi';"; }\n// DynamicLibrary MethodChannel\n''')
        node = self.analyze("parser", ["lib/parser.dart"]).capabilities[0]
        self.assertEqual(node.coupling.platform, "NONE")
        self.assertEqual(node.ownership, "shared_core")

    def test_executable_cli_and_ide_process_adapter_are_adapters(self):
        self.write("bin/scan.dart", "import 'package:args/command_runner.dart';\nclass ScanCommand extends Command<int> { int run() { stdout.writeln(argResults); return 0; } }\n")
        self.write("idea/src/ScanAction.kt", "import com.intellij.openapi.actionSystem.AnAction\nclass ScanAction: AnAction() { fun run() { val process = ProcessBuilder(\"scanner\", \"--json\").start() } }\n")
        nodes = self.analyze("scan", ["bin/scan.dart", "idea/src/ScanAction.kt"]).capabilities
        self.assertEqual({node.ownership for node in nodes}, {"adapter"})

    def test_file_ownership_is_stable_but_unmatched_query_abstains(self):
        self.write("lib/parser.dart", "class Parser { int parse(String text) => 0; }\n")
        matched = self.analyze("parser", ["lib/parser.dart"])
        unmatched = self.analyze("unrelatedxyz", ["lib/parser.dart"])
        self.assertEqual(matched.capabilities[0].ownership, unmatched.capabilities[0].ownership)
        self.assertEqual(matched.extraction_assessments[0].decision, "NEW_SHARED_CORE_CANDIDATE")
        self.assertEqual(unmatched.extraction_assessments[0].decision, "NOT_ENOUGH_EVIDENCE")
        self.assertEqual(unmatched.extraction_candidates, [])
        self.assertFalse(unmatched.context_ref["query_relevance"]["lib/parser.dart"]["matched"])
        self.assertTrue(any("query" in unknown.lower() for unknown in unmatched.unknowns))

    def test_query_relevance_remains_when_symbol_budget_is_zero(self):
        self.write("lib/parser.dart", "class Parser { int parse(String text) => 0; }\n")
        analysis = self.analyze("parser", ["lib/parser.dart"], limits=ContextLimits(max_files=1, max_symbols=0))
        self.assertEqual(analysis.capabilities[0].symbols, [])
        self.assertTrue(analysis.context_ref["query_relevance"]["lib/parser.dart"]["matched"])
        self.assertEqual(analysis.extraction_assessments[0].decision, "NEW_SHARED_CORE_CANDIDATE")

    def test_ui_leaf_and_application_orchestration_keep_their_ownership(self):
        self.write("lib/layer.dart", "class GpuLayer extends StatelessWidget { Widget build() => CustomPaint(); }\n")
        self.write("lib/session.dart", "class SessionController { final Service service; final Pipeline pipeline; final Repository repository; }\n")
        analysis = self.analyze("layer session", ["lib/layer.dart", "lib/session.dart"])
        self.assertEqual({node.ownership for node in analysis.capabilities}, {"ui_only", "application_orchestration"})
        self.assertEqual(analysis.extraction_candidates, [])

    def test_frozen_export_uses_snapshot_and_exact_relative_export_target(self):
        paths = ["lib/a/scaffold.dart", "lib/b/scaffold.dart", "lib/repo.dart"]
        text = "class ScaffoldView extends StatelessWidget { final Widget content; Widget build() => Scaffold(body: content); }\n"
        snapshot = {paths[0]: text, paths[1]: text, paths[2]: "export 'a/scaffold.dart';\n"}
        for path, value in snapshot.items():
            self.write(path, value)
        self.write("lib/repo.dart", "export 'b/scaffold.dart';\n")
        original = Path.read_text

        def reject_source_reads(path, *args, **kwargs):
            if self.repo in path.parents:
                raise AssertionError(f"Frozen evidence reread from disk: {path}")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", new=reject_source_reads):
            analysis = self.analyze("scaffold", paths, source_texts=snapshot)
        ownership = {node.files[0]: node.ownership for node in analysis.capabilities}
        self.assertEqual(ownership["repo/lib/a/scaffold.dart"], "reusable_capability")
        self.assertEqual(ownership["repo/lib/b/scaffold.dart"], "ui_only")

    def test_snapshot_mapping_is_copied_before_resolver_consumption(self):
        self.write("lib/parser.dart", "class Parser {}\n")
        snapshot = {"lib/parser.dart": "class Parser {}\n"}
        original = self.analyzer.resolver.resolve_context

        def mutate_external(*args, **kwargs):
            result = original(*args, **kwargs)
            snapshot["lib/parser.dart"] = "class Widget extends StatelessWidget {}\n"
            return result

        with patch.object(self.analyzer.resolver, "resolve_context", side_effect=mutate_external):
            analysis = self.analyze("parser", ["lib/parser.dart"], source_texts=snapshot)
        self.assertEqual(analysis.capabilities[0].ownership, "shared_core")
        self.assertTrue(analysis.context_ref["query_relevance"]["lib/parser.dart"]["matched"])

    def test_export_shaped_string_does_not_make_source_public(self):
        self.write("lib/view.dart", "class View extends StatelessWidget { final Widget content; Widget build() => Scaffold(body: content); }\n")
        self.write("lib/repo.dart", '''const example = "export 'view.dart';";\n''')
        node = next(node for node in self.analyze("view", ["lib/view.dart", "lib/repo.dart"]).capabilities if node.files == ["repo/lib/view.dart"])
        self.assertEqual(node.ownership, "ui_only")

    def test_symbol_budget_is_shared_across_source_nodes(self):
        paths = ["lib/a/parser.dart", "lib/b/parser.dart"]
        for relative in paths:
            self.write(relative, "class Parser {}\nParser createParser() => Parser();\n")
        analysis = self.analyze("parser", paths, limits=ContextLimits(max_files=2, max_symbols=1))
        self.assertEqual(sum(len(node.symbols) for node in analysis.capabilities), 1)
        self.assertEqual(analysis.metrics["query_matched_capabilities"], 2)

    def test_script_kind_is_explicit_and_no_actionable_decision_is_overcounted(self):
        self.write("tool/scan.sh", "#!/bin/sh\nexec scanner --json\n")
        analysis = self.analyze("scan", ["tool/scan.sh"])
        self.assertEqual(analysis.context_ref["evidence_kinds"]["tool/scan.sh"], "script")
        self.assertEqual(analysis.capabilities[0].label, "script_evidence")
        self.assertEqual(analysis.extraction_candidates, [])


if __name__ == "__main__":
    unittest.main()
