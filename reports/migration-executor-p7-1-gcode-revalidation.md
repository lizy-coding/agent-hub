# P7.1 gcode_core Adoption Environment Repair and Revalidation

## Final status

`PILOT_VALIDATION_FAILED`

The missing unrelated flutterguard path prerequisite was repaired in an isolated
execution topology. Dependency resolution then succeeded, but the active Pub
workspace still resolved `gcode_core` to its nested workspace member rather
than the approved standalone canonical provider. The adoption therefore did not
take effect and validation stopped without any business repair.

## Environment repair

- Run ID: `p7-1-gcode-adoption-20260812`
- Execution root: `/Users/forest/code/agent-hub/.execution/p7-1-gcode-adoption-20260812`
- Isolated flutter_study worktree: `.../flutter_study`
- `../gcode_core` realpath: `/Users/forest/code/langGraph/gcode_core`
- `../flutterguard` realpath: `/Users/forest/code/flutterguard`
- flutterguard manifest identity: `flutterguard_cli`

The flutterguard provider was discovered through its exact local `pubspec.yaml`
package name and exposed only through an execution-root symlink. No business
dependency declaration or provider source was modified.

## Approved diff and scope

Only the approved one-line worktree delta exists:

```diff
gcode_core:
-  path: packages/gcode_core
+  path: ../gcode_core
```

No Dart/test/package/native source, lockfile, file-picker, canonical provider,
or flutterguard provider change occurred. Scope guard passed.

## Validation evidence

| Check | Result |
| --- | --- |
| `flutter pub get` | PASS |
| flutterguard identity | PASS: `/Users/forest/code/flutterguard` |
| gcode_core identity | FAIL: `.dart_tool/package_config.json` root URI is `../packages/gcode_core` |
| `flutter analyze` | FAIL: 198 existing info diagnostics |
| `flutter test` | not run: canonical dependency identity hard gate failed |

The host remains an active Pub workspace whose member list includes
`packages/gcode_core`. That workspace resolution overrides the explicit
dependency path during package configuration, so the planned adoption does not
actually select `/Users/forest/code/langGraph/gcode_core`.

## Required architecture decision

A future phase must explicitly authorize and plan a Pub workspace membership or
resolution-model change. That is outside this adoption-only P7.1 scope; changing
it would alter dependency architecture and cannot be inferred as environment
repair.

## Integrity and verification

- Original flutter_study porcelain unchanged.
- Canonical gcode_core porcelain unchanged.
- Flutterguard provider porcelain unchanged.
- Executor path-dependency preflight tests: PASS.
- Full Agent Hub test suite: PASS.
- `langgraph validate --config langgraph.json`: PASS — 6 graphs.
- Structured record:
  [execution.json](../executions/p7-1-gcode-adoption-20260812/execution.json)

The isolated worktree and environment root are retained for human inspection;
no commit, push, merge, cleanup, or automatic rollback occurred.
