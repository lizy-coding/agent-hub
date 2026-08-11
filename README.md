# Agent Hub

Agent Hub is a repository-agnostic LangGraph host for a configured workspace. It does not contain, move, or copy business projects. A workspace is an externally supplied root directory plus a registry of repository facts.

Repositories are managed as runtime context: `workspace/config.json` supplies the workspace root, the paths the host may read, paths to exclude, and the bootstrap registry. Graph code only accepts that context; adding a repository through a refreshed registry does not require a Graph source change.

## Current scope

The only graph is the bootstrap graph:

```text
START -> workspace_check -> END
```

`workspace_check` confirms that the configured workspace can be read, the registry can be parsed, each registry repository path is contained by the workspace root and exists, and the host can import LangGraph. It is read-only: it does not run shell commands, alter a repository, or invoke Git.

Safety defaults are deny-by-default for business paths. Reads are limited to configured allowed paths, writes to business repositories are prohibited, and the policy forbids Git push, merge, release, repository deletion, and unrestricted shell execution.

No requirement analyzer, planner, developer/reviewer agent, RAG, supervisor, or external project-management integration is included.

## Workspace Registry (P2)

`WorkspaceRegistry` is the read-only engineering-fact layer. It discovers Git roots and manifest-backed development units only inside the configured workspace, records evidence and freshness, derives only manifest-backed path dependencies, and persists the normalized result to `workspace/registry.json`.

Its stable consumer API is in `agent_hub.projects.api`: `get_workspace`, repository/unit listing and lookup, dependency/dependent lookup, rule-file and validation lookup, `refresh`, and `validate_registry`. `AGENTS.md` and `AGENTS.override.md` are stored as path/scope/provenance only; rule text is not copied into the registry.

Run a refresh from the project environment:

```bash
python -c 'from pathlib import Path; from agent_hub.workspace.config import WorkspaceConfig; from agent_hub.projects.api import refresh; print(refresh(WorkspaceConfig.from_file(Path("workspace/config.json"))))'
```

## Run

```bash
cd /Users/forest/code/agent-hub
source .venv/bin/activate
agent-hub-bootstrap --config workspace/config.json
```

To switch workspace context without changing graph source:

```bash
agent-hub-bootstrap --config workspace/config.json --workspace-root /absolute/new/workspace
```

If a different registry is needed, pass `--registry-path /absolute/path/to/registry.json`. The registry is an explicitly configured non-business read input; repository paths inside it must still resolve under `workspace_root`.
