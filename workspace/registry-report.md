# Workspace Registry P2 report

**Status: READY_FOR_CONTEXT_RESOLVER**

## Registry architecture

`WorkspaceRegistry` implements the read-only pipeline:

```text
bootstrap input -> discover -> normalize -> compare -> persist
```

Discovery uses resolved-path containment before every workspace walk. It detects Git roots, manifest-backed units (`pubspec.yaml`, `pyproject.toml`, `Cargo.toml`, `package.json`, and `CMakeLists.txt`), and standalone manifest projects outside Git roots. Dependencies are created only when a supported manifest specifies a resolvable local path target. The persisted registry is `workspace/registry.json`; the API is storage-independent and exposed from `agent_hub.projects.api`.

Each discovered record has evidence (`source`, workspace-relative evidence path, timestamp/detail) and freshness. Registry persistence retains the empty `manual_overrides` boundary from any previous registry rather than overwriting it.

## Current discovery

| Repository | Type | Development units |
|---|---|---:|
| `file_picker_bridge` | Git repository | 1 |
| `flutter_study` | Git repository | 9 |
| `gcode_core` | Git repository | 2 |
| `flutter_study_learning` | standalone manifest project (not a Git root) | 1 |

The Git repository with multiple development units confirms that Repository and DevelopmentUnit are independent concepts. The 13 total units include Pub/Flutter units and the manifest-backed Windows CMake components.

## Dependency overview

Six direct `path_dependency` edges were discovered, all with a manifest evidence path:

- `flutter_study:.` -> its four declared Pub workspace path packages.
- `flutter_study:packages/gcode_core/example` -> `flutter_study:packages/gcode_core`.
- `gcode_core:example` -> `gcode_core:.`.

No dependency is inferred from a repository or directory name. Reverse `dependents` are derived from those same evidence-bearing edges.

## Rule files and validation

- Rule discovery found `flutter_study/AGENTS.md`, stored only with its path, directory scope, and `filesystem` provenance.
- No `AGENTS.override.md` was found.
- Dart/Flutter manifest units expose format/analyze/test candidates when their runtime/test evidence exists. The standalone learning package has no discovered test directory, so no test command is guessed.
- CMake units have no guessed validation command.

## Unknown and ambiguous facts

- The three Windows CMake development units have `capabilities: ["unknown"]`; their directory names are not treated as capabilities.
- No ambiguous repository or dependency edge was produced in the current refresh.
- External or unresolved manifest paths do not generate dependency edges.

## Refresh diff example

The test suite creates temporary workspace changes and verifies:

- a newly discovered repository appears in `added`;
- a removed repository appears in `removed`;
- manifest content changes appear in `changed` through content-hash provenance;
- an unchanged second refresh reports the four current repositories in `unchanged`.

Current stable refresh result:

```json
{"added": [], "removed": [], "changed": [], "unchanged": ["file_picker_bridge", "flutter_study", "flutter_study_learning", "gcode_core"], "ambiguous": []}
```

## Test results

`python -m unittest discover -s tests -v` passed all 5 tests. Together they cover bootstrap compatibility; registry load/discovery; a multi-unit Git repository; dependency and dependent queries; AGENTS discovery; path lookup; refresh add/remove/change; invalid path dependencies; normal/escape/symlink path boundaries; and no guessed edge outside the workspace.

The existing `workspace_bootstrap` graph also ran successfully after Registry integration. Business Git status before and after remained unchanged: one clean repository, one repository with its existing three untracked files, and one repository with its existing 12 modified/staged plus 3 untracked entries.

## Context Resolver readiness

The Registry supplies a stable, queryable Workspace/Repository/DevelopmentUnit API with evidence, freshness, dependencies, dependents, rules, validation, and safe path lookup. It therefore satisfies Context Resolver input conditions. No Context Resolver, planner, developer/reviewer agent, RAG, or business code change was implemented.
