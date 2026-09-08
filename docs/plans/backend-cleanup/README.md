# Backend cleanup implementation checklist

This is the working checklist for the active goal: implement all remaining findings from this thread's backend structure audit. The full original review is preserved in [original-audit.md](original-audit.md). Do not mark a whole finding complete when only its file movement or easiest subtask is done.

Worktree: `/Users/user/Work/grafY-worktrees/backend-safe-cleanup`
Branch: `codex/backend-safe-cleanup`
Original implementation base: `2013e7f`.
Keep unrelated worktrees untouched. Each completed batch needs a commit and verification evidence. Preserve features, public compatibility tools, historical stored data, and supported SDK contracts. Changes to incorrect authorization/concurrency behavior need regression tests.

## Completed checkpoints

- [x] Remove unread CompiledNode execution-target field and compiler bookkeeping. Commit `f4b8eda`.
- [x] Remove four uncalled catalog conversion methods, retaining wire models. Commit `366f599`.
- [x] Group publication tooling and extract independent runtime profiles. Commit `9735cc2`. Adopted owner: `grafy_api/plugins/publication` and `plugins/profiles.py`.
- Evidence for these checkpoints: 516 API/client and selected integration tests passed; OpenAPI and CLI help unchanged; wheel imports passed. Live Docker tests were collected, not run.
- Existing debt is not a passing gate: API-wide Pyright had 520 diagnostics and Ruff had 5 before/after the publication move. Earlier module/OpenAPI tests had eight reproducible baseline failures. Revalidate when affected.

## 1. Workspace authorization

- [x] Replace duplicated collaboration policy with canonical transaction-local authorization while retaining rejection audits.
- [x] Replace SavedGraphService's duplicate capability policy.
- [x] Authorize multi-workspace copies in deterministic lock order.
- [x] Prove target-bound PAT cannot copy from another workspace even when its user belongs to both; verify rejection audit and no target graph.
- [x] Verify browser cross-workspace copies, disabled users, revoked membership, and role checks still behave correctly.
- Completed in the authorization consolidation batch below.

## 2. Checkpointed graph creation

- [x] Share graph/revision/head/initial-checkpoint staging across collaboration bootstrap, template instantiation, and module import within caller transactions.
- [x] Prove immediate checkpoint after template/module creation creates no redundant revision.
- [ ] Migrate ordinary fixtures off redundant SavedGraphService create/replace/delete paths.
- [ ] Remove redundant create/replace/delete mutators after fixture and behavioral-test migration.
- [x] Remove the runtime head-initialization workaround; preserve historical-state migration coverage.

## 3. Publication consistency

- [ ] Carry reviewed base revision/generation into the committing release operation and enforce it transactionally.
- [ ] Preserve source re-verification and test concurrent publication after review.
- [ ] Move System revocation's SQL consistency rule to its owner; coordinate maintenance drain with execution admission through a shared fence.
- [ ] Prove active execution/revocation races cannot violate that fence.

## 4. Plugin ownership and compatibility

- [x] Publication package and independent profiles, commit `9735cc2`.
- [ ] Group runtime admission, Docker invocation, and artifact staging under application Plugin hosting.
- [ ] Move SQL System cutover/baseline operations to persistence; keep command parsing/files/reporting in operator tooling.
- [ ] Give the egress broker a dedicated executable application owner.
- [ ] Relocate old host loader/builder/bindings as explicit compatibility tooling; retain CLI commands and historical policies.
- [ ] Remove unused active-runtime host binding/admission state, consistent with ADR 0007.

## 5. Execution ownership

- [ ] Move compilation, scheduling, cancellation, caching, and node execution out of v1/routes.
- [ ] Split execution history, materialization, and HTTP presentation by owner.
- [ ] Move execution request/plan contracts while preserving queued recovery serialization.
- [ ] Move the portable persistent invocation-cache adapter beside core cache semantics.
- [ ] Verify recovery, MAP ordering, cancellation, history, imports, and HTTP contracts.

## 6. Execution preparation duplication

- [ ] Resolve immutable exact-release facts once across preflight and compilation, removing duplicate lookup/cache/traversal.
- [ ] Preserve missing-secret-context failure before saved-graph/module lookup.
- [ ] Share saved-graph and nested-module request derivation.
- [ ] Retain preflight validation of submitted topology against saved revisions.

## 7. Catalog ownership

- [ ] Move catalog policy assembly from NodeRegistryResponse into a validated application snapshot.
- [ ] Gather release/selection/revocation state in one concrete transaction-scoped query.
- [ ] Use ModuleLibraryService directly; retire GraphModuleCatalog and its fallback validation.
- [ ] Remove unused UnavailableGraphModule and boundary detector while retaining public empty response fields.
- [ ] Verify collision diagnostics, readiness, query counts, module behavior, and OpenAPI compatibility.

## 8. Graph document contracts

- [ ] Reuse SavedGraphDocument internally through one compatibility transport adapter.
- [ ] Remove repeated graph validators and conversion logic without losing aliases.
- [ ] Migrate clients toward collaboration metadata plus canonical document.
- [ ] Make the versioned compatibility decision explicit before retiring flattened public fields and mirrored schemas.
- [ ] Verify graph round trips, old/new transport compatibility, generated clients, and OpenAPI.

## 9. Artifact availability

- [ ] Extract exact artifact resolution/storage availability from HTTP ArtifactService into a concrete application owner.
- [ ] Batch resolution and reuse format-specific object enumeration.
- [ ] Remove repeated reads during materialization checks.
- [ ] Preserve the distinction between availability and stronger cache content-integrity checks.

## 10. Spatial contracts and reads

- [ ] Share dependency-light persisted spatial contracts in core while preserving stored schema and HTTP defaults.
- [ ] Share feature-collection reconstruction and logical-byte integrity checks.
- [ ] Keep GDAL, network requests, tile serving, and HTTP render responses with deployment owners.
- [ ] Verify existing stored fixtures, API schemas, and GIS round trips.

## 11. Persistence cleanup

- [ ] Consolidate four Pydantic JSON and eleven string-enum decorators with typed implementations and named column types.
- [ ] Preserve SQL metadata and malformed-value behavior; retain specialized datetime/output/enum-collection semantics.
- [ ] Split repository/table ownership into identity, graphs, execution, plugins, and library, with one metadata bootstrap.
- [ ] Reuse bulk node hydration for queued/interrupted execution history, preserving ordering.
- [ ] Verify SQLite and PostgreSQL behavior and migration metadata.

## 12. Artifact contracts and in-memory persistence

- [ ] Move artifact repository contracts to ports/artifacts and concrete in-memory implementations to a production core runtime owner.
- [ ] Share lifecycle-only transaction protocol across feature protocols while keeping repository requirements explicit.
- [ ] Declare materialized-output dependency in saved-graph transaction contract and remove reflective fallback.
- [ ] Preserve task isolation, cloning, rollback, guest execution, and supported SDK imports.

## 13. Cross-feature host infrastructure

- [ ] Move GraphRoomHub and post-commit publisher to application realtime ownership.
- [ ] Move operation audit metadata out of workspace views into HTTP diagnostics near registration.
- [ ] Delegate malformed OIDC transaction cleanup to authentication.
- [ ] Give workspace transport models their own owner and return complete application results without route-side transaction reopening.
- [ ] Move cohesive NodeSecretService outside routes.
- [ ] Rename ImageUploadService to StagedUploadService; share staging/domain results and preserve batch rollback.

## 14. Composition and remaining reductions

- [ ] Retain the runtime bundle in AppResources instead of duplicating its fields; preserve lifecycle/shutdown order.
- [x] Remove unused compiled execution target, commit `f4b8eda`.
- [ ] Remove test-only wait_for_events wrapper; test production subscription behavior.
- [ ] Inline sole-production-caller storage selection, preserving supported package compatibility.
- [ ] Share stored-model integrity readers used by collections and tables.
- [ ] Consolidate PluginRegistry state into immutable family declarations plus needed indexes; preserve ordering, freeze behavior, collisions.
- [ ] Replace InstalledPluginRelease forwarding properties with explicit release/installation access while preserving pair invariants.

## Architecture contract and completion gates

- [ ] Replace tests enforcing route-folder service placement with dependency rules for application/runtime, HTTP transport, and ADR 0007 hosting.
- [ ] Update stale backend architecture reference as actual ownership changes land.
- [ ] Preserve real distinctions: release/installation/selection, Module/Template, coordinator/node/scalar runtime, raw/validated cache, Local/S3, and host/guest validation.
- [ ] For every audit item, inspect final source and relevant behavioral evidence before checking completion.
- [ ] Complete broad regression and packaging checks with every remaining limitation recorded. No whole-goal completion while any required item is unresolved.

## Batch log

Append completed batches here with changed owners, commit, exact test scope, outcome, and remaining gaps. Baseline failures must not be represented as passing checks.


### Workspace authorization consolidation, f44925c

- Replaced the collaboration policy copy and removed SavedGraphService's private policy implementation. Both call canonical transaction-local authorization.
- Graph copies authorize Workspace requirements in sorted ID order while retaining collaboration rejection audits.
- Reproduced the cross-Workspace PAT defect through HTTP before the fix: the forbidden copy returned 201. The regression now proves 404, one source-Workspace rejection audit, and no new target graph; browser cross-Workspace copy still works.
- Added both-direction lock-order checks and revoked-membership/disabled-user mutation checks.
- Validation: 109 application and graph/auth/collaboration integration tests passed; 516 API/client/catalog/execution-route tests passed. Ruff passed for all four changed Python files. Pyright passed for both changed application modules and the HTTP regression module.
- These checks do not cover the separate credential capability-ceiling and live-session revocation concerns from other reviews. They prove this audit's duplicated-policy and Workspace-binding finding.
- Next: checkpointed graph staging for template instantiation and module import, followed by retirement of redundant graph mutation paths.


### Shared checkpointed graph creation, 4f15f4f

- Added application-owned `graph_creation.stage_checkpointed_graph`, used by collaboration bootstrap, exact-head copy, template instantiation, and module import. It stages graph, revision, head, and initial mapping through repositories supplied by the caller; it never commits.
- Preserved initial collaboration sequence 1 for bootstrap/copy and 0 for template/import. Authorization, receipts, folder assignment, module publication, sanitization, and commits remain with each workflow.
- Both HTTP regressions failed on the original source because an immediate checkpoint produced revision 2. They now verify revision 1 after checkpointing new template/module graphs.
- Added a rollback regression proving a failed initial mapping leaves no graph, revision, head, receipt, mapping, or success audit.
- Validation: 633 tests passed across application, API, client, templates, saved graphs, collaboration, workspace authorization, catalog, execution routes, and the module-import checkpoint regression. Focused Ruff passed; Pyright passed for all four changed application modules.
- Remaining finding 2 work: migrate ordinary fixtures away from redundant SavedGraphService mutators and retire those mutators plus the historical head-initialization workaround. This batch does not claim that retirement is complete.

### Remaining graph lifecycle migration inventory, after 4f15f4f

A bounded caller review found no production callers of `SavedGraphService.create`,
`replace`, `delete`, or `CollaborationService.initialize_head_for_existing_graph`.
Keep `SavedGraphService.apply_replacement_in_unit_of_work`: collaboration uses it
for checkpoint/replacement, secret reconciliation, and materialization carry-forward.
Also retain `verify_every_graph_has_head`, which checks startup integrity.

Next migration scope:

1. Move legacy mutator behavior coverage in `tests/unit/application/test_saved_graphs.py`
   to collaboration operations, retaining read-side and revision tests.
2. Migrate ordinary setup in node-secret integration tests, execution-history tests,
   and materialized-output tests to checkpointed graph staging in their test transaction.
3. Replace saved-graph integration calls to the head initializer with canonical head
   reads. Those graphs were already created through HTTP.
4. Replace runtime initializer tests with explicit historical-state migration/backfill
   coverage and fail-closed startup verification. Do not preserve the production
   workaround just to construct test state.
5. Remove the obsolete methods after rechecking all references and preserving the
   existing revision-conflict, secret, history, and materialization behavioral coverage.


### Retired runtime head initialization

- Removed `CollaborationService.initialize_head_for_existing_graph` after confirming no production callers and migrating every test reference.
- Saved-graph HTTP tests now read the heads created by canonical HTTP operations. The node-secret route fixture stages a checkpointed graph directly in its test transaction.
- Replaced runtime repair tests with canonical-head read stability and startup verification tests. Missing heads remain a fail-closed condition; no automatic repair is introduced.
- Preserved and ran `test_collaboration_head_migration_backfills_exactly_one_sequence_zero_head`, which verifies exact historical revisions, one head per graph, and no orphan rows.
- Fixed an existing node-secret route fixture collision: its test family was registered both as builtin code and as a synthetic published Plugin. The route fixture now uses only its intended builtin registration. All secret metadata, redaction, configuration, revision, and deletion assertions remain and execute successfully.
- Validation: 49 focused collaboration, saved-graph HTTP, node-secret HTTP, and historical migration tests passed. Ruff passed for all four changed Python files; collaboration Pyright passed. No code references to the retired method remain.
- Remaining finding 2 work: retire the legacy SavedGraphService create/replace/delete paths and migrate their ordinary fixtures and behavioral tests.
