# Shadow Benchmark P5 report

**Final status: READY_FOR_MORE_SHADOW_CASES**

## Implemented harness

- `benchmarks/shadow_cases/cases.json`: six independently authored scenarios with manifest/Registry/rule-based assertions.
- `benchmark/runner.py`: scenario loading, Context and Capability invocation, deterministic evidence scoring, metric aggregation, and result validation.
- `graphs/shadow_benchmark.py`: analysis-only shadow benchmark graph.
- `langgraph.json`: preserves the previous three graphs and registers `shadow_benchmark`.
- `benchmarks/shadow-results.json`: persisted outcome summary.

## Ground truth and scenario list

The six scenarios cover broad inventory, GCode cross-unit context, file import, application orchestration, platform-native boundary, and a negative nonexistent-capability query. Expected repository, manifest path, and AGENTS scope facts come independently from Registry/manifest/filesystem evidence; they were not copied from capability-analysis outputs. Ownership and extraction expectations deliberately remain `unscored` with `pending_review` because no reviewed architecture goldens exist.

## Per-case results and quality metrics

All `SHADOW_001` through `SHADOW_006` passed their deterministic assertions. Aggregate scored metrics:

| Metric | Result |
|---|---:|
| Repository precision | 1.00 |
| Repository recall | 1.00 |
| Evidence coverage | 1.00 |
| Rule coverage | 1.00 |
| Unknown preservation | 1.00 |
| Negative false-positive rate | 0.00 |

There were no evidence failures. Empty evidence denominators in cases without deterministic evidence expectations are reported as unscored rather than invented as perfect scores.

## Context efficiency and bounds

The runner invokes the existing bounded Context Resolver and Capability Analyzer. It records candidate repositories, searched/selected file counts, symbols, and evidence count per case. Default file/symbol/dependency-depth limits are supplied per scenario; no full-workspace dump, AST index, source persistence, or business write is performed.

## Readiness gate

All hard integrity and deterministic evidence conditions passed: six cases ran, no workspace-boundary violation was observed, unsupported positive promotion was zero in the negative case, rule resolution errors were zero, and business Git state was unchanged.

The status is nevertheless **READY_FOR_MORE_SHADOW_CASES**, not `READY_FOR_MIGRATION_PLANNER`: capability ownership and extraction decisions have no independently reviewed architecture ground truth and therefore remain unscored by design. The recommended next step is to add reviewed golden assertions for a representative set of ownership/extraction decisions, then rerun the same harness.

## Tests and integrity

All 13 Agent Hub tests passed. `langgraph validate --config langgraph.json` validates four graphs. Existing `workspace_bootstrap`, Context Resolver, and Capability Analyzer regressions passed. Business Git porcelain counts remained `0 / 3 / 15`; no business source, commit, merge, push, worktree, or migration was created.
