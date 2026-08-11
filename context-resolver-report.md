# Context Resolver P3 report

**Final status: READY_FOR_CAPABILITY_ANALYZER**

## Implemented modules

- `context/resolver.py`: `ContextResolver`, bounded `RepositorySearcher`, `RuleResolver`, deterministic `EvidenceScorer`, limits, and package validation.
- `schemas/models.py`: evidence-bearing `ContextPackage` and its candidate/file/symbol/rule/unknown contracts.
- `graphs/context_analysis.py`: read-only `START -> load_registry -> resolve_candidates -> search_evidence -> resolve_rules -> build_context_package -> END` graph.
- `graphs/registered_context.py` and `langgraph.json`: `context_analysis` registration while retaining `workspace_bootstrap`.

## Resolver pipeline and search strategy

The resolver consumes `agent_hub.projects.api` only; it never reads the persisted Registry JSON directly. It first obtains Registry units and edges, then searches only candidate unit directories using resolved-path guards. Search is lexical and exact-token first, records workspace-relative `file:line` evidence, excludes VCS/build/generated/runtime directories, skips symlinks, deduplicates results, and caps candidates, files, symbols, and dependency depth.

Only manifest-backed Registry dependency/dependent edges expand scope. Expansion does not classify a neighbor as required by itself.

## ContextPackage schema

Each package contains the original requirement/optional repository target; repository and unit scope; classified candidates; bounded files and symbols; applicable rule metadata; evidence-bearing dependency edges; explicit unknowns; confidence; and size metrics. No business source body or full-workspace dump is stored in the package.

## Confidence rules

Confidence is deterministic: dependency evidence and exact symbol/callsite evidence each contribute two points; rules and confirmed files contribute one; unresolved core relationships reduce two. A name-only candidate is never above `LOW`. Missing evidence creates an explicit unknown rather than a confirmed relationship.

## Runtime validation

| Case | Result |
|---|---|
| CTX_001: capability/plugin relationship context | `HIGH`; 9 candidates, 22 selected files, 72 symbols, 5 evidence-bearing dependencies, 1 applicable rule, 3 explicit unknowns |
| CTX_002: GCode callsite/dependency context | `HIGH`; 9 candidates, 25 selected files, 70 symbols, 5 evidence-bearing dependencies, 1 applicable rule, 3 explicit unknowns |

Both requests targeted the supplied repository at runtime; no project-specific branch exists in resolver source. The `context_analysis` Graph compiled and returned a `HIGH` ContextPackage for the GCode input.

## Candidate and selected-context summary

The selected target repository has nine manifest-backed development units. Registry neighborhood evidence produced five relevant path dependency/dependent edges. Exact source/import/callsite matches selected 22–25 files within the configured limits. The repository-root `AGENTS.md` was returned as scoped rule metadata only.

## Unknowns

Three CMake-derived units have no exact requirement evidence for both validation inputs. They remain `unknown`; their names and directories were not used as capability proof. No `AGENTS.override.md` exists in the Registry, and no unresolved external manifest path was represented as a dependency edge.

## Tests and integrity

`python -m unittest discover -s tests -v` passed 9 tests. Coverage includes bootstrap regression, Registry regression, candidate resolution, bounded dependency/dependent use, symbol and import/callsite search, name-only confidence cap, unknown preservation, rule lookup, limits, deduplication, Hub isolation, workspace path boundaries, symlink escape handling, storage independence, and ContextPackage validation.

`langgraph validate --config langgraph.json` reports two valid graphs. `workspace_bootstrap` still executes successfully. Business Git state before and after was unchanged: `file_picker_bridge` 0 entries, `flutter_study` 3 pre-existing entries, and `gcode_core` 15 pre-existing entries.

## Blockers for Capability Analyzer

None for Context Resolver input readiness. A later Capability Analyzer should consume the explicit `unknown` records rather than treating CMake directory names or unresolved external paths as capabilities.
