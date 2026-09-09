# Transient execution maintenance fence

## Verified failure

On cleanup commit `2c13042`, a real `RunExecutionManager` with a SQL-backed
`ExecutionHistoryService` starts a request with no graph identity. A controlled
executor pauses inside `run()`. `SqlPluginReleaseRepository.lock_system_revocation`
returns no active executions, and `PluginReleaseService.revoke_system` commits
while that executor is still paused.

The original diagnostic is now replaced by
`tests/unit/persistence/test_transient_executions.py`. Its regression pauses the
executor, expects `SystemPluginRevocationDrainError`, verifies no revocation row,
and verifies revocation succeeds once activity ends. The original reproduction
output remains recorded in the checklist.

## Implemented status

Migration 0027 adds a separate activity table. SQL and in-memory adapters implement
registration, owner-bound removal, listing, and stale-marker clearing. The manager
registers before task creation and removes activity after task cleanup. Revocation
and cutover include the new table in their lock/read sets.

Startup clears stale activity only after obtaining the single-owner lease and
successfully completing Plugin orphan recovery. If either condition is unavailable,
startup refuses to clear markers and reports their IDs. This includes restart with
stale markers while the Plugin runtime is disabled. It is a fail-closed operational
condition, not automatic recovery for every configuration. Without an owner lease,
startup never runs global orphan cleanup. If there are no stale markers, that
configuration may still start without deleting other workers.

Lifecycle, rollback, owner-bound removal, fail-closed deletion, additive migration,
and both database lock orderings have passing tests. Real manager execution tests
cover revocation before admission and active preflight, invocation, and sandbox
cleanup on SQLite and PostgreSQL. Startup lifespan tests verify successful
recovery, disabled owner/runtime, failed orphan cleanup, and lease contention.
The single-owner deployment assumption still applies; this does not add multi-owner
or multi-host coordination.

## Why the previous fence missed the run

`execution/manager.py:start` creates durable history only when the request has
both graph ID and revision. A transient run takes a process-local capacity lease
and starts its task. Compilation and execution occur later in that task.

System revocation reserves the SQLite write lock, or locks revocations and graph
executions on PostgreSQL, then reads active saved-graph rows. System cutover also
checks only those rows. Neither operation can observe the transient lease.

A durable marker must exist before preparation begins and remain until execution
and guest cleanup finish. Keeping a SQL transaction open for that entire interval
would interfere with artifact writes and is not the proposed solution.

## Implementation decision

Add a separate transient activity table. Keep saved-graph history non-nullable and
preserve its existing graph/revision foreign keys, browse APIs, queued recovery,
and idempotency semantics. A transient run must not invent a saved graph or become
recoverable merely to participate in maintenance coordination.

The marker contains execution identity, workspace identity, creation time, and
sufficient owner identity for safe recovery. It contains no request payload,
configuration, credentials, or artifact capabilities. Presence means active,
including cancellation while work is still stopping.

Use the existing execution persistence owner and its transaction port for marker
admission and release. Mirror its behavior in the in-memory adapter. Keep the
manager responsible for task lifetime; persistence owns database lock semantics.
Production composition must provide this dependency. A test-only optional seam
must not become an untracked production path.

```mermaid
sequenceDiagram
    participant M as Execution manager
    participant DB as Short database transactions
    participant R as Run preparation and execution
    participant O as System maintenance
    M->>DB: Insert active marker and commit
    M->>R: Start preparation
    O->>DB: Acquire maintenance fence and read activity
    DB-->>O: Active marker; refuse maintenance
    R-->>M: Work and guest cleanup finished
    M->>DB: Delete active marker and commit
```

## Lock and lifecycle requirements

- PostgreSQL maintenance must lock the new marker table in a consistent order
  after the existing revocation and execution locks. Marker insertion takes a
  conflicting write lock. System cutover must include the same table and activity
  check. SQLite retains its short `BEGIN IMMEDIATE` maintenance transaction.
- If admission commits first, maintenance observes activity and refuses. If
  maintenance commits first, admission may proceed but later compilation must
  observe the revocation. Test both orderings with actual database transactions.
- Register before spawning the task. An admission write failure must prevent task
  creation and release process capacity. Failed task creation must clean up the
  marker, or retain it with a contextual failure if deletion cannot be confirmed.
- Release activity after the task and guest cleanup end, including success,
  failure, cancellation, shutdown, and cancellation before first task execution.
  Cancellation intent alone must not remove the marker.
- A failed or uncertain marker deletion must fail closed. Do not silently pretend
  maintenance is safe. Retry/reconcile deletion and report execution identity.
- Recovery must not delete another live owner's markers. Current production uses
  a single API owner, but that setting can be disabled. Define an explicit policy
  for that mode; a restarted process alone is not proof that an older owner died.
- Startup may clear confirmed stale markers only after obtaining exclusive owner
  authority and successfully draining orphaned Plugin workers. Preserve markers
  if orphan recovery fails. Never clear them merely because they are old.
- Nested runs remain covered by the parent's lifetime. Verify every externally
  reachable execution entry point is tracked; an HTTP-only hook is insufficient.

## Required evidence before completion

1. Turn the reproduced failure into a passing regression with no revocation row.
2. Verify marker lifetime for success, failure, cancellation, shutdown, admission
   failure, task creation failure, and terminal persistence failure.
3. Verify System cutover rejects active transient work too.
4. Exercise both transaction orderings on SQLite and PostgreSQL. Use events and
   confirmed database blocking rather than sleep duration as race evidence.
5. Verify startup with stale markers, orphan recovery failure, and owner authority
   absent. Demonstrate that active markers cannot be erased by another owner.
6. Test the additive Alembic upgrade on an existing database. Verify no changes to
   saved history browsing, request serialization, generated clients, or OpenAPI.
7. Run execution, persistence, release-maintenance, architecture, and packaging
   checks; retain established baseline failures separately.

Both externally reachable top-level execution paths now enter the manager.
Background work uses `start`; synchronous `POST /runs` uses `run_inline` while
retaining the HTTP admission lease through presentation. Real route-handler races
verify synchronous preflight, invocation, cleanup, and cancellation. Module execution
remains nested within its parent's lifetime.

Finding 3 remains open for unconfirmed sandbox cleanup. `DockerPluginRuntime.close_scope`
can raise after failing to remove a container. Current manager terminal handling
still removes transient activity or terminalizes saved history after that executor
error. The next change must distinguish a confirmed stopped execution from a cleanup
failure, retain the maintenance fence for the latter, and cover both saved and
transient runs. Normal execution failure and successful cancellation must continue
to release activity. Startup recovery must remain the authority for orphan cleanup.
