# P6.3 Human Architecture Authority and Canonical Target Resolution

## Final status

`READY_FOR_P7_PILOT_REVIEW`

P7 remains unauthorized. This plan is an evidence-backed, read-only candidate
for human pilot approval only.

## Authority

[ArchitectureAuthority](../architecture/flutter-study-plugin-authority.json)
persists `HUMAN_REVIEW_P6_3` provenance, approved canonical repositories, seven
explicit human decisions, and conservative boundary retention rules. Application
composition, adapters, feature-local UI, examples, tests, generated files, and
ephemeral artifacts remain outside automatic extraction.

## Canonical comparisons

| Nested source unit | Approved canonical repository | Result |
| --- | --- | --- |
| `flutter_study:packages/gcode_core` | `gcode_core` | `IDENTICAL_ALREADY_CANONICAL` |
| `flutter_study:packages/file_picker_bridge` | `file_picker_bridge` | `IDENTICAL_ALREADY_CANONICAL` |

Both comparisons used complete Dart library content hashes and public export
comparison, not names. The host `pubspec.yaml` still points at nested paths,
while exact host import callsites consume each package public API. This is a
real dependency-adoption delta, not a source move. No contract extension,
implementation move, cleanup, or caller source edit is proposed.

## Revised plan

[P6.3 plan](../plans/flutter-study-plugin-decomposition-p6-3.json) contains four
tasks in two reversible adoption chains:

1. Adopt canonical `gcode_core` dependency, then validate host integration.
2. Adopt canonical `file_picker_bridge` dependency, then validate host integration.

Each chain has the exact host manifest and existing consumer import files as
allowed paths, a concrete `ADOPTION_ONLY` MigrationDelta, host validation, and
no destructive cleanup. Application file-picker controller/adapter remains in
the application boundary.

## Recommended P7 pilot candidate

`adoption:flutter_study:packages/gcode_core->gcode_core:adopt-dependency`
followed by its `validate-host` task.

It is the lower-risk candidate because it is pure core adoption, has three
precise existing host imports, changes only one dependency relationship, has no
MethodChannel/native boundary, and has no cleanup. The file-picker chain is
valid but excluded from the first pilot due to its platform-plugin boundary.

## Conservative outcomes

- Human KEEP_IN_APPLICATION / KEEP_CURRENT_BOUNDARY decisions generate no move.
- The example remains `NO_MIGRATION_REQUIRED`.
- No new plugin target was inferred.
- No canonical divergence was found in the two approved families.
- P6.1/P6.2 blockers outside approved authority remain non-executable.

## Validation and integrity

| Check | Result |
| --- | --- |
| Authority persistence and adoption-only tests | PASS |
| Full Agent Hub suite | PASS |
| `langgraph validate --config langgraph.json` | PASS — 5 graphs |
| Revised DAG validation | PASS |
| Business Git state | unchanged: file_picker_bridge 0, flutter_study 3, gcode_core 15 |
| Business writes | none |

## Next human review

Confirm the exact P7 pilot chain, host dependency path change, validation
commands, rollback boundary, and whether nested copies should remain after the
non-destructive pilot. P7 execution is not authorized by this report.
