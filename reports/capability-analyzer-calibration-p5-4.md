# Capability Analyzer calibration P5.4

**Final status: READY_FOR_MORE_CALIBRATION**

## Root causes and responsible-layer changes

The remaining clustering failures were primarily Context Resolver source-selection omissions: broad unit scanning consumed the bounded file budget before direct controller/router/contract anchors from the root application unit could be selected. The Resolver now processes root composition units first and adds up to three bounded semantic anchors per unit only when the request has semantic intent or exact evidence already exists. This preserves negative-query false-positive control.

Analyzer calibration now separates export identity from destination fit. A public widget remains `ui_only` unless source evidence establishes behavior beyond a rendering surface. `ui_only` now returns extraction `UNKNOWN`; public export or current package location cannot authorize `EXTEND_EXISTING_UNIT`.

## Before and after

| Metric | P5.3 | P5.4 | Gate |
|---|---:|---:|---:|
| Ownership accuracy | 0.375 | 0.625 | >= 0.85 |
| Extraction accuracy | 0.375 | 0.50 | >= 0.80 |
| Target accuracy | 0.667 | 0.333 | informational |
| Unsupported promotions | 1 | 0 | 0 |
| Architecture disagreements | 5 | 4 | informational |

GOLDEN_001, 002, 007, and 008 now match their reviewed ownership/extraction truth. The UNKNOWN destination safety regression is eliminated: the public rendering widget equivalent returns `UNKNOWN` extraction rather than a positive target decision. CMake-only behavior remains `unknown` / `NOT_ENOUGH_EVIDENCE`.

## Remaining generic failures

- Adapter and route controller anchors still need a stronger direct-definition/callsite selection relation to reach the exact reviewed file scope.
- Existing package platform identity is discovered, but destination-fit evidence must be distinguished from identity more consistently for some contract cases.
- Reusable UI requires a generic non-render responsibility/contract signal; the current bounded source selection still classifies one scaffold case as UI-only.

These are generic anchor, contract-fit, and responsibility-classification gaps. No golden ID, repository name, business domain name, or human review file is read by Analyzer runtime.

## Verification

- All 20 Agent Hub tests passed, including synthetic generic fixtures, deterministic shadow regression, path boundaries, Registry, Context Resolver, and bootstrap regression.
- Four LangGraph graph registrations remain valid.
- Deterministic metrics remain 1.00 for repository precision/recall, evidence/rule coverage, and unknown preservation; false-positive rate remains 0.00.
- Business Git porcelain counts are unchanged: `0 / 3 / 15`.

Migration Planner remains unauthorized because the reviewed architecture accuracy gates are not met, despite UNKNOWN safety now passing.
