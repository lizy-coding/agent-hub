"""CLI registration object for the generic Context Resolver graph."""
from agent_hub.graphs.context_analysis import build_context_analysis_graph
from agent_hub.graphs.registered import _load_config
graph = build_context_analysis_graph(_load_config())
