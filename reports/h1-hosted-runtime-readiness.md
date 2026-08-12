# H1 Hosted Runtime Readiness

## Final status

`READY_FOR_H2_HOSTED_EXECUTION_CONTRACT`

## Runtime model

`RuntimeWorkspaceProvider` now maps stable `repository_id` values to ephemeral
runtime checkout paths. Runtime models support LOCAL and HOSTED environments,
repository roles, managed/writable policy, source metadata, and contained
development units. Absolute paths are runtime data, not repository identity.

- PRIMARY managed repository: `flutter_study`.
- Nested packages: internal development units in the primary repository
  transaction.
- External `gcode_core` and `file_picker_bridge`: read-only REFERENCE
  repositories.
- Cross-repository writes are blocked for the Hosted MVP.

## Adaptations

- Added runtime configuration with environment-variable overrides.
- Added safe repository-relative path resolution with escape rejection.
- Bootstrap graph now emits RuntimeWorkspace alongside existing health checks.
- Existing Registry/Context/Analyzer retain their bounded behavior using the
  injected runtime workspace configuration.
- Added the `development` graph as a no-write hosted dry-run skeleton; it reaches
  `DRY_RUN_REVIEW_READY` and explicitly disables execution in H1.
- Existing P7 executor isolation remains intact; H1 does not authorize business
  writes or cross-repo migration.

## Path coupling audit

[Audit JSON](../analysis/hosted-readiness/path-coupling-audit.json) records that
local Mac paths remain only in local development configuration and historical
artifacts. Core runtime code contains no fixed `/Users/forest/code/langGraph`
architectural constant.

## Hosted simulation

The provider built a HOSTED RuntimeWorkspace at an alternate temporary root,
resolved `flutter_study` solely by repository ID, enforced writable PRIMARY
policy, rejected reference writes and path escape, and ran the development graph
to dry-run review state. No original business checkout was required by that
runtime path.

## Validation

| Check | Result |
| --- | --- |
| Runtime workspace unit tests | PASS |
| Full Agent Hub suite | PASS |
| Local bootstrap/development dry run | PASS |
| Hosted alternate-root simulation | PASS |
| `langgraph validate --config langgraph.json` | PASS — 7 graphs |
| Business Git integrity | unchanged: flutter_study 3, gcode_core 15, file_picker_bridge 0 |

## Deferred items and H2 requirements

P7.2 Pub workspace canonicalization, external-plugin adoption, all external
repository writes, credentials-backed Git materialization, and hosted business
execution remain deferred. H2 must define an execution authorization contract,
task-worktree lifecycle, source materialization/credential policy, and explicit
validation/review gates before enabling any business write.
