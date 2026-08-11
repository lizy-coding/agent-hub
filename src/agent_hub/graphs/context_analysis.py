"""Read-only Context Resolver graph."""
from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from agent_hub.context.resolver import ContextResolver
from agent_hub.workspace.config import WorkspaceConfig

class ContextState(TypedDict, total=False):
    requirement: str
    target_repository: str | None
    context_package: dict[str, object]

def build_context_analysis_graph(config: WorkspaceConfig):
    resolver = ContextResolver(config)
    def load_registry(state): return {}
    def resolve_candidates(state): return {}
    def search_evidence(state): return {}
    def resolve_rules(state): return {}
    def build_context_package(state):
        package=resolver.resolve_context(state["requirement"], state.get("target_repository")); return {"context_package": package.model_dump(mode="json")}
    graph=StateGraph(ContextState)
    graph.add_node("load_registry", load_registry); graph.add_node("resolve_candidates", resolve_candidates); graph.add_node("search_evidence", search_evidence); graph.add_node("resolve_rules", resolve_rules); graph.add_node("build_context_package", build_context_package)
    graph.add_edge(START,"load_registry"); graph.add_edge("load_registry","resolve_candidates"); graph.add_edge("resolve_candidates","search_evidence"); graph.add_edge("search_evidence","resolve_rules"); graph.add_edge("resolve_rules","build_context_package"); graph.add_edge("build_context_package",END)
    return graph.compile()
