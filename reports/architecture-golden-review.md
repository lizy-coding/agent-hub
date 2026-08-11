# Architecture golden candidate review

All eight entries are **pending_review**. Their proposed ownership and extraction values are candidate questions, not benchmark truth. Review each using the listed bounded file/symbol/callsite/manifest evidence; do not use the Analyzer comparison as approval evidence.

## Review instructions

For every case, record:

```text
ownership: ACCEPT | CHANGE:<value> | UNKNOWN
extraction: ACCEPT | CHANGE:<value> | UNKNOWN
note: optional
```

## Candidates

| ID | Capability | Proposed ownership | Proposed extraction | Key independent evidence |
|---|---|---|---|---|
| GOLDEN_001 | GCode parser public contract | shared_core | MOVE_TO_EXISTING_UNIT → `packages/gcode_core` | public export + root path dependency |
| GOLDEN_002 | GCode player orchestration | application_orchestration | KEEP_IN_APPLICATION | controller owns picker and pipeline |
| GOLDEN_003 | File picker platform contract | platform_plugin | MOVE_TO_EXISTING_UNIT → `packages/file_picker_bridge` | `MethodChannelFilePicker implements FilePickerService` + manifest |
| GOLDEN_004 | File picker controller | adapter | ADAPTER_ONLY | controller accepts service and owns module-local field |
| GOLDEN_005 | Root route composition | application_orchestration | KEEP_IN_APPLICATION | `GoRouter(routes: AppRouteTable.routes)` |
| GOLDEN_006 | LearningScaffold | reusable_capability | EXTEND_EXISTING_UNIT → `packages/flutter_study_learning` | exported StatelessWidget + module callsite |
| GOLDEN_007 | GcodeCanvas rendering | ui_only | EXTEND_EXISTING_UNIT → `packages/gcode_core` | exported StatelessWidget + visualizer callsite |
| GOLDEN_008 | Windows CMake boundary | unknown | NOT_ENOUGH_EVIDENCE | CMake descriptor only; no channel/FFI/host contract located |

## Alternatives and unresolved items

The machine-readable candidate file provides alternatives and evidence needed to resolve each uncertainty. In particular, `GOLDEN_008` must remain unknown unless a platform-channel, FFI, or explicit host API callsite is independently established.

## Analyzer comparison

[Analyzer comparison JSON](../benchmarks/architecture_goldens/analyzer-comparison.json) is diagnostic only. It shows disagreements for seven cases and does not alter review state. This is expected: the current Analyzer performs bounded heuristic classification, whereas candidates were independently authored from source and manifest facts.

## Coverage and missing categories

Ownership coverage: application orchestration, reusable capability, shared core, platform plugin, adapter, UI-only, and unknown are all represented. Extraction coverage: KEEP, MOVE, EXTEND, ADAPTER_ONLY, and NOT_ENOUGH_EVIDENCE are represented.

`NEW_SHARED_CORE_CANDIDATE` and `NEW_PLUGIN_CANDIDATE` are intentionally missing. Existing package boundaries already cover the evidenced parser/platform contract cases, and CMake presence alone is insufficient for a new-plugin proposal. No evidence-supported candidate should be invented solely to complete a category matrix.
