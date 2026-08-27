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

After the repository migration and rename, discovery reports:

| Repository | Type | Development units |
|---|---|---:|
| `flutter_forge` | Git repository | 10 |

The managed runtime boundary contains one primary Git repository (`flutter_forge`) with its application, four internal `packages/*` workspace members, and platform/example components. `workspace/config.json` names only `flutter_forge` as the managed, writable primary repository. The obsolete archival snapshot remains excluded so it cannot re-enter discovery if restored locally.

## Dependency overview

Four direct `path_dependency` edges were discovered, all with a manifest evidence path:

- `flutter_forge:.` -> its four declared Pub workspace path packages.

No dependency is inferred from a repository or directory name. Reverse `dependents` are derived from those same evidence-bearing edges.

## Rule files and validation

- Rule discovery found `flutter_forge/AGENTS.md`, stored only with its path, directory scope, and `filesystem` provenance.
- No `AGENTS.override.md` was found.
- Dart/Flutter manifest units expose format/analyze/test candidates when their runtime/test evidence exists.
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
- an unchanged second refresh reports the same repositories in `unchanged`.

The persisted `workspace/registry.json` is refreshed from this active boundary; historical migration and benchmark artifacts may still mention `flutter_study`, but they are not runtime repository registrations.

## Test results

The focused runtime, project configuration, refactor runner, and workspace registry suites pass. Together they cover bootstrap compatibility; registry load/discovery; a multi-unit Git repository; dependency and dependent queries; AGENTS discovery; path lookup; refresh add/remove/change; invalid path dependencies; normal/escape/symlink path boundaries; and no guessed edge outside the workspace.

The bootstrap graph also succeeds with one registered repository: `flutter_forge`.

## Context Resolver readiness

The Registry supplies a stable, queryable Workspace/Repository/DevelopmentUnit API with evidence, freshness, dependencies, dependents, rules, validation, and safe path lookup. It therefore satisfies Context Resolver input conditions. No Context Resolver, planner, developer/reviewer agent, RAG, or business code change was implemented.

## Milestone: flutter_forge v1.2.1

Released 2026-08-23 (installer structure completed). Ships a macOS unsigned zip and a Windows Inno Setup `.exe`. Identity is placeholder `com.flutterforge.preview`, pending assignment of the real bundle identity. `INSTALL_GUIDE` covers both platforms; release notes are structured by platform. Current flutter_forge HEAD is `6a6cad8`. Registry refreshed to 2026-08-23 reflecting this state.

## Capability update: Windows resilient online video playback

Observed at flutter_forge `432ad04` on 2026-08-25. The app-owned `online_video_player` capability now uses `video_player_win` on Windows, performs a `dio` reachability precheck, rebuilds and safely disposes controllers across retries, and rejects stale asynchronous opens with a generation guard. The error state exposes an explicit retry action, with adapter regression coverage in the business repository. Agent Hub records this as `windows-resilient-online-video-playback`, owned by `apps/flutter_forge`; it remains an app/platform capability rather than a reusable package candidate.

The untracked `.hermes/fix-usb-detector-subscription.codex.json` file is a pending external task input and is intentionally excluded from the active capability record until its business change is committed. Current flutter_forge HEAD is `432ad04`; Windows device acceptance remains outstanding per that commit's checklist.

## Current maintainability baseline (2026-08-27)

Flutter Forge now has a responsive navigation policy: Android/iOS/Web and compact windows use in-app navigation; only large supported desktop windows may create category windows. Android host and APK smoke validation passed on an Android 15 AOSP ARM64 emulator; Windows build evidence remains host-dependent.

The current Flutter Forge implementation commits are `58defb5`, `7ac3d92`, and `d581db5`. Agent Hub records the next PC封板 tasks as `pc_window_lifecycle_baseline` and `pc_build_matrix`, followed by the non-blocking Android compatibility tasks. The business-module intake remains gated by module contracts, tests, and adapter-frozen paths.
