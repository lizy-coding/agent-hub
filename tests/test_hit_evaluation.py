"""Public fixture accounting for bounded evaluation; no production source scan."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.evaluate_agent_context_hits import aggregate, evaluate, expected_rule_pairs, freeze_daily_pool, score_case
from agent_hub.capability.decisions import ACTIONABLE_DECISIONS


class HitEvaluationTest(unittest.TestCase):
    def setUp(self):
        self.case = {
            "id": "fixture", "project_id": "fixture-project", "negative": False,
            "query_zh": "解析输入", "query_en": "parse input",
            "must_hit": ["AGENTS.md", "lib/parser.dart", "lib/missing.dart"],
            "rule_entries": ["AGENTS.md", "lib/AGENTS.md"],
            "ownership_expectation": None, "known_irrelevant": [],
        }
        self.observation = {
            "project_id": "fixture-project", "repository_id": "fixture_repo", "repository_root": "/fixture",
            "status": "REFRESHED", "selected_files": [{"path": "AGENTS.md"}, {"path": "lib/parser.dart"}],
            "context_package": {
                "files": [{"relative_path": "AGENTS.md"}, {"relative_path": "lib/parser.dart"}],
                "symbols": [{"file": "/fixture/lib/parser.dart"}],
                "rules": [{"path": "AGENTS.md", "applies_to": "fixture_repo:AGENTS.md"}, {"path": "lib/AGENTS.md", "applies_to": "fixture_repo:lib/AGENTS.md"}],
                "unknowns": [],
            },
            "capability_analysis": {"capabilities": [], "extraction_assessments": [], "context_ref": {}},
        }

    def test_rule_pairs_keep_missing_sources_and_exclude_guidance_self(self):
        with patch.object(Path, "exists", side_effect=AssertionError("goldens must not drop absent targets")), patch.object(Path, "is_file", side_effect=AssertionError("goldens must not inspect production sources")):
            wanted = expected_rule_pairs(self.case)
        self.assertEqual(wanted, {
            ("AGENTS.md", "lib/parser.dart"), ("AGENTS.md", "lib/missing.dart"),
            ("lib/AGENTS.md", "lib/parser.dart"), ("lib/AGENTS.md", "lib/missing.dart"),
        })
        row = score_case(self.case, "zh", self.observation)
        self.assertEqual(row["covered_rules"], 2)
        self.assertEqual(row["expected_rules"], 2)
        self.assertEqual(row["expected_rule_target_pairs"], 4)
        self.assertEqual(row["covered_rule_target_pairs"], 0)
        self.assertEqual(row["missing_files"], ["lib/missing.dart"])

    def test_claimed_pair_for_missing_target_cannot_be_a_hit(self):
        self.observation["context_package"]["rules"].extend([
            {"path": "AGENTS.md", "applies_to": "fixture_repo:lib/parser.dart"},
            {"path": "AGENTS.md", "applies_to": "fixture_repo:lib/missing.dart"},
        ])
        row = score_case(self.case, "en", self.observation)
        self.assertEqual(row["covered_rule_target_pairs"], 1)
        self.assertEqual(row["expected_rule_target_pairs"], 4)
        self.assertIn({"rule": "AGENTS.md", "target": "lib/missing.dart"}, row["missing_rule_target_pairs"])

    def test_actionable_count_uses_actual_decisions_and_excludes_old_names(self):
        decisions = ["KEEP_IN_APPLICATION", "ADAPTER_ONLY", "NOT_ENOUGH_EVIDENCE", "UNKNOWN", "EXTEND_EXISTING_UNIT", "MOVE_TO_EXISTING_UNIT", "NEW_SHARED_CORE_CANDIDATE", "NEW_PLUGIN_CANDIDATE", "REUSE_UNIT", "REUSE_WITH_ADAPTER", "NEW_PACKAGE_CANDIDATE"]
        self.observation["capability_analysis"]["extraction_assessments"] = [{"capability_id": "parser", "decision": decision} for decision in decisions]
        self.observation["capability_analysis"]["capabilities"] = [{"capability_id": "parser", "files": ["lib/parser.dart"], "ownership": "shared_core", "confidence": "HIGH"}]
        self.observation["capability_analysis"]["context_ref"] = {"query_relevance": {"lib/parser.dart": {"matched": True}}}
        row = score_case(self.case, "en", self.observation)
        self.assertEqual(set(ACTIONABLE_DECISIONS), {"EXTEND_EXISTING_UNIT", "MOVE_TO_EXISTING_UNIT", "NEW_SHARED_CORE_CANDIDATE", "NEW_PLUGIN_CANDIDATE"})
        self.assertEqual(row["query_unfiltered_recommendations"], 4)
        self.assertEqual(row["query_linked_recommendations"], 4)
        self.assertEqual(row["query_unlinked_recommendations"], 0)

    def test_node_ids_and_markdown_are_counted_before_path_map_collapses(self):
        self.observation["capability_analysis"]["capabilities"] = [
            {"capability_id": "duplicate", "files": ["lib/a.dart"], "ownership": "shared_core", "confidence": "HIGH"},
            {"capability_id": "duplicate", "files": ["lib/b.dart"], "ownership": "shared_core", "confidence": "HIGH"},
            {"capability_id": "guide", "files": ["AGENTS.md"], "ownership": "adapter", "confidence": "HIGH"},
        ]
        row = score_case(self.case, "zh", self.observation)
        self.assertEqual(row["capability_nodes"], 3)
        self.assertEqual(row["unique_node_ids"], 2)
        self.assertEqual(row["duplicate_node_ids"], {"duplicate": 2})
        self.assertEqual(row["markdown_nodes_with_high_ownership"], 1)

    def test_evidence_types_include_config_and_missing_source_denominators(self):
        self.case["must_hit"].extend(["pubspec.yaml", "AI_PROJECT_CONTEXT.md", "tool/build.sh"])
        row = score_case(self.case, "en", self.observation)
        self.assertEqual(row["evidence_by_kind"]["source"]["expected"], 2)
        self.assertEqual(row["evidence_by_kind"]["source"]["covered"], 1)
        self.assertEqual(row["evidence_by_kind"]["configuration"]["expected"], 2)
        self.assertEqual(row["evidence_by_kind"]["guidance"]["expected"], 1)
        self.assertEqual(row["evidence_by_kind"]["script"]["expected"], 1)
        self.assertIn(("AGENTS.md", "pubspec.yaml"), expected_rule_pairs(self.case))
        self.assertNotIn(("AGENTS.md", "AGENTS.md"), expected_rule_pairs(self.case))

    def test_negative_proxy_is_not_semantic_false_claim_scoring(self):
        self.case["negative"] = True
        row = score_case(self.case, "zh", self.observation)
        self.assertTrue(row["query_abstention"]["no_actionable_recommendation"])
        self.assertFalse(row["query_abstention"]["relevance_available"])
        self.assertEqual(row["negative_semantic_support_claim"], "NOT_SCORED_GRAPHS_RETURN_ANCHORS_NOT_SUPPORT_CLAIMS")
        summary = aggregate([row])["zh"]
        self.assertEqual(summary["negative_queries_without_actionable_recommendations"], 1)
        self.assertEqual(summary["files"]["total"], 0)

    def test_task_evaluation_passes_query_only_and_preserves_run(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            goldens, output = root / "goldens.json", root / "run"
            goldens.write_text(json.dumps({"cases": [self.case]}))
            with patch("scripts.evaluate_agent_context_hits.refresh_agent_contexts", return_value={"projects": [self.observation]}) as refresh:
                result = evaluate(goldens, output)
            self.assertEqual(refresh.call_count, 2)
            for call, language in zip(refresh.call_args_list, ("zh", "en")):
                self.assertEqual(call.args, (["fixture-project"],))
                self.assertEqual(call.kwargs["requirement"], self.case[f"query_{language}"])
                self.assertEqual(call.kwargs["max_files"], 24)
                self.assertNotIn("candidate_paths", call.kwargs)
                self.assertNotIn("must_hit", call.kwargs)
            self.assertEqual(result["evaluation_mode"], "task")
            self.assertFalse(result["golden_candidate_injection"])
            self.assertEqual(result["precision"]["status"], "NOT_SCORED")
            prior = (output / "results.json").read_bytes()
            with self.assertRaises(FileExistsError):
                evaluate(goldens, output)
            self.assertEqual((output / "results.json").read_bytes(), prior)

    def test_evaluation_rejects_business_checkout_output_before_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            goldens = Path(raw) / "goldens.json"
            goldens.write_text(json.dumps({"cases": [self.case]}))
            with patch("scripts.evaluate_agent_context_hits.refresh_agent_contexts") as refresh:
                with self.assertRaisesRegex(ValueError, "inside Agent Hub"):
                    evaluate(goldens, Path("/fixture-business-checkout/evaluation"))
            refresh.assert_not_called()

    def test_frozen_daily_texts_reject_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "fixture.dart"
            source.write_text("class Fixture {}\n")
            observation = {"repository_root": str(root), "selected_files": [{"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}
            self.assertEqual(freeze_daily_pool(observation), {"fixture.dart": "class Fixture {}\n"})
            source.write_text("class Changed {}\n")
            with self.assertRaisesRegex(ValueError, "INVALID_EVIDENCE"):
                freeze_daily_pool(observation)


if __name__ == "__main__":
    unittest.main()
