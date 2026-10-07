"""Query evidence and frozen graph inputs stay useful within intake limits."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from agent_hub.context.resolver import terms
from agent_hub.graphs.capability_analysis import build_capability_analysis_graph
from agent_hub.graphs.context_analysis import build_context_analysis_graph
from agent_hub.schemas.models import DevelopmentUnit, Repository, Workspace
from agent_hub.workspace.config import WorkspaceConfig


class QueryEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.cache = self.workspace / "registry.json"
        unit = DevelopmentUnit(unit_id="repo:.", repo_id="repo", relative_path=".", unit_type="library/package")
        self.cache.write_text(Workspace(workspace_root=self.workspace, allowed_paths=[self.workspace], excluded_paths=[], registry_path=self.cache, repositories=[Repository(repo_id="repo", path=self.repo, development_units=[unit])]).model_dump_json(), encoding="utf-8")
        self.config = WorkspaceConfig(workspace_root=self.workspace, allowed_paths=[self.workspace], registry_path=self.cache, registry_storage_path=self.cache)

    def put(self, relative, content):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def state(self, requirement, paths, **extra):
        return {"requirement": requirement, "target_repository": "repo", "candidate_paths": paths, "limits": {"max_files": 24, "max_symbols": 80}, **extra}

    def guarded(self, forbid_reads=False):
        stack = ExitStack()
        for target in ("os.walk", "pathlib.Path.glob", "pathlib.Path.rglob"):
            stack.enter_context(patch(target, side_effect=AssertionError("recursive discovery is prohibited")))
        if forbid_reads:
            original = Path.read_text

            def read(path, *args, **kwargs):
                if self.repo in path.parents:
                    raise AssertionError("frozen source must not be re-read")
                return original(path, *args, **kwargs)

            stack.enter_context(patch.object(Path, "read_text", new=read))
        return stack

    def context(self, state):
        return build_context_analysis_graph(self.config).invoke(state)["context_package"]

    def test_pure_chinese_queries_match_real_identifier_tokens(self):
        fixtures = [
            ("主题令牌", "lib/theme.dart", "class AppThemeTokens {}\n", {"theme", "token", "tokens"}),
            ("蓝牙连接", "lib/wireless.dart", "class BleConnection {}\n", {"ble", "connection"}),
            ("解析模型", "lib/reader.dart", "class ToolpathParserModel {}\n", {"parser", "model"}),
            ("命令行标准输出", "bin/tool.dart", "class ScanCommand {}\nvoid output() => stdout.writeln('ok');\n", {"command", "stdout"}),
        ]
        for query, path, content, expected in fixtures:
            self.put(path, content)
            with self.subTest(query=query), self.guarded():
                context = self.context(self.state(query, [path]))
            self.assertTrue(expected.intersection(symbol["name"] for symbol in context["symbols"]))
            self.assertEqual(context["files"][0]["relevance"], "explicit_candidate_query_match")

    def test_camel_case_snake_case_split_and_generic_words_do_not_match(self):
        self.put("lib/logic.dart", "class ThemeController {}\nfinal ble_session = BleConnection();\n")
        self.assertTrue({"theme", "controller", "ble", "session"}.issubset(terms("ThemeController ble_session and app")))
        self.assertNotIn("and", terms("ThemeController and app"))
        self.assertNotIn("app", terms("ThemeController and app"))
        self.assertIn("contract", terms("agent rule contract"))
        self.assertIn("rule", terms("agent rule contract"))
        with self.guarded():
            context = self.context(self.state("theme connection", ["lib/logic.dart"]))
        self.assertEqual({symbol["name"] for symbol in context["symbols"]}, {"theme", "connection"})

    def test_identifier_substrings_and_paths_cannot_fabricate_query_evidence(self):
        self.put("lib/ffi_theme_parser.dart", "final suffix = 'plain';\n")
        with self.guarded():
            context = self.context(self.state("ffi theme parser", ["lib/ffi_theme_parser.dart"]))
        self.assertEqual(context["symbols"], [])
        self.assertEqual(context["files"][0]["relevance"], "explicit_candidate_no_query_match")

    def test_relevant_source_and_configuration_share_symbols_before_long_guides(self):
        self.put("AGENTS.md", "theme release contract\n" * 120)
        self.put("lib/alpha.dart", "class ThemeController {}\n" * 120)
        self.put("lib/beta.dart", "class ThemeTokens {}\n")
        self.put(".github/workflows/ship.yml", "name: release\n")
        self.put("tool/package.sh", "run_release() { true; }\n")
        paths = ["AGENTS.md", "lib/alpha.dart", "lib/beta.dart", ".github/workflows/ship.yml", "tool/package.sh"]
        with self.guarded():
            context = self.context(self.state("theme release", paths))
        seen = {Path(symbol["file"]).relative_to(self.repo).as_posix() for symbol in context["symbols"]}
        self.assertEqual(seen, set(paths))
        self.assertEqual(len(context["symbols"]), 80)
        first = Path(context["symbols"][0]["file"]).relative_to(self.repo).as_posix()
        self.assertNotEqual(first, "AGENTS.md")
        targets = [rule for rule in context["rules"] if rule["applies_to"] == "repo:lib/beta.dart"]
        self.assertEqual([rule["path"] for rule in targets], ["repo/AGENTS.md"])

    def test_small_symbol_budget_prefers_source_and_config_over_guide_mentions(self):
        self.put("AGENTS.md", "release\n" * 100)
        self.put("tool/package.sh", "run_release() { true; }\n")
        with self.guarded():
            context = self.context(self.state("发布", ["AGENTS.md", "tool/package.sh"], limits={"max_files": 24, "max_symbols": 1}))
        self.assertEqual(context["symbols"][0]["file"], str(self.repo / "tool/package.sh"))

    def test_frozen_sources_keep_original_symbols_capabilities_and_plan(self):
        texts = {
            "AGENTS.md": "Parser rules.\n",
            "lib/parser.dart": "class FrozenParser { Object parse(String input) => input; }\n",
            "REFACTOR_PLAN.md": json.dumps({"work_queue": [{"id": "frozen-plan", "status": "pending", "targets": ["lib/parser.dart"]}]}),
        }
        for path, text in texts.items():
            self.put(path, text)
        self.put("lib/parser.dart", "class LiveWidget extends StatelessWidget {}\n")
        self.put("REFACTOR_PLAN.md", json.dumps({"work_queue": []}))
        state = self.state("解析", list(texts), source_texts=texts)
        with self.guarded(forbid_reads=True):
            context = self.context(state)
            capabilities = build_capability_analysis_graph(self.config).invoke(state)["capability_analysis"]
        self.assertTrue(any(symbol["name"] in {"parser", "parse"} and symbol["file"].endswith("parser.dart") for symbol in context["symbols"]))
        source = next(node for node in capabilities["capabilities"] if node["files"] == ["repo/lib/parser.dart"])
        self.assertEqual(source["ownership"], "shared_core")
        self.assertEqual(context["planned_capabilities"], [{"task_id": "frozen-plan", "targets": ["lib/parser.dart"], "status": "pending"}])

    def test_frozen_input_is_validated_before_source_reads_in_both_graphs(self):
        self.put("lib/parser.dart", "class Parser {}\n")
        bad = [
            {}, {"lib/parser.dart": 1}, {Path("lib/parser.dart"): "class Parser {}"},
            {"lib/parser.dart": "class Parser {}", "other.dart": "class Other {}"},
            {"lib/parser.dart": "class Parser {}", "../outside.dart": "class Other {}"},
            {"lib/parser.dart": "class Parser {}", "/absolute.dart": "class Other {}"},
        ]
        for texts in bad:
            for build in (build_context_analysis_graph, build_capability_analysis_graph):
                with self.subTest(texts=texts, build=build.__name__), self.guarded(forbid_reads=True), self.assertRaises(ValueError):
                    build(self.config).invoke(self.state("parser", ["lib/parser.dart"], source_texts=texts))

    def test_freeze_does_not_read_unselected_or_downgrade_missing_override(self):
        texts = {"AGENTS.md": "ordinary rule", "lib/parser.dart": "class Parser {}\n"}
        for path, text in texts.items():
            self.put(path, text)
        self.put("AGENTS.override.md", "active rule")
        with self.guarded(forbid_reads=True):
            context = self.context(self.state("parser", list(texts), source_texts=texts))
        self.assertEqual(context["rules"], [])
        self.assertTrue(any(item["subject"] == "repo/AGENTS.override.md" and "not selected" in item["reason"] for item in context["unknowns"]))

    def test_frozen_snapshot_cannot_activate_an_unselected_plan(self):
        texts = {"lib/parser.dart": "class Parser {}\n", "REFACTOR_PLAN.md": json.dumps({"work_queue": [{"id": "outside-budget", "status": "pending", "targets": ["lib/parser.dart"]}]})}
        for path, text in texts.items():
            self.put(path, text)
        with self.guarded(forbid_reads=True):
            context = self.context(self.state("parser", list(texts), source_texts=texts, limits={"max_files": 1, "max_symbols": 80}))
        self.assertEqual(context["planned_capabilities"], [])
        self.assertEqual([item["relative_path"] for item in context["files"]], ["repo/lib/parser.dart"])

    def test_frozen_input_requires_an_explicit_intake(self):
        self.put("lib/parser.dart", "class Parser {}\n")
        with self.guarded(forbid_reads=True), self.assertRaises(ValueError):
            self.context({"requirement": "parser", "target_repository": "repo", "source_texts": {"lib/parser.dart": "class Parser {}"}})

    def test_relevance_remains_known_when_symbol_budget_is_zero(self):
        self.put("lib/theme.dart", "class ThemeController {}\n")
        with self.guarded():
            context = self.context(self.state("主题", ["lib/theme.dart"], limits={"max_files": 24, "max_symbols": 0}))
        self.assertEqual(context["symbols"], [])
        self.assertEqual(context["files"][0]["relevance"], "explicit_candidate_query_match")


if __name__ == "__main__":
    unittest.main()
