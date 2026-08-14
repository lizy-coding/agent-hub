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

After the flutter_study migration and the removal of the standalone husk repositories (`gcode_core`, `file_picker_bridge`, `flutter_study_learning` at the workspace root), discovery reports:

| Repository | Type | Development units |
|---|---|---:|
| `flutter_study` | Git repository | 10 |
| `flutter_study__agent_p7_gcode` | standalone manifest project (archival snapshot) | 9 |
| `file_picker_bridge` | standalone project inside the archive snapshot | 1 |
| `flutter_ioc_core` | standalone project inside the archive snapshot | 1 |
| `flutter_study_learning` | standalone project inside the archive snapshot | 1 |
| `gcode_core` | standalone project inside the archive snapshot | 2 |
| `example` | standalone project inside the archive snapshot | 1 |
| `windows` | standalone project inside the archive snapshot | 3 |
| `flutter` | standalone project inside the archive snapshot | 1 |
| `runner` | standalone project inside the archive snapshot | 1 |

The managed repository boundary now contains a single Git repository (`flutter_study`) with 10 development units (the `apps/flutter_study` app, its four `packages/*` workspace members, plus manifest-backed Windows/example components). The `flutter_study__agent_p7_gcode` tree is a read-only archival snapshot of an earlier repo layout. The 30 total units include Pub/Flutter units and the manifest-backed Windows CMake components.

## Dependency overview

Ten direct `path_dependency` edges were discovered, all with a manifest evidence path:

- `flutter_study:.` -> its four declared Pub workspace path packages.
- `flutter_study__agent_p7_gcode:.` -> the four packages inside the archival snapshot.
- `gcode_core:.` and `example:.` -> `gcode_core:.` within the archival snapshot.

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

Current stable refresh result (after husk removal):

```json
{"added": [], "removed": ["file_picker_bridge-40241", "flutter_study_learning-95758", "gcode_core-23952"], "changed": ["example", "file_picker_bridge", "flutter_study", "flutter_study__agent_p7_gcode", "gcode_core"], "unchanged": ["flutter", "flutter_ioc_core", "flutter_study_learning", "runner", "windows"], "ambiguous": []}
```

## Test results

`python -m unittest discover -s tests -v` passed all 5 tests. Together they cover bootstrap compatibility; registry load/discovery; a multi-unit Git repository; dependency and dependent queries; AGENTS discovery; path lookup; refresh add/remove/change; invalid path dependencies; normal/escape/symlink path boundaries; and no guessed edge outside the workspace.

The existing `workspace_bootstrap` graph also ran successfully after Registry integration. Business Git status before and after remained unchanged: one clean repository, one repository with its existing three untracked files, and one repository with its existing 12 modified/staged plus 3 untracked entries.

## Context Resolver readiness

The Registry supplies a stable, queryable Workspace/Repository/DevelopmentUnit API with evidence, freshness, dependencies, dependents, rules, validation, and safe path lookup. It therefore satisfies Context Resolver input conditions. No Context Resolver, planner, developer/reviewer agent, RAG, or business code change was implemented.
