# Capability Analyzer calibration P5.3

**Final status: READY_FOR_MORE_CALIBRATION**

## Generic algorithm changes

The Analyzer now seeds capabilities from bounded ContextPackage source-evidence files rather than collapsing all selected files in a development unit into one cluster. This preserves parser, controller, widget, contract, and platform anchors as separate reviewable nodes.

Ownership ordering now prioritizes route/service coordination, then adapter mapping, explicit platform contracts, UI surface, and pure parser/model/algorithm signals. CMake text alone remains `unknown`. Existing-unit matching now recognizes a public exported contract in a Registry unit when an incoming manifest path dependency provides an independent identity edge. Extraction evaluates adapter/unknown before new-unit proposals and separates reusable-widget ownership from destination selection.

No runtime Analyzer path reads human review files, candidate files, comparison files, or golden identifiers.

## Generic fixture and safety results

Generic fixture tests cover pure parser against unrelated controller signals, injected-service adapters, reusable widgets, route composition, platform contracts, and CMake-only unknown behavior. They use synthetic names only. All fixtures passed. P1–P5.2 regression tests also passed.

## Rebenchmark comparison

| Metric | P5.2 baseline | P5.3 result | Gate |
|---|---:|---:|---:|
| Ownership accuracy | 0.125 | 0.375 | >= 0.85 |
| Extraction accuracy | 0.00 | 0.375 | >= 0.80 |
| Target accuracy | 0.00 | 0.667 | informational |
| Unsupported promotions | 1 | 1 | 0 |

Three reviewed goldens now match fully:

- GOLDEN_003: platform contract and existing-unit move.
- GOLDEN_006: reusable public widget and existing-unit extension.
- GOLDEN_008: CMake-only unknown and `NOT_ENOUGH_EVIDENCE`.

## Remaining failure classes

- **Clustering:** GOLDEN_001, 002, 004, and 005 still lack file-overlapping Analyzer nodes for the independently bounded review evidence.
- **Ownership / unknown safety:** GOLDEN_007 detects its widget as reusable due to a package export; human truth is UI-only, and Analyzer still proposes `EXTEND_EXISTING_UNIT` despite reviewed extraction `UNKNOWN`. This remains an unsupported promotion.

The next calibration should improve generic source-anchor selection for direct contract/controller/route files and add a generic “public widget destination unresolved” condition: public export establishes reuse potential but must not itself establish a package destination.

## Deterministic quality and integrity

Deterministic Shadow metrics remain 1.00 for repository precision/recall, evidence coverage, rule coverage, and unknown preservation; negative false-positive rate remains 0.00. All 20 Agent Hub tests passed and all four LangGraph graphs validate. Business Git porcelain counts remain unchanged at `0 / 3 / 15`.

Migration Planner remains unauthorized because the reviewed architecture gate and UNKNOWN-promotion safety gate do not pass.
