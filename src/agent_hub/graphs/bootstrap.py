"""The minimal, repository-agnostic bootstrap graph."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent_hub.validation.workspace_check import WorkspaceCheckResult, check_workspace
from agent_hub.workspace.config import WorkspaceConfig
from agent_hub.workspace.runtime import RuntimeWorkspaceProvider


class BootstrapState(TypedDict, total=False):
    """State emitted by the bootstrap graph."""

    result: dict[str, object]
    runtime_workspace: dict[str, object]


def build_bootstrap_graph(config: WorkspaceConfig):
    """Build START -> workspace_check -> END with injected workspace context."""

    def workspace_check(_: BootstrapState) -> BootstrapState:
        result: WorkspaceCheckResult = check_workspace(config)
        runtime = RuntimeWorkspaceProvider.from_config(config).workspace
        return {"result": result.model_dump(mode="json"), "runtime_workspace": runtime.model_dump(mode="json")}

    graph = StateGraph(BootstrapState)
    graph.add_node("workspace_check", workspace_check)
    graph.add_edge(START, "workspace_check")
    graph.add_edge("workspace_check", END)
    return graph.compile()
