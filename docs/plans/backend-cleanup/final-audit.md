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
| 8. Graph contracts | Canonical `SavedGraphDocument` is used by collaboration domain/application and frontend shared head state. `CollaborativeHeadResponse.from_head` is the backend legacy flattening/pin adapter. HTTP and room outputs call it. Shared domain rules preserve legacy aliases; acceptance differences and retained inline checks are documented. | 607 frontend tests and production build; 696 backend integration/unit tests; exact OpenAPI and generated-client comparisons; 96 tests with asserted extracted-wheel imports. Current unit suite also includes 43 transport contracts. | Implementation evidence verified. Browser runtime check passed in the production-build smoke below. Retained legacy schema declarations are an explicit compatibility choice, not a claim that v1 has been retired. |
| 9. Artifact availability | `ArtifactAvailability.load` deduplicates IDs and loads rows with `get_many`. Batch resolution checks exact identity and memoizes format-specific accessibility. Materialization uses that batch. `PersistentInvocationCache` separately checks hashes and collection integrity, removing stale generations conditionally. | Availability and invocation-cache unit tests pass. Source inspection confirms accessibility has not replaced stronger cache validation. | Source and unit behavior verified; include artifact integration in final gate. |
| 10. Spatial contracts | `spatial_contracts.py` owns persisted models used by API and GIS. `spatial_storage.load_feature_collection` reconstructs one complete features collection and checks logical byte length/hash. Both API artifact service and GIS persistence call it with their own payload/metadata types. Deployment-specific readers remain with their callers. | Fresh spatial contract unit tests verify producer/reader differences, legacy payloads, geometry and bounds. | Source and unit behavior verified; artifact/GIS integration remains in the broad integration gate. |
| 11. Persistence | `column_types.py` has typed Pydantic JSON and string-enum implementations, while UTC datetime and artifact-output serializers remain specialized. Schema and repositories have matching feature owners and one metadata bootstrap. `_hydrate_executions` batches composite identities, orders nodes by position and preserves input record order for queue/list/interruption callers. | Fresh persistence suite: 199 passed, 41 optional cases skipped. | Source and SQLite behavior verified; PostgreSQL evidence reconciliation remains open. |
| 12. Ports and in-memory persistence | Artifact contracts live in `ports/artifacts.py`; `TransactionPort` owns lifecycle and SavedGraphUnitOfWorkPort explicitly requires materialized outputs. `runtime/in_memory.py` clones state under a transaction lock, stores entered state in a ContextVar, restores on rollback and releases the lock on exit. It remains production runtime code for the guest. | Fresh core runtime and compatibility/import tests pass. | Source and unit behavior verified; final guest/package verification remains open. |
| 13. Host infrastructure | Realtime owns room/publishing code; HTTP diagnostics calls authentication-owned malformed callback cleanup. Workspace routes import their own response models and use complete application results without reopening SQL transactions. NodeSecretService and StagedUploadService have cohesive application owners. Upload batch failure deletes staged paths; persistence commits the batch once. | Fresh unit suite covers diagnostics, authentication cleanup, secrets and upload rollback. Architecture tests scan these owners for route dependencies. | Source and unit behavior verified; broad auth/secret/upload integration remains open. |
| 14. Composition and deletions | AppResources retains WorkbenchComponents and closes rooms, execution manager, plugin runtime and artifacts in order. Registry stores immutable family declarations plus lookup/collision indexes. InstalledPluginRelease retains pair validation and the meaningful descriptor-digest guard. API storage composition selects Local/S3 directly; the public factory remains for supported callers. Tables and collections share `stored_models.load_stored_model`. A production-source scan found no removed GraphModuleCatalog, execution_target, wait_for_events or ImageUploadService; the remaining UnavailableGraphModuleResponse is a deliberate public response schema. | Fresh unit suite covers registry behavior, resources, storage selection and compatibility. | Source and unit behavior verified; broad integration/packaging gates remain open. |

Source paths above are relative to their owning package under `apps/api/src/grafy_api`, `libs/core/src/grafy_core`, or `libs/persistence/src/grafy_persistence`. Exact changed-owner links and historical batch evidence remain in the implementation checklist.

## Remaining completion gates

- Source review for findings 10–14 is complete. Keep verification gaps in the table open until the corresponding integration or packaging evidence is inspected.
- Inspect preserved release/installation/selection, Module/Template, coordinator/node/scalar, raw/validated cache, Local/S3 and host/guest boundaries.
- Complete broad integration and packaging checks, including the relevant PostgreSQL and Docker evidence; record every exclusion or baseline failure.
- The migrated frontend flow passed the running-browser verification recorded below.
- Reconcile architecture documentation and all explicit original-audit requirements with final source, then check the overall completion gates only if each is proven.


## Second source pass, 2026-09-09

Reviewed findings 10–14 at the same production source, `c88bd00`. The architecture reference still described graph migration and revocation/recovery implementation as pending. Updated it to distinguish completed implementation from open final verification gates. No production code changed in this pass. [R23: Maintain The Rules]

The broad integration suite ran with two previously verified native macOS fork-crash files excluded: `test_plugin_egress_docker.py` and `test_workspace_plugin_protocol.py`. Do not count either exclusion as a passing integration check. Its final outcome is recorded below.


## Integration and PostgreSQL outcomes

- Broad integration run: 328 passed and one exact-OpenAPI test failed. The missing expected `/head/document` route was introduced by this cleanup and is now included. The test also contained two stale assertions: absence of catalog `origin` and omission of required `RunNodeRequest.kind`. Both fields were compared with the checked-in OpenAPI at implementation base `2013e7f` and current source and are unchanged. The updated test preserves exact assertions instead of weakening them. All five OpenAPI integration tests pass on rerun. No production schema changed. [R43: Tests Are Behavioral Contracts]
- The broad run includes passing system OCI loader and workspace Docker sandbox lifecycle tests. The two excluded native-fork files remain unverified in this final run. The run also emitted an aiosqlite worker-thread/event-loop-close warning during a readiness test; it is recorded as a warning, not a failed assertion.
- A fresh disposable PostgreSQL 15 container ran the transient marker, database lock-ordering, real execution/revocation, and cleanup-failure suites alongside their SQLite cases: 66 passed. Tests used isolated schemas, and the container was stopped and removed in `finally`. Log: `/tmp/grafy-final-postgres.log`.
- The general persistence run's 41 skipped cases remain visible. This dedicated run supplies the relevant fence/cleanup PostgreSQL cases; older optional persistence cases still need final gate classification.

Remaining work is runtime browser verification, final packaging/CLI and supported-platform coverage reconciliation, and the final preserved-boundary gate. Source review now covers all 14 findings. No whole-goal completion is claimed.


## Production frontend browser verification, 2026-09-09

Ran the cleanup worktree's production Next build against a real local API and an isolated temporary SQLite database. A loopback proxy forwarded HTTP and WebSocket traffic. Seeded test users authenticated through normal session cookies loaded from a protected temporary browser-state file. No authentication bypass or production source modification was used.

Playwright drove the visible UI:

1. Created a graph with a built-in Text input node and saved revision 1.
2. Edited its configuration, added an Artifact Viewer and dragged a preview connection from the text output to the viewer.
3. Opened a second tab. It hydrated the uncheckpointed text, viewer and link. Edited from that tab and observed the update arrive in the first tab through room replay.
4. Asserted with authenticated API reads that the live sequence was 7 while the checkpoint sequence was 1, and that the saved document still contained the original text. The live head contained one viewer and one link.
5. Saved from the UI and reloaded. Deterministic Playwright assertions checked the text value, viewer count, preview link and disabled Saved button. Authenticated browser-request assertions checked equality of canonical head and saved documents, saved revision 2, and matching sequence/checkpoint sequence 8.

The reloaded page had zero console errors or warnings. The initial unauthenticated page, before loading the test session, returned the expected session 401 and an unconfigured-OIDC login response; those setup responses were not part of the authenticated flow. The CLI assertion result was:

```json
{"browserAssertions":"passed","sequence":8,"checkpointSequence":8,"revision":2,"viewers":1,"links":1}
```

Inspected the screenshot at local artifact `output/playwright/final-graph-round-trip.png`. It shows the saved text node, connected Artifact Viewer and Saved state. This browser pass exercises built-in node configuration and presentation transport; exact Plugin pin variants remain covered by the transport and room tests.

Closed only the dedicated Playwright session and stopped its API/frontend/proxy supervisor. All children exited and the protected browser-state file was removed. The disposable database and non-secret logs remain under `/tmp/grafy-final-browser-9pdzueir` as local evidence. No main-checkout database or running app was used.

The browser verification gate is complete. Final packaging/CLI and platform/optional-test classification remain open.


## Final package and database verification, 2026-09-09

Built eight wheels offline: client, core, persistence, storage, workbench, API, standalone egress broker and GIS. Every packaged Python member was compared byte-for-byte with its owning source file, and every source Python file was present: 271 modules matched, with no stale moved/deleted modules. Import-path assertions confirmed that all eight packages loaded from the extracted wheels. Their OpenAPI matched the checked-in schema.

Five CLI help contracts matched exactly between source and extracted wheels: root, plugin, historical build-system-deployment, system-cutover and network-policy. The standalone broker entry point constructed successfully. Focused packaged client, core runtime, graph transport, compatibility, storage and spatial tests passed: 113 in the first run plus 10 historical deployment tests after correcting their fixture asset path. The same 10 deployment tests also passed against source. The correction makes repository test assets resolve relative to the test file rather than an installed wheel; it does not change runtime inventory discovery.

The full persistence run with both PostgreSQL configurations enabled initially had 239 passes and one migration parity failure. Migration `0027_transient_executions` used a timezone-aware SQL timestamp while the runtime's `UTCDateTime` stores UTC in a timezone-free column. Corrected that new, unmerged migration to `sa.DateTime()`. A fresh empty PostgreSQL container then passed all 32 migration tests, including upgrade, Alembic metadata comparison, downgrade and preservation coverage. All 240 persistence cases have now passed across the full run and focused retry; no optional case remains unexercised. Both disposable containers were removed.

Proposed rule addition: after a migration or mapped column-type change, run migration-to-runtime metadata comparison on each supported database dialect. A SQLite pass does not establish PostgreSQL type parity, especially for timezone handling. This is a concrete addition to schema verification guidance, not a new permission requirement. [R23: Maintain The Rules]

## Preserved boundaries

| Boundary | Final evidence |
| --- | --- |
| Release / installation / selection | Immutable release facts, scoped append-only installation and generation-bearing mutable selection remain separate domain models. InstalledPluginRelease still enforces their exact pairing. Release/catalog/persistence tests passed. |
| Module / Template | Module release/publication state remains separate from Template snapshot/state. Their API/application workflows and shared graph-staging use were inspected; both integration suites passed. |
| Coordinator / node / scalar runtime | API execution coordination and per-node execution remain separate from core NodeRuntime; import-boundary checks pass. Execution integration includes passing system OCI and workspace Docker lifecycle tests. |
| Raw / validated cache | Repository cache storage remains separate from PersistentInvocationCache identity/content checks and conditional stale-generation removal. Core and packaged cache tests passed. |
| Local / S3 | Concrete storage adapters remain distinct behind FileStoragePort. API selection is explicit, while the public package factory remains supported. Source and packaged storage/compatibility tests passed. |
| Host / guest validation | Host artifact exchange validates returned identities, formats and outputs; the guest independently validates contracts, materialized inputs and configuration. Source boundaries and unit/packaged contracts were inspected. Five native subprocess cases remain the platform limitation below. |

## Final requirement disposition

All 14 original implementation findings and the architecture-rule correction have current source evidence and relevant behavioral checks in this audit and the batch ledger. The remaining implementation steps referenced in earlier chronological entries are superseded by these final results. In particular, graph transport, revocation/cleanup fencing, PostgreSQL parity, browser verification and package compatibility are complete.

The final source scan preserves supported compatibility exports and response declarations deliberately: the storage package factory, historical host-tool aliases, and v1 graph response schemas remain. Their retention follows the original compatibility requirements and does not leave duplicate application ownership in place. No legacy protocol or feature was silently removed.

### Verification limits retained in the result

- Five native subprocess cases in `test_plugin_egress_docker.py` and `test_workspace_plugin_protocol.py` are excluded from the final broad integration run. The publication-fencing batch reproduced the same SIGSEGV failures in macOS Network.framework on an untouched baseline archive with asserted baseline import paths. They are not counted as passes, and this cleanup does not claim a new Linux run of those cases. Actual system OCI and workspace Docker lifecycle tests did pass.
- Targeted graph-contract typing retains seven pre-existing collection-default diagnostics; earlier whole-repository type/lint debt is documented in the batch ledger. No whole-repository clean-type-check claim is made. Frontend TypeScript and changed-file lint passed.
- The broad integration run emitted an aiosqlite worker-thread/event-loop-close warning in a readiness test. No corresponding assertion failed.
- Historical system deployment tooling still uses repository source/inventory inputs; its default inventory discovery is checkout-oriented exactly as at base `2013e7f`. Packaged implementation behavior was verified with explicit repository fixtures, not represented as a standalone source-free build workflow.

These are classified baseline/platform limits, not unresolved cleanup implementation. All required cleanup completion gates are satisfied with these limits disclosed. Changes remain local on the separate cleanup branch; nothing was pushed, merged or deployed.
