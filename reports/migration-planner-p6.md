# P6 Migration Planner

## Final status

`READY_FOR_HUMAN_PLAN_REVIEW`

P6 generated a read-only, evidence-bound MigrationPlan. It authorizes no
business change: a human review is required before any future execution phase.

## Implemented modules

- `agent_hub.planning.migration_planner.MigrationPlanner`
- `MigrationPlan`, `MigrationTask`, and `BlockedItem` schemas
- `migration_planning` LangGraph, registered alongside the existing four graphs
- Planner tests covering keep/adapter preservation, blocked unknowns,
  contract-first move order, and missing dependency rejection

## Plan

- Plan ID: `migration-4acbfd7b5ac2`
- Artifact: [flutter-study-plugin-decomposition.json](../plans/flutter-study-plugin-decomposition.json)
- Status: `READY_FOR_HUMAN_PLAN_REVIEW`
- Executable planning tasks: 24
- Explicit blocked items: 35
- DAG validation: PASS — unique IDs, no missing dependencies, no cycles, no
  out-of-workspace paths, no unknown executable target, and cleanup after
  integration validation.

## Capability-to-task mapping

Only decisions with an evidence-backed existing target generated DAG tasks:

| Target development unit | Decision pattern | Tasks |
| --- | --- | ---: |
| `flutter_study:packages/gcode_core` | move existing core/platform capability | 12 |
| `flutter_study:packages/file_picker_bridge` | move existing platform implementation | 6 |
| `flutter_study:packages/flutter_study_learning` | extend public reusable contract | 6 |

Each migration chain is contract first, then implementation, caller update,
target validation, integration validation, and only then cleanup.  The plan has
3 contract definitions, 1 contract extension, 2 core moves, 2 platform moves,
4 caller updates, 8 validations, and 4 cleanup tasks.

## Preserved boundaries and blocked decisions

- KEEP_IN_APPLICATION produces no move task and is retained as an architecture
  invariant.
- ADAPTER_ONLY produces no relocation task; the adapter remains in the
  application boundary.
- UNKNOWN and NOT_ENOUGH_EVIDENCE never become positive destination decisions.
- NEW unit/plugin candidates without an approved target boundary are blocked,
  rather than being treated as executable plugin work.

The 35 blocked items include unresolved adapter/UI/platform candidates and
insufficiently evidenced existing-boundary proposals. Their evidence and
required missing proof are present in the plan.

## Rules, validation, and risk

- Applicable rule metadata is attached per task as path/scope/provenance only;
  rule text is not copied into the plan.
- 18 discovered validation commands are attached to the plan/task context where
  available. Missing commands are not invented.
- Risks are explicit per task; native platform transitions and cleanup are HIGH.
- The plan records eight architecture invariants, including application
  orchestration retention, adapter boundary preservation, explicit cross-repo
  dependency work, and validation-before-cleanup.

## Verification and integrity

| Check | Result |
| --- | --- |
| P6 planner unit tests | PASS |
| Full Agent Hub test suite | PASS |
| `langgraph validate --config langgraph.json` | PASS — 5 graphs |
| Business Git status | unchanged: file_picker_bridge 0, flutter_study 3, gcode_core 15 |
| Business code / manifests / dependencies modified | none |

## Human review required before P7

Review source/target boundaries, application-orchestration and adapter retention,
contract changes across repository boundaries, cleanup timing, validation
sufficiency, and every HIGH/BLOCKED item. No migration execution has occurred.
