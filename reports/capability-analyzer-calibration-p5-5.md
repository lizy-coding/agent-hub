# Capability Analyzer Calibration P5.5

## Result

`READY_FOR_MORE_CALIBRATION`

The four missing direct anchors now resolve through generic, bounded source
evidence.  The deterministic unit suite passed after the change.  The complete
benchmark runner was started repeatedly but did not complete within this host's
tool execution window; its persisted `shadow-results.json` therefore remains a
P5.4 result and must not be used as P5.5 evidence.  A normal unrestricted local
run of the runner is still required before promotion to the Migration Planner.

## Failure layer before change

| Golden | Layer | P5.5 result |
| --- | --- | --- |
| 003 | Existing-unit matching was hidden by parent-unit attribution. | Package-owned implementation resolves to `MOVE_TO_EXISTING_UNIT`. |
| 004 | Controller definition was dropped after broad matches consumed the file budget. | Controller anchor resolves as `adapter` / `ADAPTER_ONLY`. |
| 005 | Route root definition was dropped by the same bounded selection order. | Router composition resolves as `application_orchestration` / `KEEP_IN_APPLICATION`. |
| 006 | Parent unit claimed nested package sources; public contract was therefore not evaluated at its owner. | Public scaffold composition resolves as `reusable_capability` / `EXTEND_EXISTING_UNIT`. |

## Generic changes

- Context search orders exact source matches above documentation and metadata.
- Parent development units no longer attribute files owned by a nested registered
  development unit.
- Each candidate unit reserves at most four semantic definition anchors before
  broad matches consume the global file budget.  Anchors remain path-guarded and
  source-backed.
- Export evidence is source-specific: a barrel export must name the exact source
  file, rather than proving visibility for every file in the unit.
- Reusable UI requires both exact public export and a public constructor-level
  composition contract rooted in scaffold-like composition.  Public visual leaves
  remain `ui_only` and retain `UNKNOWN` extraction.

## Targeted evidence results

| Golden | Ownership | Extraction | Target |
| --- | --- | --- | --- |
| 003 | platform_plugin | MOVE_TO_EXISTING_UNIT | registered package unit |
| 004 | adapter | ADAPTER_ONLY | none |
| 005 | application_orchestration | KEEP_IN_APPLICATION | none |
| 006 | reusable_capability | EXTEND_EXISTING_UNIT | registered package unit |
| 007 regression check | ui_only | UNKNOWN | none |

## Tests and integrity

- `./.venv/bin/python -m unittest discover -s tests -q`: passed after the P5.5
  source and synthetic-fixture changes.
- Added synthetic coverage for injected service adapter, root router composition,
  reusable scaffold contract, and exported visual leaf.
- Business Git status remained unchanged: `file_picker_bridge=0`,
  `flutter_study=3` pre-existing entries, `gcode_core=15` pre-existing entries.
- No review/candidate/golden data is read by the runtime analyzer or resolver.

## Required next verification

Run the complete ShadowBenchmarkRunner in an execution environment that permits
the full read-only scan to complete, then regenerate
`benchmarks/shadow-results.json`.  Required gate: deterministic metrics all
`1.00`, ownership `>= 0.85`, extraction `>= 0.80`, and unsupported promotions
`0`.
