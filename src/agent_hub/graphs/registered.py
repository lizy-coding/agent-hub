"""LangGraph CLI entrypoint with runtime workspace configuration injection."""

import os
from pathlib import Path

from agent_hub.graphs.bootstrap import build_bootstrap_graph
from agent_hub.workspace.config import WorkspaceConfig


_HUB_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG = _HUB_ROOT / "workspace" / "config.json"


def _load_config() -> WorkspaceConfig:
    """Use an explicit environment override or the host's local config file."""

    return WorkspaceConfig.from_file(Path(os.environ.get("AGENT_HUB_CONFIG", _DEFAULT_CONFIG)))


graph = build_bootstrap_graph(_load_config())
