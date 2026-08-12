# P6.1 Migration Planner Semantic Correction

## Original review

`CHANGES_REQUIRED` for P6 plan `migration-4acbfd7b5ac2`. The revised planner
separates architecture intent from a physically actionable migration delta.
P7 remains unauthorized pending this revised human review.

## Corrections

- Added `MigrationDelta` to every executable task contract.
- A MOVE now requires distinct current and intended development-unit ownership.
  Same-unit capability evidence is classified `ALREADY_IN_TARGET`; it cannot
  generate MOVE, caller-switch, or cleanup tasks.
- Cleanup validation rejects overlapping source/destination implementation paths.
- A planner never selects between equivalent repository/development-unit targets
  by name or current location. Without separate canonical ownership, consumer,
  and destination proof it emits a blocker.
- `UPDATE_CALLER` requires real consumer paths; absent callsite evidence means no
  caller task.
- Root and nested `AGENTS.md`/`AGENTS.override.md` scope metadata now resolves
  from actual allowed change paths. Empty effective rules block an executable
  task.
- Artifact filtering excludes docs, rule files, manifests, locks, generated
  artifacts, ephemeral files, and tests from the migration-capability plan.

## Revised plan

- [Revised plan JSON](../plans/flutter-study-plugin-decomposition-p6-1.json)
- Status: `READY_FOR_HUMAN_PLAN_REVIEW`
- Executable tasks: 0
- Blocked real capabilities: 22
- Already in target: 4
- P6 self-migration/no-op task chains removed: 24 tasks removed.

No executable task is emitted because currently available bounded evidence does
not establish a distinct source path, destination path, canonical target unit,
and real consumer caller change for any proposed migration. Four assessed
capabilities are already physically inside their intended target unit, so they
are correctly `ALREADY_IN_TARGET` rather than migrations.

## Identity, caller, and validation semantics

- Repository and development-unit identities remain distinct in the delta model.
- Ambiguous duplicate candidate units are blocked, never resolved by package name.
- There are no caller tasks because no bounded caller evidence identified a
  consumer file needing change.
- There are no target/integration tasks because P6.1 permits them only for a
  concrete nonempty delta. The host repository validation commands remain in the
  plan-level strategy for any future approved delta.
- No broad package-directory paths are used in executable change scope.

## DAG and integrity

- DAG validation: PASS (empty executable DAG; no cycles or missing refs).
- Tests: PASS, including self-move rejection and already-owned no-op behavior.
- Full Agent Hub suite: PASS.
- `langgraph validate --config langgraph.json`: PASS (5 graphs).
- Business Git state unchanged: file_picker_bridge `0`, flutter_study `3`,
  gcode_core `15`.

## Next human review

Review whether any of the 22 blocked capabilities should supply new canonical
target ownership, explicit destination files, public contract deltas, and real
consumer callsites. Only then can the planner produce a genuine pilot chain.
No migration execution has occurred.
