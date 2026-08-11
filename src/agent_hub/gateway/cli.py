"""CLI for the read-only bootstrap graph."""

import argparse
import json
from pathlib import Path

from agent_hub.graphs.bootstrap import build_bootstrap_graph
from agent_hub.workspace.config import WorkspaceConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only Agent Hub bootstrap graph.")
    parser.add_argument("--config", type=Path, required=True, help="WorkspaceConfig JSON file")
    parser.add_argument("--workspace-root", type=Path, help="Override workspace_root for this run")
    parser.add_argument("--registry-path", type=Path, help="Override registry_path for this run")
    args = parser.parse_args()

    config = WorkspaceConfig.from_file(
        args.config,
        workspace_root=args.workspace_root,
        registry_path=args.registry_path,
    )
    state = build_bootstrap_graph(config).invoke({})
    print(json.dumps(state["result"], indent=2, sort_keys=True))
    return 0 if state["result"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
