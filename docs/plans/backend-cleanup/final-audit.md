# Final backend cleanup audit

This audit checks the original findings against current source and behavioral evidence. Implementation checklist completion does not prove whole-goal completion. The cleanup worktree is on `codex/backend-safe-cleanup`; this first final-audit pass inspected production commit `c88bd00`.

## Fresh regression evidence

| Scope | Result | Log |
| --- | --- | --- |
| `tests/unit`, excluding persistence | 1,123 passed | `/tmp/grafy-final-unit.log` |
| `tests/unit/persistence`, separate process | 199 passed, 41 skipped | `/tmp/grafy-final-persistence.log` |
| Workspace authorization integration, template integration, immediate module checkpoint | 15 passed | `/tmp/grafy-final-auth-creation.log` |

Persistence skips are not passes. Dedicated PostgreSQL/concurrency evidence from earlier batches still needs reconciliation with the final gate. Browser verification and the remaining integration/packaging scope are also open.

## Requirement-by-requirement source review

| Finding | Current source evidence | Behavioral evidence inspected | Final audit status |
| --- | --- | --- | --- |
| 1. Workspace authorization | `application/identity.py:authorize_workspace` checks credential binding before locking, then active user, membership and capability. `application/collaboration.py:_authorize` delegates and retains rejection audit handling. Copies sort all workspace requirements before invoking that boundary in the same transaction. SavedGraphService calls canonical authorization. | `test_target_bound_pat_cannot_copy_graph_from_another_workspace` verifies browser copy success, PAT rejection, unchanged target graphs and a rejection audit. Unit copy tests cover lock ordering. Fresh authorization integration passes. | Source and focused behavior verified. The copy uses an explicit sorted loop around the audit-preserving authorization boundary, rather than `authorize_workspaces` directly; this retains the required lock order and rejection audit. |
| 2. Checkpointed creation | `application/graph_creation.py:stage_checkpointed_graph` stages graph, revision, head and checkpoint mapping without committing. Collaboration bootstrap/copy, templates and module import call it within their owning transactions. | Bootstrap, rollback and checkpoint unit tests pass. Fresh `test_instantiated_template_is_already_checkpointed` and `test_imported_module_is_already_checkpointed` verify the original redundant-revision problem. | Source and focused behavior verified; final stale-path deletion scan remains part of the whole-source gate. |
| 3. Publication consistency | Publication workflow passes the reviewed base revision into `PluginReleaseService`; `_publish` checks it after workspace authorization locks the transaction. Persistence `lock_system_revocation` orders revocation, saved-execution and transient-marker locks, deduplicates activity, and uses SQLite `BEGIN IMMEDIATE`. Manager inline execution registers before preflight and retains activity after unconfirmed cleanup. | Reviewed publication race test is in the passing unit suite. Current persistence suite covers available SQLite fence/cleanup cases. Prior dedicated PostgreSQL and actual execution race evidence is in the batch ledger. | Source paths reviewed; final PostgreSQL and execution-entry-point evidence reconciliation remains open. |
| 4. Plugin ownership | `grafy_api/plugins` has publication, runtime, profiles and explicit compatibility owners. SQL baseline/cutover live in persistence. Egress broker has its own application. Import-boundary tests reject runtime dependencies on routes or historical host tooling and enforce plugin dependency ownership. | Plugin authoring, publication, compatibility, cutover CLI and architecture tests pass in the fresh unit suite. | Ownership source verified; CLI/wheel/live-host final gate remains open. |
| 5. Execution ownership | Compilation, manager, coordinator, node execution, history, materialization and requests live in `grafy_api/execution`. Persistent invocation cache lives in core runtime. Architecture tests enforce route/framework independence and public request/event identity. | Execution unit tests and architecture checks pass; recent graph/module integration batch passed 696 tests before this audit. | Ownership verified; final execution integration/packaging gate remains open. |
| 6. Execution preparation | `GraphPreflight.validate` resolves exact releases into a per-run map, rejects missing secret context before saved revision lookup, validates submitted topology, and passes the map to compilation through `GraphRunContext`. Both saved and nested-module requests use `RunNodeRequest.from_saved_node`. | Fresh preflight/compiler unit tests pass. Source order was inspected, not inferred from filenames. | Source and unit behavior verified; include execution integration in final gate. |
| 7. Catalog | Route gathers `ModuleLibraryService.catalog_definitions` and one release catalog result, then serializes a validated `CatalogSnapshot`. SQL catalog query joins selection/release/installation/revocation in one operation. Application snapshot owns readiness and composition. | Readiness/catalog and architecture unit tests pass. | Ownership and query source reviewed; final legacy-symbol scan and catalog integration remain open. |
| 8. Graph contracts | Canonical `SavedGraphDocument` is used by collaboration domain/application and frontend shared head state. `CollaborativeHeadResponse.from_head` is the backend legacy flattening/pin adapter. HTTP and room outputs call it. Shared domain rules preserve legacy aliases; acceptance differences and retained inline checks are documented. | 607 frontend tests and production build; 696 backend integration/unit tests; exact OpenAPI and generated-client comparisons; 96 tests with asserted extracted-wheel imports. Current unit suite also includes 43 transport contracts. | Implementation evidence verified. Browser runtime check remains open. Retained legacy schema declarations are an explicit compatibility choice, not a claim that v1 has been retired. |
| 9. Artifact availability | `ArtifactAvailability.load` deduplicates IDs and loads rows with `get_many`. Batch resolution checks exact identity and memoizes format-specific accessibility. Materialization uses that batch. `PersistentInvocationCache` separately checks hashes and collection integrity, removing stale generations conditionally. | Availability and invocation-cache unit tests pass. Source inspection confirms accessibility has not replaced stronger cache validation. | Source and unit behavior verified; include artifact integration in final gate. |
| 10. Spatial contracts | Pending final source review. | Earlier batch evidence exists; fresh spatial unit tests pass. | Open. |
| 11. Persistence | Pending final source review of serializers, ownership and bulk hydration. | Fresh persistence results above. | Open. |
| 12. Ports and in-memory persistence | Pending final source review of transaction requirements, isolation and SDK exports. | Fresh unit suite includes core runtime and architecture tests. | Open. |
| 13. Host infrastructure | Pending final source review of realtime, diagnostics, authentication cleanup, workspace results, secrets and uploads. | Fresh unit suite passes. | Open. |
| 14. Composition and deletions | Pending final source review of runtime lifecycle, registry state and deleted helpers. | Fresh unit suite passes. | Open. |

Source paths above are relative to their owning package under `apps/api/src/grafy_api`, `libs/core/src/grafy_core`, or `libs/persistence/src/grafy_persistence`. Exact changed-owner links and historical batch evidence remain in the implementation checklist.

## Remaining completion gates

- Finish source review for findings 10–14 and resolve any contradictions.
- Inspect preserved release/installation/selection, Module/Template, coordinator/node/scalar, raw/validated cache, Local/S3 and host/guest boundaries.
- Complete broad integration and packaging checks, including the relevant PostgreSQL and Docker evidence; record every exclusion or baseline failure.
- Verify the migrated frontend flow in a running browser.
- Reconcile architecture documentation and all explicit original-audit requirements with final source, then check the overall completion gates only if each is proven.
