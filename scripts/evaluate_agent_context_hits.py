#!/usr/bin/env python3
"""Evaluate the current bounded graphs against independent file goldens."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_hub.graphs.capability_analysis import build_capability_analysis_graph
from agent_hub.graphs.context_analysis import build_context_analysis_graph
from agent_hub.projects.agent_context import _target_repository, _workspace_config, refresh_agent_contexts
from agent_hub.projects.decomposition_config import load_decomposition_project
from agent_hub.schemas.models import Workspace
from agent_hub.workspace.config import WorkspaceConfig

SOURCE_SUFFIXES = {".dart", ".kt", ".java", ".swift", ".py", ".c", ".cpp", ".h", ".hpp", ".mm", ".js", ".ts"}


def ratio(hit: int, total: int):
    return hit / total if total else None


def evaluate(goldens: Path, output: Path, max_files: int = 24) -> dict:
    truth = json.loads(goldens.read_text())
    output.mkdir(parents=True, exist_ok=True)
    with ExitStack() as guards:
        for name in ("os.walk", "pathlib.Path.glob", "pathlib.Path.rglob", "agent_hub.projects.discovery.discover", "agent_hub.projects.workspace_registry.WorkspaceRegistry.refresh"):
            guards.enter_context(patch(name, side_effect=AssertionError(f"Unbounded operation forbidden: {name}")))
        intake = refresh_agent_contexts(output_path=output / "intake.json", max_files=max_files)
        projects = {p["project_id"]: p for p in intake["projects"]}
        registry = json.loads((ROOT / "workspace/projects.json").read_text())
        rows = []
        for project_id, observation in projects.items():
            root = Path(observation["repository_root"])
            project = load_decomposition_project(project_id)
            config = _workspace_config(registry["projects"][project_id])
            repository, _, _ = _target_repository(config, root, project.primary_repository_id)
            pool = [item["path"] for item in observation["selected_files"]]
            with tempfile.TemporaryDirectory(prefix="agent-hit-", dir="/private/tmp") as raw:
                storage = Path(raw) / "registry.json"
                storage.write_text(Workspace(workspace_root=root, allowed_paths=[root], excluded_paths=[], registry_path=storage, repositories=[repository]).model_dump_json())
                bounded = WorkspaceConfig(workspace_root=root, allowed_paths=[root], registry_path=storage, registry_storage_path=storage)
                context_graph = build_context_analysis_graph(bounded)
                capability_graph = build_capability_analysis_graph(bounded)
                for case in [c for c in truth["cases"] if c["project_id"] == project_id]:
                    for language in ("zh", "en"):
                        state = {"requirement": case[f"query_{language}"], "target_repository": project.primary_repository_id, "candidate_paths": pool, "limits": {"max_files": max_files, "max_symbols": 80, "max_dependency_depth": 0}}
                        context = context_graph.invoke(state)["context_package"]
                        analysis = capability_graph.invoke(state)["capability_analysis"]
                        returned = {f["relative_path"] for f in context["files"]}
                        symbol_files = {Path(s["file"]).relative_to(root).as_posix() for s in context["symbols"]}
                        rules = {r["path"] for r in context["rules"]}
                        expected = set(case["must_hit"])
                        expected_rules = set(case["rule_entries"])
                        nodes = {path: n for n in analysis["capabilities"] for path in n["files"]}
                        owner = case["ownership_expectation"]
                        predicted_owner = nodes.get(owner["path"], {}).get("ownership") if owner else None
                        markdown = [n for path, n in nodes.items() if Path(path).suffix == ".md"]
                        actions = [a for a in analysis["extraction_assessments"] if a["decision"] in {"REUSE_UNIT", "REUSE_WITH_ADAPTER", "NEW_PACKAGE_CANDIDATE", "NEW_PLUGIN_CANDIDATE"}]
                        unsupported_files = [path for path in returned if path not in pool]
                        rows.append({
                            "case_id": case["id"], "project_id": project_id, "language": language, "negative": case["negative"],
                            "pool_files": len(pool), "returned_files": len(returned), "intake_retention": ratio(len(returned & set(pool)), len(pool)),
                            "expected_files": len(expected), "covered_files": len(expected & returned), "missing_files": sorted(expected - returned),
                            "symbol_supported_files": len(expected & symbol_files), "symbol_missing_files": sorted(expected - symbol_files),
                            "covered_files_without_symbols": sorted((expected & returned) - symbol_files),
                            "expected_rules": len(expected_rules), "covered_rules": len(expected_rules & rules), "missing_rules": sorted(expected_rules - rules),
                            "symbols": len(context["symbols"]), "symbol_budget_saturated": len(context["symbols"]) == 80,
                            "ownership_expected": owner["classification"] if owner else None, "ownership_predicted": predicted_owner,
                            "ownership_correct": predicted_owner == owner["classification"] if owner else None,
                            "markdown_nodes": len(markdown), "markdown_nodes_with_high_ownership": sum(n["confidence"] == "HIGH" and n["ownership"] != "unknown" for n in markdown),
                            "unknown_context_count": len(context["unknowns"]), "query_unfiltered_recommendations": len(actions),
                            "negative_semantic_support_claim": "NOT_SCORED_GRAPHS_RETURN_ANCHORS_NOT_SUPPORT_CLAIMS" if case["negative"] else None,
                            "out_of_pool_files": unsupported_files,
                            "known_irrelevant_symbol_hits": sorted(set(case["known_irrelevant"]) & symbol_files),
                            "node_ownership": {path: {"ownership": n["ownership"], "confidence": n["confidence"]} for path, n in nodes.items()},
                        })
        aggregates = {}
        for language in ("zh", "en"):
            positives = [r for r in rows if r["language"] == language and not r["negative"]]
            labelled = [r for r in positives if r["ownership_expected"] is not None]
            with_prediction = [r for r in labelled if r["ownership_predicted"] is not None]
            aggregates[language] = {
                "positive_cases": len(positives),
                "files": {"hit": sum(r["covered_files"] for r in positives), "total": sum(r["expected_files"] for r in positives)},
                "symbols": {"hit": sum(r["symbol_supported_files"] for r in positives), "total": sum(r["expected_files"] for r in positives)},
                "conditional_symbols": {"hit": sum(r["symbol_supported_files"] for r in positives), "total": sum(r["covered_files"] for r in positives)},
                "rules": {"hit": sum(r["covered_rules"] for r in positives), "total": sum(r["expected_rules"] for r in positives)},
                "ownership_end_to_end": {"hit": sum(r["ownership_correct"] for r in labelled), "total": len(labelled)},
                "ownership_with_prediction": {"hit": sum(r["ownership_correct"] for r in with_prediction), "total": len(with_prediction)},
                "symbol_budget_saturated_cases": sum(r["symbol_budget_saturated"] for r in positives),
            }
            for value in aggregates[language].values():
                if isinstance(value, dict) and "total" in value:
                    value["rate"] = ratio(value["hit"], value["total"])
        result = {
            "schema": "bounded-agent-hit-evaluation.v1", "generated_at": datetime.now(UTC).isoformat(),
            "no_walk": True, "evaluator_parameter_tuning": False, "max_files": max_files,
            "goldens_sha256": hashlib.sha256(goldens.read_bytes()).hexdigest(),
            "case_semantics_sha256": hashlib.sha256(json.dumps(truth["cases"], ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "code_hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in ("src/agent_hub/context/resolver.py", "src/agent_hub/capability/analyzer.py", "src/agent_hub/projects/agent_context.py")},
            "project_observations": [{k: p[k] for k in ("project_id", "source_sha", "version", "workspace_dirty_paths", "registry_metadata_mode", "metrics")} for p in projects.values()],
            "aggregates": aggregates, "cases": rows,
            "precision": {"status": "NOT_SCORED", "reason": "must_hit is a partial positive set, not a complete relevance judgement"},
            "limitations": truth.get("limitations", []) + ["Symbol-supported file coverage is lexical evidence coverage, not semantic answer accuracy.", "Existing HIGH ownership anchors do not assert support for a negative query.", "The run evaluates current local worktrees and cached unit metadata, not release acceptance."],
        }
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goldens", type=Path, default=ROOT / "benchmarks/agent_context_goldens/cases.json")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/agent_context_runs/20261002-basic")
    parser.add_argument("--max-files", type=int, default=24)
    args = parser.parse_args()
    result = evaluate(args.goldens, args.output, args.max_files)
    print(json.dumps(result["aggregates"], indent=2))
