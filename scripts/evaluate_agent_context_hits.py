#!/usr/bin/env python3
"""Evaluate bounded task intake against independent file and rule-target goldens."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_hub.capability.decisions import ACTIONABLE_DECISIONS
from agent_hub.graphs.capability_analysis import build_capability_analysis_graph
from agent_hub.graphs.context_analysis import build_context_analysis_graph
from agent_hub.projects.agent_context import _target_repository, _workspace_config, refresh_agent_contexts
from agent_hub.projects.decomposition_config import load_decomposition_project
from agent_hub.schemas.models import Workspace
from agent_hub.workspace.config import WorkspaceConfig

SOURCE_SUFFIXES = {".dart", ".kt", ".java", ".swift", ".py", ".c", ".cpp", ".h", ".hpp", ".mm", ".js", ".ts"}
SCRIPT_SUFFIXES = {".sh", ".bash", ".zsh", ".ps1", ".bat"}
CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".xml", ".lock", ".kts", ".gradle", ".iss"}
PROTECTED_RUNS = {"20261002-baseline", "20261002-rules-optimized", "20261002-basic"}


def ratio(hit: int, total: int):
    return hit / total if total else None


def evidence_kind(path: str) -> str:
    """Independent benchmark categories, without consulting source existence."""
    relative = Path(path)
    if relative.name in {"AGENTS.md", "AGENTS.override.md"}:
        return "guidance"
    if relative.name.startswith("AI_") and relative.suffix == ".md":
        return "configuration"
    if relative.suffix in SOURCE_SUFFIXES:
        return "source"
    if relative.suffix in SCRIPT_SUFFIXES:
        return "script"
    if relative.suffix in CONFIG_SUFFIXES:
        return "configuration"
    if relative.suffix == ".md":
        return "guidance"
    return "unsupported"


def expected_rule_pairs(case: dict) -> set[tuple[str, str]]:
    """Keep absent targets in the denominator and exclude guidance self-pairs.

    Goldens can supply explicit pairs. For the immutable original cases, derive
    ancestor pairs from their existing rule entries and required source/config
    paths. No filesystem lookup or graph prediction changes the expectation.
    """
    if "rule_target_pairs" in case:
        values = {(item["rule"], item["target"]) for item in case["rule_target_pairs"]}
    else:
        values = set()
        for guide in case["rule_entries"]:
            parent = Path(guide).parent
            for target in case["must_hit"]:
                if parent == Path(".") or parent in Path(target).parents:
                    values.add((guide, target))
    return {
        (guide, target) for guide, target in values
        if guide != target and Path(target).name not in {"AGENTS.md", "AGENTS.override.md"}
        and evidence_kind(target) in {"source", "script", "configuration"}
    }


def _relative_symbol_files(symbols: list[dict], root: Path) -> set[str]:
    result = set()
    for symbol in symbols:
        path = Path(symbol["file"])
        try:
            result.add(path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix())
        except ValueError:
            continue
    return result


def _rule_pair(rule: dict, repository_id: str) -> tuple[str, str]:
    target = rule.get("applies_to", "")
    prefix = repository_id + ":"
    return rule["path"], target[len(prefix):] if target.startswith(prefix) else target


def score_case(case: dict, language: str, observation: dict, max_symbols: int = 80) -> dict:
    """Score a frozen observation; partial positives never stand in for precision."""
    context = observation.get("context_package", {})
    analysis = observation.get("capability_analysis", {})
    root = Path(observation.get("repository_root", "/unknown"))
    pool = {item["path"] for item in observation.get("selected_files", [])}
    returned = {item["relative_path"] for item in context.get("files", [])}
    symbol_files = _relative_symbol_files(context.get("symbols", []), root)
    rules = {item["path"] for item in context.get("rules", [])}
    expected = set(case["must_hit"])
    expected_rules = set(case["rule_entries"])
    wanted_pairs = expected_rule_pairs(case)
    rule_pairs = {_rule_pair(item, observation.get("repository_id", "")) for item in context.get("rules", [])}
    # A rule claim for a missing target cannot establish applied source coverage.
    supported_pairs = {(guide, target) for guide, target in rule_pairs if target in returned}
    nodes = analysis.get("capabilities", [])
    node_ids = Counter(item["capability_id"] for item in nodes)
    nodes_by_path: dict[str, list[dict]] = {}
    for node in nodes:
        for path in node.get("files", []):
            nodes_by_path.setdefault(path, []).append(node)
    owner = case.get("ownership_expectation")
    ownerships = {node.get("ownership") for node in nodes_by_path.get(owner["path"], [])} if owner else set()
    predicted_owner = next(iter(ownerships)) if len(ownerships) == 1 else None
    markdown = [node for node in nodes if any(Path(path).suffix == ".md" for path in node.get("files", []))]
    actionable = [item for item in analysis.get("extraction_assessments", []) if item.get("decision") in ACTIONABLE_DECISIONS]
    query_relevance = analysis.get("context_ref", {}).get("query_relevance", {})
    matched_paths = {path for path, match in query_relevance.items() if match.get("matched")}
    matched_ids = {node["capability_id"] for node in nodes if set(node.get("files", [])) & matched_paths}
    linked_actions = [item for item in actionable if item.get("capability_id") in matched_ids]
    observed_kinds = analysis.get("context_ref", {}).get("evidence_kinds", {})
    expected_kinds = case.get("evidence_expectations", {})
    kind_scores = {}
    for kind in ("source", "script", "configuration", "guidance", "unsupported"):
        wanted = {path for path in expected if expected_kinds.get(path, evidence_kind(path)) == kind}
        kind_scores[kind] = {
            "expected": len(wanted), "covered": len(wanted & returned),
            "with_symbols": len(wanted & symbol_files), "missing": sorted(wanted - returned),
        }
    return {
        "case_id": case["id"], "project_id": case["project_id"], "language": language, "negative": case["negative"],
        "observation_status": observation.get("status"),
        "pool_files": len(pool), "returned_files": len(returned), "intake_retention": ratio(len(returned & pool), len(pool)),
        "expected_files": len(expected), "covered_files": len(expected & returned), "missing_files": sorted(expected - returned),
        "symbol_supported_files": len(expected & symbol_files), "symbol_missing_files": sorted(expected - symbol_files),
        "covered_files_without_symbols": sorted((expected & returned) - symbol_files),
        "expected_rules": len(expected_rules), "covered_rules": len(expected_rules & rules), "missing_rules": sorted(expected_rules - rules),
        "expected_rule_target_pairs": len(wanted_pairs), "covered_rule_target_pairs": len(wanted_pairs & supported_pairs),
        "missing_rule_target_pairs": [{"rule": guide, "target": target} for guide, target in sorted(wanted_pairs - supported_pairs)],
        "observed_rule_target_pairs": [{"rule": guide, "target": target} for guide, target in sorted(rule_pairs)],
        "symbols": len(context.get("symbols", [])), "symbol_budget_saturated": len(context.get("symbols", [])) == max_symbols,
        "ownership_expected": owner["classification"] if owner else None, "ownership_predicted": predicted_owner,
        "ownership_correct": predicted_owner == owner["classification"] if owner else None,
        "ownership_conflicting_paths": sorted(path for path, values in nodes_by_path.items() if len({node.get("ownership") for node in values}) > 1),
        "capability_nodes": len(nodes), "unique_node_ids": len(node_ids),
        "duplicate_node_ids": {identity: count for identity, count in sorted(node_ids.items()) if count > 1},
        "markdown_nodes": len(markdown), "markdown_nodes_with_high_ownership": sum(node.get("confidence") == "HIGH" and node.get("ownership") != "unknown" for node in markdown),
        "unknown_context_count": len(context.get("unknowns", [])), "query_unfiltered_recommendations": len(actionable),
        "query_linked_recommendations": len(linked_actions), "query_unlinked_recommendations": len(actionable) - len(linked_actions),
        "query_matched_capability_nodes": sum(bool(set(node.get("files", [])) & matched_paths) for node in nodes),
        "query_abstention": {
            "relevance_available": "query_relevance" in analysis.get("context_ref", {}),
            "no_matched_capability": not matched_ids,
            "no_actionable_recommendation": not actionable,
            "matched_evidence_files": len(matched_paths),
            "status": "LEXICAL_AND_DECISION_PROXY_ONLY",
        },
        "evidence_by_kind": kind_scores,
        "returned_evidence_kinds": dict(sorted(Counter(observed_kinds.get(path, evidence_kind(path)) for path in returned).items())),
        "negative_semantic_support_claim": "NOT_SCORED_GRAPHS_RETURN_ANCHORS_NOT_SUPPORT_CLAIMS" if case["negative"] else None,
        "out_of_pool_files": sorted(returned - pool),
        "known_irrelevant_symbol_hits": sorted(set(case.get("known_irrelevant", [])) & symbol_files),
        "node_ownership": {path: {"ownership": values[0].get("ownership"), "confidence": values[0].get("confidence")} for path, values in sorted(nodes_by_path.items())},
    }


def aggregate(rows: list[dict]) -> dict:
    aggregates = {}
    for language in ("zh", "en"):
        language_rows = [row for row in rows if row["language"] == language]
        positives = [row for row in language_rows if not row["negative"]]
        negatives = [row for row in language_rows if row["negative"]]
        labelled = [row for row in positives if row["ownership_expected"] is not None]
        predicted = [row for row in labelled if row["ownership_predicted"] is not None]
        values = {
            "positive_cases": len(positives),
            "files": {"hit": sum(row["covered_files"] for row in positives), "total": sum(row["expected_files"] for row in positives)},
            "symbols": {"hit": sum(row["symbol_supported_files"] for row in positives), "total": sum(row["expected_files"] for row in positives)},
            "conditional_symbols": {"hit": sum(row["symbol_supported_files"] for row in positives), "total": sum(row["covered_files"] for row in positives)},
            "rules": {"hit": sum(row["covered_rules"] for row in positives), "total": sum(row["expected_rules"] for row in positives)},
            "rule_target_pairs": {"hit": sum(row["covered_rule_target_pairs"] for row in positives), "total": sum(row["expected_rule_target_pairs"] for row in positives)},
            "ownership_end_to_end": {"hit": sum(bool(row["ownership_correct"]) for row in labelled), "total": len(labelled)},
            "ownership_with_prediction": {"hit": sum(bool(row["ownership_correct"]) for row in predicted), "total": len(predicted)},
            "node_id_uniqueness": {"hit": sum(row["unique_node_ids"] for row in language_rows), "total": sum(row["capability_nodes"] for row in language_rows)},
            "markdown_high_ownership": {"count": sum(row["markdown_nodes_with_high_ownership"] for row in language_rows), "nodes": sum(row["markdown_nodes"] for row in language_rows)},
            "negative_query_actionable_recommendations": sum(row["query_unfiltered_recommendations"] for row in negatives),
            "negative_queries_without_actionable_recommendations": sum(row["query_abstention"]["no_actionable_recommendation"] for row in negatives),
            "negative_cases": len(negatives),
            "symbol_budget_saturated_cases": sum(row["symbol_budget_saturated"] for row in positives),
            "out_of_pool_files": sum(len(row["out_of_pool_files"]) for row in language_rows),
            "evidence_by_kind": {},
        }
        for kind in ("source", "script", "configuration", "guidance", "unsupported"):
            scores = [row["evidence_by_kind"][kind] for row in positives]
            total = sum(score["expected"] for score in scores)
            hit = sum(score["covered"] for score in scores)
            symbolic = sum(score["with_symbols"] for score in scores)
            values["evidence_by_kind"][kind] = {"hit": hit, "total": total, "rate": ratio(hit, total), "symbol_hit": symbolic, "symbol_rate": ratio(symbolic, total)}
        for value in values.values():
            if isinstance(value, dict) and "hit" in value and "total" in value:
                value["rate"] = ratio(value["hit"], value["total"])
        aggregates[language] = values
    return aggregates


def _observation_metadata(observation: dict, case_id: str | None, language: str | None) -> dict:
    keys = ("project_id", "source_sha", "version", "workspace_dirty_paths", "registry_metadata_mode", "metrics", "status", "evidence_mode", "source_snapshot_id")
    return {"case_id": case_id, "language": language, **{key: observation.get(key) for key in keys}}


def freeze_daily_pool(observation: dict) -> dict[str, str]:
    """Bind both daily query graphs to the intake hashes or stop scoring."""
    root = Path(observation["repository_root"])
    texts = {}
    for item in observation["selected_files"]:
        data = (root / item["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"INVALID_EVIDENCE: source changed after intake: {item['path']}")
        texts[item["path"]] = data.decode("utf-8")
    return texts


def _daily_pool_observations(truth: dict, output: Path, max_files: int):
    """Compatibility mode: one daily pool, then bounded per-query graph calls."""
    intake = refresh_agent_contexts(output_path=output / "intake.json", max_files=max_files)
    registry = json.loads((ROOT / "workspace/projects.json").read_text())
    for observation in intake["projects"]:
        project_id = observation["project_id"]
        cases = [case for case in truth["cases"] if case["project_id"] == project_id]
        if not cases:
            continue
        if "repository_root" not in observation:
            for case in cases:
                for language in ("zh", "en"):
                    yield case, language, observation
            continue
        root = Path(observation["repository_root"])
        project = load_decomposition_project(project_id)
        config = _workspace_config(registry["projects"][project_id])
        repository, _, _ = _target_repository(config, root, project.primary_repository_id)
        pool = [item["path"] for item in observation["selected_files"]]
        texts = freeze_daily_pool(observation)
        with tempfile.TemporaryDirectory(prefix="agent-hit-", dir="/private/tmp") as raw:
            storage = Path(raw) / "registry.json"
            storage.write_text(Workspace(workspace_root=root, allowed_paths=[root], excluded_paths=[], registry_path=storage, repositories=[repository]).model_dump_json())
            bounded = WorkspaceConfig(workspace_root=root, allowed_paths=[root], registry_path=storage, registry_storage_path=storage)
            context_graph = build_context_analysis_graph(bounded)
            capability_graph = build_capability_analysis_graph(bounded)
            for case in cases:
                for language in ("zh", "en"):
                    state = {"requirement": case[f"query_{language}"], "target_repository": project.primary_repository_id, "candidate_paths": pool, "limits": {"max_files": max_files, "max_symbols": 80, "max_dependency_depth": 0}, "source_texts": texts}
                    yield case, language, {**observation, "context_package": context_graph.invoke(state)["context_package"], "capability_analysis": capability_graph.invoke(state)["capability_analysis"]}


def evaluate(goldens: Path, output: Path, max_files: int = 24, mode: str = "task") -> dict:
    if mode not in {"task", "daily_pool"}:
        raise ValueError("evaluation mode must be task or daily_pool")
    truth = json.loads(goldens.read_text())
    output = output.expanduser().resolve()
    allowed_outputs = (ROOT.resolve(), Path(tempfile.gettempdir()).resolve(), Path("/private/tmp").resolve())
    if not any(output == allowed or allowed in output.parents for allowed in allowed_outputs):
        raise ValueError("evaluation output must be inside Agent Hub or a system temporary directory")
    if output.name in PROTECTED_RUNS or (output / "results.json").exists():
        raise FileExistsError("Frozen evaluation runs must not be overwritten; choose a new output directory")
    output.mkdir(parents=True, exist_ok=True)
    rows, observations = [], []
    with ExitStack() as guards:
        for name in ("os.walk", "pathlib.Path.glob", "pathlib.Path.rglob", "agent_hub.projects.discovery.discover", "agent_hub.projects.workspace_registry.WorkspaceRegistry.refresh"):
            guards.enter_context(patch(name, side_effect=AssertionError(f"Unbounded operation forbidden: {name}")))
        if mode == "task":
            for case in truth["cases"]:
                for language in ("zh", "en"):
                    # Golden expectations are only consumed by score_case. They
                    # never become candidate_paths or discovery parameters.
                    intake = refresh_agent_contexts([case["project_id"]], output_path=output / "intakes" / f"{case['id']}-{language}.json", max_files=max_files, requirement=case[f"query_{language}"])
                    observation = intake["projects"][0]
                    rows.append(score_case(case, language, observation))
                    observations.append(_observation_metadata(observation, case["id"], language))
        else:
            for case, language, observation in _daily_pool_observations(truth, output, max_files):
                rows.append(score_case(case, language, observation))
                observations.append(_observation_metadata(observation, case["id"], language))
        result = {
            "schema": "bounded-agent-hit-evaluation.v2", "generated_at": datetime.now(UTC).isoformat(),
            "evaluation_mode": mode, "intake_requirement": "per_case_query" if mode == "task" else "daily_project_context",
            "no_walk": True, "evaluator_parameter_tuning": False, "golden_candidate_injection": False, "max_files": max_files,
            "goldens_sha256": hashlib.sha256(goldens.read_bytes()).hexdigest(),
            "case_semantics_sha256": hashlib.sha256(json.dumps(truth["cases"], ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "code_hashes": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in ("src/agent_hub/context/resolver.py", "src/agent_hub/capability/analyzer.py", "src/agent_hub/projects/agent_context.py", "src/agent_hub/capability/decisions.py")},
            "project_observations": observations, "aggregates": aggregate(rows), "cases": rows,
            "precision": {"status": "NOT_SCORED", "reason": "must_hit is a partial positive set, not a complete relevance judgement"},
            "limitations": truth.get("limitations", []) + [
                "Symbol-supported coverage and query abstention are lexical/decision proxies, not semantic answer accuracy.",
                "Existing HIGH ownership anchors do not assert platform support for a negative query; false support claims are not scored.",
                "Rule path presence is separate from rule-to-source/config applicability; missing expected targets remain in the pair denominator.",
                "Source/config/script/guidance coverage is reported separately; guidance self-targets do not establish source rule coverage.",
                "The run evaluates current local worktrees and cached unit metadata, not release acceptance.",
                "daily_pool results use a shared daily intake and cannot be compared directly with task intake as identical retrieval conditions.",
            ],
        }
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goldens", type=Path, default=ROOT / "benchmarks/agent_context_goldens/cases.json")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/agent_context_runs/20261002-task-followup")
    parser.add_argument("--max-files", type=int, default=24)
    parser.add_argument("--mode", choices=("task", "daily_pool"), default="task")
    args = parser.parse_args()
    result = evaluate(args.goldens, args.output, args.max_files, args.mode)
    print(json.dumps(result["aggregates"], indent=2))
