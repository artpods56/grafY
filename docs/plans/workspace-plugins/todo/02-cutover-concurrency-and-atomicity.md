# Work packet 02: Cutover concurrency and atomicity

- **Status:** Not implemented at the interruption checkpoint
- **Parent slice:** [Slice 12](../12-compatibility-cutover.md)
- **Outcome:** An apply run either rewrites the exact audited state as one
  maintenance transaction or makes no changes

## Problem

`SystemBaselineCutoverService.execute()` currently checks active executions and
reads graph documents with ordinary `SELECT`s. `_apply()` then updates rows by
primary key only. A graph edit can be overwritten after audit, or a queued
execution can be inserted after the drain check.

Row-level locks alone do not solve the insertion race under PostgreSQL
`READ COMMITTED`. The apply path needs a transaction-scoped maintenance fence
over every table it audits or mutates, followed by exact compare-and-swap checks.

## Required invariants

1. The apply path acquires its maintenance fence before the active-execution
   check, baseline verification, document audit, or provenance audit.
2. The fence prevents concurrent `INSERT`, `UPDATE`, and `DELETE` operations on
   every cutover-scanned or cutover-mutated table until commit or rollback.
3. After acquiring the fence, active execution state is read again and any
   `queued`, `running`, or `cancelling` row aborts the cutover.
4. Every document/provenance update compares the exact audited original value as
   well as its primary key. A missing or changed row aborts the whole transaction.
5. Cache/materialization invalidation and provenance marking commit in the same
   transaction as document rewrites.
6. PostgreSQL and SQLite have explicit, tested behavior. Any other dialect fails
   closed instead of pretending to be safe [R11: Framework Constraints Must Be
   Explicit].
7. Audit mode remains non-mutating. Apply recomputes the precondition token under
   the maintenance fence and must match the caller's audited token.

## Maintenance fence contract

Use one cohesive method on `SystemBaselineCutoverService`; do not create a generic
database-lock helper used nowhere else [R02: No Abstraction For One Call Site].

For PostgreSQL, acquire deterministic `LOCK TABLE ... IN SHARE ROW EXCLUSIVE
MODE` locks for all of these tables in the apply transaction:

- `plugin_releases`
- `plugin_release_selections`
- `plugin_release_revocations`
- `saved_graphs`
- `saved_graph_revisions`
- `collaborative_graph_heads`
- `templates`
- `graph_executions`
- `artifact_objects`
- `graph_execution_nodes`
- `invocation_cache_entries`
- `materialized_node_outputs`

This mode conflicts with the `ROW EXCLUSIVE` lock taken by data-changing
statements, including inserts of new queued executions and graph revisions.

For SQLite, `BEGIN IMMEDIATE` must be the first transaction operation so the
connection obtains the database write reservation before auditing. Do not issue
it after SQLAlchemy has already emitted another statement in an implicit
transaction.

## Current partial state

No lock or CAS edit had landed when the implementation agent was stopped. The
current service still:

- enters a normal `session.begin()` transaction;
- calls `_refuse_active_executions()` before any maintenance fence;
- audits rows with ordinary selects;
- updates documents and provenance with primary-key predicates only.

## Owned files

- `libs/persistence/src/grafy_persistence/system_cutover.py`
- `tests/unit/persistence/test_system_cutover.py`

Do not add a global application maintenance mode or edit graph-authoring routes in
this packet. The database transaction is the owner of this narrow cutover fence.

## Implementation steps

1. Split the apply transaction entry only as much as needed to make
   `BEGIN IMMEDIATE` the first SQLite operation. Keep transaction orchestration in
   the service [R18: One Layer Per Function].
2. Acquire the dialect-specific fence before all apply reads. Use a static,
   deterministic table order.
3. Re-run the drain check and all audits inside that fenced transaction.
4. Add the audited original payload to every update predicate where the database
   type supports equality. Also re-read locked payloads and compare in Python so
   JSON representation differences cannot weaken the check.
5. Require `rowcount == 1` for every changed document/provenance row. Raise
   `SystemCutoverPreconditionError` with store and row identity on mismatch.
6. Let the exception roll back graph rewrites, provenance, cache deletion, and
   materialization deletion together.

## Behavioral acceptance tests

Add deterministic tests proving:

- a changed document between audit and apply causes a precondition failure and
  zero cutover mutations;
- a deleted audited row causes a precondition failure and zero cutover mutations;
- an execution inserted after the earlier dry-run cannot slip through the apply
  drain check;
- SQLite obtains its write reservation before the first audit query;
- unsupported dialects fail closed;
- an exception after one attempted rewrite rolls back every rewrite,
  provenance mark, and invalidation;
- the existing idempotent successful apply behavior still passes.

Do not weaken the test by invoking `_apply()` directly. Exercise the public
`execute(SystemCutoverCommand(..., mode="apply"))` behavior [R43: Tests Are
Behavioral Contracts].

## Focused gate

```bash
uv run pytest -q -o log_cli=false tests/unit/persistence/test_system_cutover.py
uv run ruff check \
  libs/persistence/src/grafy_persistence/system_cutover.py \
  tests/unit/persistence/test_system_cutover.py
uv run basedpyright \
  libs/persistence/src/grafy_persistence/system_cutover.py \
  tests/unit/persistence/test_system_cutover.py
```

## Definition of done

- PostgreSQL insertion/update races are blocked for the whole apply transaction.
- SQLite starts apply with `BEGIN IMMEDIATE`.
- Exact stale/missing-row CAS failures roll back the entire cutover.
- Focused tests, Ruff, type checking, and `git diff --check` pass.
- Implementation evidence is appended below.

Current ownership: the SQL service and its tests now live in persistence.
The implementation evidence below retains the paths used by its original runs.

## Implementation evidence

Files changed (relative to HEAD):

- `apps/api/src/grafy_api/system_cutover.py` (new) — the cutover service with:
  - one cohesive fence method, `_acquire_apply_maintenance_fence`, acquired as the first operation of the apply transaction (before the active-execution check, baseline digest verification, document audit, and legacy provenance audit): PostgreSQL issues `LOCK TABLE <table> IN SHARE ROW EXCLUSIVE MODE` for all 12 `_CUTOVER_FENCE_TABLES` in fixed order; SQLite issues `BEGIN IMMEDIATE` as the first statement (the same pattern the repositories already use for write transactions); any other dialect fails closed with `SystemCutoverError` [R11];
  - dry-run stays non-mutating: it never acquires the fence and never writes;
  - the apply precondition token is recomputed under the fence and must equal `expected_precondition_token`, so a stale audited token is refused after the fence is held;
  - document payload swaps use `_cas_swap_payload`: re-read the locked payload by primary key, compare the deserialized current payload to the audited original in Python, `UPDATE` with the identity conditions plus `payload ==` the original JSON literal, require `rowcount == 1`, otherwise raise `SystemCutoverPreconditionError` naming the store, table, and row identity; a failed apply rolls back the whole cutover transaction.
- `tests/unit/api/test_system_cutover.py` (new) — 11 tests, including this completion's six behavioral tests: `test_postgresql_fence_locks_every_cutover_table_in_fixed_order`, `test_apply_fence_fails_closed_on_unsupported_dialect`, `test_apply_fence_serializes_queued_execution_insert_before_drain_check`, `test_sqlite_apply_waits_for_write_reservation_before_auditing` (a contending write lock held in a second session defers apply until the busy timeout and surfaces `OperationalError`), `test_apply_cas_rejects_document_changed_after_audit_and_rolls_back`, `test_apply_cas_rejects_deleted_audited_row_and_rolls_back`.

Focused gates (all green):

- `uv run pytest -q -o log_cli=false tests/unit/api/test_system_cutover.py` → 11 passed.
- `uv run ruff check apps/api/src/grafy_api/system_cutover.py tests/unit/api/test_system_cutover.py` → All checks passed.
- `uv run basedpyright apps/api/src/grafy_api/system_cutover.py` → 0 errors.
- `git diff --check` → clean.

Deliberately unsupported states: apply on any dialect other than PostgreSQL or SQLite refuses to run (`SystemCutoverError`) rather than falling back to an unverified locking strategy; the SQLite fence relies on the repository's `busy_timeout` (5000 ms) for reservation contention, after which the blocked apply surfaces `OperationalError` and rolls back cleanly.

Remaining blockers: none.
