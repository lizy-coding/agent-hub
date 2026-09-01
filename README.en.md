# Agent Hub

[中文](./README.md) | **English**

A project-registry-driven LangGraph workspace host and refactor-orchestration platform. Generic Worker, Thread/Run lifecycle, and path guards are repository-neutral; project-specific capability inventories and architecture rules are explicit adapters.

Agent Hub does not contain, move, or copy business project code. It accepts an externally supplied "workspace root + repository registry" as its runtime context (`workspace/config.json`) and hosts a set of read-only / refactor / migration orchestration Graphs on top of that context. Adding a repository through a refreshed registry therefore **requires no Graph source change**.

---

## 1. Layout

| Path | Purpose |
| --- | --- |
| `src/agent_hub/` | Source (`gateway` CLI, `graphs`, `projects` registry, `workspace` config, `execution` workers, `policies` safety) |
| `langgraph.json` | Registers every Graph entrypoint for the LangGraph CLI |
| `workspace/config.json` | Workspace runtime context (workspace root, allowed paths, excluded paths, registry) |
| `workspace/projects.json` | Decomposition project registry |
| `workspace/registry.json` | Normalized engineering-fact registry (generated read-only artifact) |
| `agent` | Local CLI entrypoint (refactor / decomposition dashboard) |
| `.integration/` | Development-refactor integration worktree (flutter_forge, created at runtime by `refactor-run`) |
| `.decomposition/` | Decomposition program worktrees and state snapshots |
| `plans/` | Migration / decomposition plans and proposals (JSON) |
| `tests/` | `unittest` suite |

---

## 2. Registered Graphs

| Graph (`langgraph.json`) | Module | Purpose |
| --- | --- | --- |
| `workspace_bootstrap` | `graphs/bootstrap.py` | Minimal read-only graph `START -> workspace_check -> END`; verifies the workspace is readable, the registry parses, every registry repo path is inside the workspace root and exists, and LangGraph is importable |
| `context_analysis` | `graphs/context_analysis.py` | Read-only context resolver: load registry, resolve candidates, search evidence, resolve rules, build context package |
| `capability_analysis` | `graphs/capability_analysis.py` | Capability analysis: context -> capability discovery -> coupling analysis -> ownership classification -> workspace match -> extraction assessment |
| `shadow_benchmark` | `graphs/shadow_benchmark.py` | Shadow benchmark: load scenarios and reviewed goldens, run context/capability analysis, score evidence, aggregate metrics, evaluate gate |
| `migration_planning` | `graphs/migration_planning.py` | Migration planning: derive architecture invariants from capability analysis, generate a MigrationTask DAG, attach rules/validation, assess risk |
| `migration_execution` | `graphs/migration_execution.py` | Migration execution skeleton (load approved plan, verify authority & source freshness, prepare worktree, execute, scope/validate/integration) |
| `development` | `graphs/development.py` | Refactor execution graph: `bootstrap_runtime -> reconcile -> inventory -> normalize -> prepare -> execute -> review -> commit -> final_rescan`; drives single-repo global refactor programs |
| `decomposition` | `graphs/decomposition.py` | Decomposition orchestration: capability inventory -> package-candidate classification -> MigrationTask DAG -> worktree management -> Worker dispatch -> validation -> review -> integration |
| `release_hosting` | `graphs/release_hosting.py` | GitHub installer release hosting (scene#22 CI/CD): reconcile -> freeze -> verify_artifacts -> preflight -> publish -> verify_release; PLAN_ONLY by default, `--execute` publishes through the frozen `gh release` lane |

---

## 3. Environment & Install

- Python `>= 3.11`
- Dependencies managed by `pyproject.toml` (langgraph, langgraph-cli, pydantic, PyYAML)

```bash
cd /path/to/agent-hub
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Verify all Graphs parse with the LangGraph CLI:

```bash
langgraph validate --config langgraph.json
```

---

## 4. Start the LangGraph Server

The dashboard and `./agent` default to `http://127.0.0.1:2024`:

```bash
langgraph dev --no-browser --no-reload --port 2024
```

---

## 5. Usage

### 5.1 Bootstrap check

```bash
agent-hub-bootstrap --config workspace/config.json
```

- Switch workspace at runtime without changing graph source:

  ```bash
  agent-hub-bootstrap --config workspace/config.json --workspace-root /absolute/new/workspace
  ```

- Use a different registry (an explicitly configured read-only input; its repo paths must still resolve under `workspace_root`):

  ```bash
  agent-hub-bootstrap --config workspace/config.json --registry-path /absolute/path/to/registry.json
  ```

### 5.2 Refresh the engineering-fact registry

```bash
python -c 'from pathlib import Path; from agent_hub.workspace.config import WorkspaceConfig; from agent_hub.projects.api import refresh; print(refresh(WorkspaceConfig.from_file(Path("workspace/config.json"))))'
```

`WorkspaceRegistry` is the read-only engineering-fact layer: it discovers Git roots and manifest-backed development units only inside the configured workspace, records evidence and freshness, derives path dependencies, and persists the normalized result to `workspace/registry.json`. The stable consumer API lives in `agent_hub.projects.api` (`get_workspace`, repository/unit listing & lookup, dependency/dependent lookup, rule-file & validation lookup, `refresh`, `validate_registry`).

> `AGENTS.md` / `AGENTS.override.md` are stored as path/scope/provenance only; rule text is **not** copied into the registry.

### 5.3 Refactor program (development Graph)

```bash
./agent refactor-status            # inspect persisted refactor thread state
./agent refactor-watch             # refresh state every 2 seconds
./agent refactor-run               # submit/continue a global refactor run (auto-starts the Worker)
./agent refactor-decide --decision-id <id> --choice <choice> [--reason "..."]   # resolve blocked decisions
```

The refactor program follows a **frozen-task** model: only one frozen `DevelopmentTask` may change code at a time. After Worker -> Codex -> ScopeGuard -> targeted validation -> flutter analyze baseline comparison -> Reviewer, only approved tasks are committed inside the integration worktree. It never pushes, merges, or releases.

### 5.4 Decomposition program (decomposition Graph, PLAN_ONLY)

```bash
./agent decomposition-plan                # submit a planning run
./agent decomposition-propose --spec <proposal.json>   # read-only custom task proposal
./agent decomposition-sync                # fast-forward a clean managed base to the verified integration HEAD
./agent decomposition-status              # inspect decomposition program state
./agent decomposition-run --execute       # allow a MigrationTask run (plan-only by default)
./agent decomposition-decide --decision-id <id> --choice <choice>
```

- Decomposition programs are registered per project in `workspace/projects.json` (default project `flutter-forge`).
- The planning phase **never executes** a migration; execution requires an explicit `--execute`, and the Graph freezes exact Worker paths.
- Custom proposals may not carry graph-owned fields such as `allowed_paths` / `candidate_paths`.

### 5.5 Installer release hosting (release_hosting Graph, scene#22 CI/CD)

```bash
./agent release-plan [--spec release.json]   # Freeze a ReleaseProgram and verify installer sha256 (PLAN_ONLY)
./agent release-status                       # Inspect the release program
./agent release-run --execute                # Publish to GitHub Releases through the frozen gh release lane
./agent release-decide --decision-id retry:release:<tag> --choice retry   # Retry after a partial publish
```

- The publish target is frozen in the `release` section of `workspace/projects.json`: `github_repo` (must be configured before publishing, otherwise the plan blocks with `RELEASE_NOT_CONFIGURED`), `tag_prefix`, `artifact_root`, default draft/prerelease.
- Flutter Forge convention: installers are pre-built by CI or a local build into `<repo>/release/<version>/`, named `FlutterForge-<version>-<platform>.<ext>` (apk/aab/dmg/exe/msix/zip/ipa/tar.gz), with an optional `SHA256SUMS` cross-check; the version defaults to `apps/flutter_forge/pubspec.yaml`.
- The graph only consumes pre-built installers and **never runs builds**; every artifact's sha256 is recomputed and compared against the frozen value before publishing. Path escapes, missing files, or checksum mismatches block the program.
- The release lane is the single explicit exception to `forbid_release` (`policies/safety.py::validate_release_command`): only `gh release create/upload/view/list`, `gh auth status`, and `gh repo view` are allowed, and `--repo` must equal the frozen repository; `delete`/`edit`/push/merge stay forbidden. Credentials come from the operator's own `gh auth` session; no token is stored by this host.
- Idempotent resume: an existing tag switches to RESUME mode and only re-uploads missing assets; an interrupted upload blocks with `PARTIAL_PUBLISH` and resumes after a `release-decide` retry; the release is marked `PUBLISHED` only after the remote assets match the frozen manifest by name and size.

---

## 6. Configuration

### 6.1 `workspace/config.json`

| Field | Purpose |
| --- | --- |
| `workspace_root` | Workspace root directory |
| `allowed_paths` | Paths allowed for reading (defaults to the workspace root) |
| `excluded_paths` | Paths to exclude |
| `registry_path` | Externally supplied bootstrap registry (JSON) |
| `registry_storage_path` | Where the normalized registry is persisted |
| `runtime` | Runtime identity (environment, primary repository, repository runtime paths) |

### 6.2 `workspace/projects.json`

Decomposition project registry: `default_project` plus per-project `adapter` / `program_id` / `snapshot_namespace` / `workspace_config` path.

### 6.3 `.env.local`

Local runtime parameters: Worker endpoint, Codex profile, etc. (this file holds secrets; do not commit it — provide a `.env.local.example` if needed). Values can be overridden via environment variables such as `AGENT_HUB_CODE_WORKER_ENDPOINT` and `AGENT_HUB_CONFIG`.

---

## 7. Safety Policy

Deny-by-default; see `src/agent_hub/policies/safety.py`:

- Business repositories are read-only: reads are limited to configured `allowed_paths`;
- Writes to business repositories, and Git push / merge / release / repository deletion, are forbidden;
- The host exposes no unrestricted shell executor;
- Execution must stay within Graph-frozen paths (ScopeGuard checks both tracked and untracked changes).

---

## 8. Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests
```

Coverage includes: bootstrap, workspace registry, runtime workspace, context resolver, capability analyzer, migration planner/executor, shadow benchmark, refactor dashboard/decide/run, development reconciliation, decomposition, architecture goldens, and more.

---

## 9. Current Scope

- Implemented: bootstrap check, workspace registry, context resolution, capability analysis, shadow benchmark, migration planning/execution skeleton, development refactor program, decomposition program.
- Deliberately out of scope: requirement analyzers, general-purpose RAG, external project-management integrations; apart from the frozen release_hosting lane, the host never pushes, merges, or releases.
