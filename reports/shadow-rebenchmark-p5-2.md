# Shadow rebenchmark P5.2

**Final status: READY_FOR_ANALYZER_CALIBRATION**

## Reviewed truth integration

The benchmark loads [review-decisions.json](../benchmarks/architecture_goldens/review-decisions.json) separately from the immutable proposal [candidates.json](../benchmarks/architecture_goldens/candidates.json). Eight approved human decisions were scored. `UNKNOWN` is preserved as a first-class extraction truth; it is not treated as `NOT_ENOUGH_EVIDENCE` and no target is scored for it.

## Deterministic benchmark results

| Metric | Result |
|---|---:|
| Repository precision | 1.00 |
| Repository recall | 1.00 |
| Evidence coverage | 1.00 |
| Rule coverage | 1.00 |
| Unknown preservation | 1.00 |
| Negative false-positive rate | 0.00 |

All six Shadow cases passed their independent deterministic assertions.

## Reviewed architecture results

| Metric | Result | Gate |
|---|---:|---:|
| Reviewed golden count | 8 | — |
| Ownership accuracy | 0.125 | >= 0.85 |
| Extraction accuracy | 0.00 | >= 0.80 |
| Extraction target accuracy | 0.00 | informational / scored where applicable |
| Unsupported architecture promotions | 1 | 0 required |
| Architecture disagreements | 8 | informational |

### Failed goldens

- **GOLDEN_001, 002, 004, 005, 008:** clustering failures. The Analyzer did not select a capability with overlap to the bounded candidate evidence, so prediction was `UNKNOWN`.
- **GOLDEN_003:** extraction failure. Ownership matched `platform_plugin`, but the Analyzer proposed `NEW_PLUGIN_CANDIDATE` despite the reviewed existing package target.
- **GOLDEN_006:** ownership/extraction failure. It selected `unknown` and `NOT_ENOUGH_EVIDENCE` instead of the reviewed reusable existing-unit boundary.
- **GOLDEN_007:** ownership/extraction failure and unsupported promotion. Reviewed extraction is `UNKNOWN`; Analyzer produced `KEEP_IN_APPLICATION`, which is a positive extraction decision and therefore a safety failure.

The failures are Analyzer classification/cluster/match/extraction failures, not truth-separation, registry, Context Resolver, or deterministic-evidence failures. No Analyzer heuristic was changed to match a golden ID or repository name.

## Gate and next stage

Migration Planner is **not** authorized. The required next stage is Analyzer calibration focused on generic evidence-to-capability clustering, existing-unit target matching, and preserving `UNKNOWN` when the source evidence cannot resolve a package-boundary decision. Re-run this benchmark after calibration; do not weaken UNKNOWN safety or change human review truth.

## Verification and integrity

- 18 Agent Hub tests passed.
- `langgraph validate --config langgraph.json` validates all four existing graphs.
- `workspace_bootstrap` regression passed.
- Business Git porcelain counts before/after are unchanged: `file_picker_bridge` 0, `flutter_study` 3, `gcode_core` 15.
- No business source, migration plan, worktree, commit, push, merge, or code migration was performed.
