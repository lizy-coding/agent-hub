"""Read-only Context Resolver graph."""
import json
from pathlib import Path
from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from agent_hub.context.resolver import ContextResolver
from agent_hub.workspace.config import WorkspaceConfig

class ContextState(TypedDict, total=False):
    requirement: str
    target_repository: str | None
    context_package: dict[str, object]

def _refactor_plan_path(config: WorkspaceConfig) -> Path:
    runtime = config.runtime if isinstance(config.runtime, dict) else {}
    repositories = runtime.get("repositories")
    if isinstance(repositories, dict):
        primary = str(runtime.get("primary_repository_id") or "")
        entries = [repositories.get(primary)] if primary else []
        entries.extend(value for key, value in repositories.items() if key != primary)
        for entry in entries:
            if isinstance(entry, dict) and entry.get("runtime_path"):
                candidate = Path(str(entry["runtime_path"])) / "REFACTOR_PLAN.md"
                if candidate.is_file():
                    return candidate
    candidates = sorted(config.workspace_root.glob("*/REFACTOR_PLAN.md"))
    return candidates[0] if candidates else config.workspace_root / "REFACTOR_PLAN.md"

def _load_plan_entries(plan_path: Path) -> list[dict]:
    if not plan_path.is_file():
        return []
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = payload.get("work_queue") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]

def planned_capabilities(package: dict[str, object], config: WorkspaceConfig) -> list[dict[str, object]]:
    """Surface pending REFACTOR_PLAN work whose targets intersect resolved paths.

    Read-only and backward compatible: absent or unparsable plans yield an
    empty list and the field simply remains omitted/empty for non-matching
    repositories.
    """
    resolved = [str(item.get("relative_path", "")) for item in package.get("files", []) if isinstance(item, dict)]
    planned: list[dict[str, object]] = []
    for entry in _load_plan_entries(_refactor_plan_path(config)):
        if str(entry.get("status", "")) != "pending":
            continue
        targets = [str(item) for item in entry.get("targets") or entry.get("changes") or [] if isinstance(item, str)]
        if not targets:
            continue
        if any(target and any(target in path for path in resolved) for target in targets):
            planned.append({"task_id": str(entry.get("id", "")), "targets": targets, "status": "pending"})
    return planned

def build_context_analysis_graph(config: WorkspaceConfig):
    resolver = ContextResolver(config)
    def load_registry(state): return {}
    def resolve_candidates(state): return {}
    def search_evidence(state): return {}
    def resolve_rules(state): return {}
    def build_context_package(state):
        package=resolver.resolve_context(state["requirement"], state.get("target_repository"))
        data=package.model_dump(mode="json")
        data["planned_capabilities"]=planned_capabilities(data, config)
        return {"context_package": data}
    graph=StateGraph(ContextState)
    graph.add_node("load_registry", load_registry); graph.add_node("resolve_candidates", resolve_candidates); graph.add_node("search_evidence", search_evidence); graph.add_node("resolve_rules", resolve_rules); graph.add_node("build_context_package", build_context_package)
    graph.add_edge(START,"load_registry"); graph.add_edge("load_registry","resolve_candidates"); graph.add_edge("resolve_candidates","search_evidence"); graph.add_edge("search_evidence","resolve_rules"); graph.add_edge("resolve_rules","build_context_package"); graph.add_edge("build_context_package",END)
    return graph.compile()
