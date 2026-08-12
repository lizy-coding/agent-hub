import json
import tempfile
import unittest
from pathlib import Path

from agent_hub.benchmark.runner import ResumableShadowBenchmark


class _Runner:
    def __init__(self, root):
        self.scenario_path = root / "shadow_cases" / "cases.json"
        self.config = type("Config", (), {"registry_path": root / "registry.json"})()
        self.calls = []
        (root / "shadow_cases").mkdir(parents=True)
        (root / "architecture_goldens").mkdir()
        self.scenario_path.write_text(json.dumps([{"id": "SHADOW_001", "expected": {}}]))
        (root / "architecture_goldens" / "candidates.json").write_text(json.dumps([{"id": "GOLDEN_001"}]))
        (root / "architecture_goldens" / "review-decisions.json").write_text(json.dumps([{"id": "GOLDEN_001", "state": "approved", "accepted_ownership": "unknown"}]))
        (root / "registry.json").write_text("{}")
    def load_scenarios(self): return json.loads(self.scenario_path.read_text())
    def load_reviewed_goldens(self): return [({"id": "GOLDEN_001"}, {"id": "GOLDEN_001", "accepted_ownership": "unknown"})]
    def run_shadow_case(self, item):
        self.calls.append(item["id"])
        return {"id": item["id"], "passed": True, "repository_precision": 1, "repository_recall": 1, "evidence_coverage": 1, "rule_coverage": 1, "unknown_preservation": 1, "false_positive": 0, "metrics": {}, "failures": []}
    def score_golden_case(self, candidate, truth):
        self.calls.append(truth["id"])
        return {"id": truth["id"], "ownership_match": True, "extraction_match": True, "target_scored": False, "target_match": None, "unsupported_promotion": False, "metrics": {}, "failures": []}


class ResumableBenchmarkTest(unittest.TestCase):
    def test_resume_skips_valid_completed_case_and_publishes_only_complete_run(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = _Runner(root)
            store = ResumableShadowBenchmark(runner)
            # Identity construction is replaced only for this synthetic store;
            # production identity remains source/truth/config based.
            store.identity = lambda: {"stage": "P5.6.1", "source_revision": "x", "analyzer_source_hash": "a", "resolver_source_hash": "r", "benchmark_source_hash": "b", "benchmark_config_hash": "c", "candidates_hash": "d", "review_decisions_hash": "e", "registry_snapshot_identity": "f", "case_ids": ["SHADOW_001", "GOLDEN_001"]}
            result = store.run()
            self.assertTrue(result["complete"])
            self.assertEqual(runner.calls, ["SHADOW_001", "GOLDEN_001"])
            old_result = (root / "shadow-results.json").read_text()
            runner.calls.clear()
            resumed = store.run()
            self.assertTrue(resumed["complete"])
            self.assertEqual(resumed["executed"], 0)
            self.assertEqual(resumed["skipped"], 2)
            self.assertEqual(runner.calls, [])
            self.assertEqual(json.loads((root / "shadow-results.json").read_text())["run_id"], json.loads(old_result)["run_id"])
            case = json.loads(next((root / "runs").glob("*/cases/SHADOW_001.json")).read_text())
            self.assertEqual(case["status"], "COMPLETE")
            self.assertTrue(case["result_hash"])
