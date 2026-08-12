# P5.6.1 Resumable Shadow Benchmark Execution

## Readiness decision

`READY_FOR_MIGRATION_PLANNER`

Run `p5-6-1-20260812T034824Z-62c8281f` completed all six Shadow cases and all
eight reviewed Golden cases. The final aggregate was atomically published to
`benchmarks/shadow-results.json` only after all fourteen valid case checkpoints
and the aggregate existed.

## Resumability implementation

- Checkpoints live in `benchmarks/runs/<run_id>/cases/<case_id>.json`.
- Each checkpoint is written to a temporary file, fsynced, and atomically
  renamed. A result is `COMPLETE` only when its schema and content hash verify.
- Manifest identity includes the source revision; Analyzer, Resolver, and
  benchmark hashes; scenario configuration; candidate and reviewed-truth hashes;
  Registry snapshot identity; and the ordered case IDs.
- Any identity mismatch invalidates the prior manifest rather than mixing
  artifacts. Valid `COMPLETE` checkpoints are skipped on resume.
- The orchestration calls the existing bounded `ShadowBenchmarkRunner` per-case
  methods; it does not introduce a separate resolver, analyzer, or workspace
  scan.

## Run identity and execution

- Run ID: `p5-6-1-20260812T034824Z-62c8281f`
- Source revision: `abcd32aecb05efb49598d1ec74d295a26161289c`
- Manifest status: `COMPLETE`
- Created: `2026-08-12T03:48:24.618984+00:00`
- Completed: `2026-08-12T03:49:54.938163+00:00`
- First execution persisted SHADOW_001–005 before interruption; resume skipped
  those five valid checkpoints and executed SHADOW_006 plus GOLDEN_001–008.
- Executed cases: 14 total across the resumable run; skipped valid cases on the
  resume: 5; invalidated runs: 0.

## Validation and integrity

| Check | Result |
| --- | --- |
| Agent Hub unit tests | PASS |
| LangGraph config validation | PASS — 4 graphs |
| Workspace boundary violations | 0 observed |
| file_picker_bridge porcelain | 0 → 0 |
| flutter_study porcelain | 3 → 3 |
| gcode_core porcelain | 15 → 15 |
| Business writes / worktrees / commits | none |

## Aggregate metrics

| Metric | Result |
| --- | ---: |
| Repository precision / recall | 1.00 / 1.00 |
| Evidence coverage | 1.00 |
| Rule coverage | 1.00 |
| Unknown preservation | 1.00 |
| Negative false-positive rate | 0.00 |
| Ownership accuracy | 1.00 |
| Extraction accuracy | 1.00 |
| Extraction target accuracy | 1.00 |
| Unsupported promotions | 0 |
| Architecture disagreements | 0 |

All SHADOW_001–006 passed. GOLDEN_001–008 all matched reviewed truth; in
particular GOLDEN_007 remained `ui_only` with `UNKNOWN` extraction, and
GOLDEN_008 remained `unknown` with `NOT_ENOUGH_EVIDENCE`.

## Performance

- Total recorded case duration: 89.449s.
- Slowest cases: SHADOW_005 (8.442s), SHADOW_002 (8.204s), and SHADOW_001
  (8.151s).
- Per-case durations and bounded context counters are included in
  `benchmarks/shadow-results.json` and the run checkpoint files.

## Published artifact

- [shadow-results.json](../benchmarks/shadow-results.json)
- SHA-256: `a3b1476899a8e4a1c5e7e9d9367de7809aa68724ab727acb0e1a32fb2f839659`
