# P7 gcode_core Adoption Pilot

## Final status

`PILOT_VALIDATION_FAILED`

The approved, isolated dependency-adoption change was applied only in the pilot
worktree, but validation could not resolve the existing unrelated
`flutterguard_cli` path dependency. Per P7 policy, no business-code repair or
scope expansion was attempted.

## Execution

- Run ID: `p7-gcode-adoption-20260812`
- Approved plan: `migration-4acbfd7b5ac2`
- Approved tasks only: gcode_core `adopt-dependency` and `validate-host`
- Worktree: `/Users/forest/code/langGraph/flutter_study__agent_p7_gcode`
- Branch: `agent/p7-gcode-adoption-20260812`
- Base revision: `930bd47fcf29171bbfc5d281fb21fda9b858453f`
- Canonical provider revision: `d4dad03aeb88e95cc6ddd51d9f98016ce2b0ced4`

The worktree sibling layout resolves `../gcode_core` exactly to
`/Users/forest/code/langGraph/gcode_core`.

## Scoped diff

Only `pubspec.yaml` changed:

```diff
gcode_core:
-  path: packages/gcode_core
+  path: ../gcode_core
```

No Dart, test, package-source, native-platform, lockfile, file-picker, canonical
provider, cleanup, commit, push, or merge change occurred. Scope guard passed;
the exact worktree diff is retained for review.

## Validation

| Command | Result |
| --- | --- |
| `flutter pub get` | FAIL before gcode_core resolution |
| dependency identity check | not reached |
| `flutter analyze` | not run — dependency resolution prerequisite failed |
| `flutter test` | not run — dependency resolution prerequisite failed |

Failure:

```text
main_app depends on flutterguard_cli from path which doesn't exist
(could not find package flutterguard_cli at "../flutterguard")
```

This is an existing unrelated path dependency outside the approved pilot scope.
P8 repair is not authorized, so it was not modified.

## Integrity and rollback

- Original flutter_study porcelain remained `3` entries, unchanged.
- Canonical gcode_core porcelain remained `15` entries, unchanged.
- The isolated worktree contains the sole reviewable `pubspec.yaml` diff.
- Rollback boundary: original repositories are untouched; preserve the worktree
  for inspection. No automatic removal/reset was performed.

## Executor verification

- Scoped MigrationExecutor primitives and worktree relative-path guard added.
- Executor unit test: PASS.
- Full Agent Hub regression suite: PASS.
- `langgraph validate --config langgraph.json`: PASS — 6 graphs.
- Structured execution record:
  [execution.json](../executions/p7-gcode-adoption-20260812/execution.json)

## Required decision

Authorize a separate repair/availability action for the missing
`../flutterguard` dependency, or provide an environment where that pre-existing
path resolves. The same retained worktree diff can then be revalidated without
changing the approved gcode_core adoption scope.
