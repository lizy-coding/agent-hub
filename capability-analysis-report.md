# Capability Analyzer P4 report

**Final status: READY_FOR_SHADOW_BENCHMARK**

## Implemented modules

- `capability/analyzer.py`: bounded ContextPackage consumption, clustering, coupling, ownership, overlap matching, extraction assessment, and validation.
- `schemas/models.py`: `CapabilityNode`, `WorkspaceCapabilityMatch`, `ExtractionAssessment`, `CapabilityAnalysis`, and coupling contracts.
- `graphs/capability_analysis.py`: read-only capability-analysis graph.
- `graphs/registered_capability.py` and `langgraph.json`: registration of `capability_analysis` while retaining the two previous graphs.

## CapabilityAnalysis and pipeline

The analyzer calls `ContextResolver.resolve_context` and Registry public API only. It reads only files already selected by the bounded ContextPackage, rejects out-of-bound paths, and does not rescan the full Workspace or persist source text. The graph topology is:

```text
START -> resolve_context -> discover_capabilities -> analyze_coupling
-> classify_ownership -> match_workspace_capabilities
-> assess_extraction -> build_analysis -> END
```

Nodes store only structured decisions, evidence references, paths, symbols, and metrics.

## Capability map and ownership

For both runtime cases, six evidence-backed capability clusters were produced from the target's selected development units. Ownership decisions are driven by bounded source signals: session/navigation/state coordination is application orchestration; method-channel/platform boundaries are platform-plugin candidates; parser/model/algorithm evidence without UI is shared-core evidence; and insufficient evidence remains unknown.

No directory, filename, repository name, or package name alone creates a capability or overlap decision.

## Coupling, matches, and extraction

Coupling is recorded per node across UI, application state, platform, and external contract dimensions. Ten workspace matches were derived from existing Registry dependency edges and carry their manifest evidence paths. Strong cross-repository matches are required before `MOVE_TO_EXISTING_UNIT`; application orchestration is always `KEEP_IN_APPLICATION`; all extraction output remains an assessment, never a migration action.

## Runtime cases

| Case | Capabilities | Matches | Keep in app | Extraction candidates | Unknowns | Bounded files read |
|---|---:|---:|---:|---:|---:|---:|
| CAP_001 | 6 | 10 | 2 | 2 | 5 | 23 |
| CAP_002 | 6 | 10 | 3 | 2 | 4 | 26 |

Both analyses passed `validate_capability_analysis()`. Unknown CMake facts remain unknown without evidence; no absent `AGENTS.override.md` or unresolved external path was converted into a positive match.

## Tests and integrity

`python -m unittest discover -s tests -v` passed all 11 tests. Coverage includes P1/P2/P3 regressions, ContextPackage consumption, bounded reads, ownership/coupling classification, unknown preservation, evidence traceability, workspace matching evidence, structured extraction, path isolation, and registry-storage independence.

`langgraph validate --config langgraph.json` validates all three graphs. `workspace_bootstrap` regression passed. Business Git states are unchanged: `file_picker_bridge` 0, `flutter_study` 3 existing, `gcode_core` 15 existing porcelain entries.

## Blockers for shadow benchmark

No implementation blocker. Shadow benchmark scenarios should retain explicit expected evidence/unknown assertions, particularly for CMake-derived units and external unresolved paths.
