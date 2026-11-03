# ADR 0002: Use server-authoritative graph sessions for Workbench collaboration

- **Status:** Accepted; Phase 0–6 implemented; Phase 7 operator release gate open;
  amended by ADR 0020 (the collaborative document and its command batches become
  Project-scoped)
- **Date:** 2026-08-05
- **Scope:** Workbench graph authoring, persistence, presence, and execution observation
- **Design:** [Realtime Workbench collaboration rework](../design/workbench-realtime-collaboration.md)
- **Related:** [Authenticated workspace ADR](0003-authenticate-users-and-scope-collaboration-to-workspaces.md)
  and [authentication and workspace tenancy design](../design/authentication-and-workspace-tenancy.md)

## Context

The Workbench currently keeps its canonical editable graph in browser-local,
React Flow-shaped state. Saving replaces the complete saved graph using the
revision last read. This prevents silent overwrite but turns concurrent editing
into a whole-document conflict.

Live execution is also session-local from the frontend's perspective. The
browser that starts an execution learns its id and subscribes to its event
stream; another browser viewing the same graph does not discover that active
execution automatically.

Realtime collaboration needs three kinds of state with different consistency
requirements:

1. durable graph authoring that must converge and survive restart;
2. transient presence such as cursors and drag previews;
3. server-owned execution state tied to one immutable graph revision.

Saved graph revisions already identify immutable execution and module
checkpoints. Materialized outputs and execution history use that exact revision.
Using saved graph revision as a high-frequency collaboration clock would create
full immutable snapshots for ordinary gestures and continuously change output
eligibility.

The current API process owns execution tasks, cancellation, and the bounded SSE
replay journal in memory. Startup recovery assumes that one process owns every
active execution. Supporting multiple browser sessions does not remove that
single-API-owner constraint.

## Decision

### Keep one Workbench feature

The Workbench remains one feature-first client lifecycle under
`features/workbench`. Collaboration does not introduce independently hydrated
canvas islands or a global application store.

Move the canonical authored graph into a framework-independent Workbench model.
React Flow becomes an adapter that combines the authored graph with local
selection, renderer callbacks, registry decoration, presence, and
revision-scoped execution overlays.

This would replace the transitional React Flow-shaped graph contract recorded in
ADR 0001 rather than duplicating it.

### Use a server-authoritative collaboration sequence

Each saved graph within a workspace has one durable collaborative head
identified by `(workspace_id, graph_id)`, a room epoch, and a monotonic server
sequence. Clients submit typed semantic graph commands over one
workspace-and-graph-scoped WebSocket.

The server:

- deduplicates each command id;
- defines its conflict behavior;
- validates and applies it atomically to the latest collaborative head;
- persists the new head and accepted command before acknowledgement;
- assigns the next collaboration sequence; and
- broadcasts the accepted command only after commit.

Commands describe meaningful graph gestures and compound transitions. The
protocol does not expose arbitrary JSON Patch operations.

Command ids are idempotency keys within the workspace-owned graph, with a
versioned, server-keyed HMAC over the canonical request. A plain digest of
low-entropy configuration is not persisted. An exact retry returns its original
receipt; reusing an id for another semantic command is rejected. Receipts are
retained as tombstones across room-epoch resets for the graph's lifetime.

Complete head snapshots are the only recovery path. No operational command
journal or incremental replay store is retained; accepted commands persist only
the updated head, receipt, checkpoint mapping or revision when applicable, and
audit metadata. Security audit remains a separate metadata-only store; neither
audit records nor receipts copy command or configuration values.

### Keep saved graph revisions as checkpoints

Collaboration sequence and saved graph revision remain separate.

- Accepted commands are automatically persisted to the collaborative head.
- A checkpoint turns one exact collaborative head sequence into an immutable
  saved graph revision through the existing saved graph validation and
  node-secret reconciliation workflow.
- Checkpoint revision, secret reconciliation, sequence mapping, and
  collaborative-head metadata commit once in one application-owned unit of
  work; the current independently committing saved-graph service boundary must
  be restructured for that workflow.
- Explicit Save creates a checkpoint; starting execution automatically creates
  or reuses the checkpoint for the synchronized head sequence.
- Execution history, graph modules, materializations, and pins continue to
  identify only saved graph revisions.
- External complete-document replacement is rejected while the collaborative
  head contains uncheckpointed commands. A safe replacement creates a new room
  epoch and forces connected clients to rehydrate.
- Create, safe replacement, and delete all coordinate the collaborative head;
  deletion of an uncheckpointed head requires explicit exact-head confirmation.
- MCP is HTTP-only: first delivery mounts **stateless** Streamable HTTP at
  `/mcp` under the FastAPI authority, validates a workspace-bound PAT on every
  request with no process-global caller token, and has no stdio or anonymous
  fallback. MCP authoring calls the same workspace-bound collaboration
  application as the WebSocket and HTTP graph routes. It applies commands to,
  or safely replaces, the live collaborative head and cannot mutate an
  unrelated checkpoint document directly.

### Keep presence ephemeral

Cursor position, remote selection, editing activity, soft claims, and live drag
previews are best-effort room presence with a server-owned expiry.

Presence:

- does not advance collaboration sequence or saved graph revision;
- does not mutate local selection in another browser;
- may be dropped under backpressure;
- is cleared on disconnect or API restart; and
- never contains graph configuration values, secret values, artifact payloads,
  complete run inputs, or one-time URLs.

A node drag publishes transient positions through presence and submits one
durable move command when the gesture ends.

### Share graph execution observation

One workspace-owned saved graph may have at most one queued, running, or
cancelling execution. `graph_executions.status` is the sole authority for that
invariant: a database-level partial unique index over `(workspace_id,
graph_id)` covers only the active statuses, so terminal transitions release the
constraint automatically and no second slot table exists. Every top-level API
path that starts and persists an execution attributed to that graph obeys the
same application and persistence invariant; a conflicting start is rejected and
reports the existing active execution identity. Internal immutable saved-module
invocations remain part of their owning top-level run.

Graph deletion conflicts with an active execution; cancellation and terminal
commit must finish before deletion can remove revision, history, or
materialization state.

Command idempotency through `graph_command_receipts` applies to collaboration
commands only. Top-level execution-start requests are not durably idempotent in
the current implementation: a repeated start with a fresh id creates a new
execution or is rejected by the one-active-execution invariant. Durable
execution-start idempotency would require its own accepted design and is not
implied by command receipts.

Synchronous `/v1/runs` becomes draft/diagnostic-only and rejects saved graph
context. Saved graph runs must respect the one-active-execution invariant and
produce a discoverable execution id.

The workspace-and-graph room advertises the active execution id, starter
presentation, checkpoint revision, scope, and lifecycle. Each browser then uses
the existing per-execution SSE stream and polling fallback for node status and
progress. The room does not duplicate the complete progress stream.

The retained execution GET exposes a sequence-consistent current per-node
observation snapshot. SSE explicitly reports when its requested cursor predates
bounded replay so a late joiner can recover through that snapshot.

The activity bar remains visible when collaborators edit during a run. Node
overlays are applied only while a server-owned comparison says that the current
head derives the same execution plan as the run's checkpoint. Cosmetic graph
changes do not invalidate that comparison. Materialized outputs remain eligible
only for the exact saved graph revision recorded by the execution.

### Retain the single-API-owner deployment constraint

The first collaboration implementation uses one in-process graph-room hub and
the current in-process execution manager. It supports exactly one FastAPI
application process: one replica and one Uvicorn or Gunicorn worker. Feature
enablement must fail or remain disabled when that singleton cannot be asserted.

Do not add a broker or coordination interface until another API owner is a real
supported adapter. Multiple API owners require a separate accepted design for
leases, fencing, shared room publication, shared execution replay,
cancellation routing, and owner-scoped recovery.

### Bind every room and operation to authenticated workspace access

The current `local` workspace slug and room session identity are not
authentication boundaries. The production room protocol depends on the
authenticated Workspace and WorkspaceAccess model in ADR 0003. A room, its
collaborative head, and its active execution are all identified by the requested
workspace and graph; the server verifies that the graph belongs to that
workspace before exposing any room state.

At WebSocket admission, the server authenticates the browser session, resolves
current WorkspaceAccess, authorizes graph visibility, and derives the actor
presentation, capabilities, and an opaque authorization version. The client
cannot claim an actor id, role, capability, authorization version, display name,
or display style. `room.ready` reports only the server-derived presentation,
capabilities, and authorization version.

Admission is not continuing mutation authority. Each graph command, checkpoint,
complete replacement, execution start or cancellation, secret mutation, and
delete revalidates the credential and current WorkspaceAccess at handling time
through the owning application workflow. Authentication and workspace access
are checked before idempotency results or resource state are disclosed.

Workspace-membership removal or role change advances the membership's
authorization version and deterministically closes affected room and SSE
connections. The same membership transaction revokes that user's affected
workspace-bound PATs: all of them on removal, and any whose scopes exceed the
member's remaining capabilities on role loss. AuthSession revocation separately
closes room and SSE connections bound to that browser credential without
changing membership state. Because first-delivery MCP is stateless, PAT
revocation takes effect on the next independently authenticated MCP request
rather than by closing a retained MCP authorization session. A still-authorized
browser client must reconnect and receive newly derived capabilities before it
can resume; a client that lost visibility is rejected before the room snapshot.
Operation-time authorization remains authoritative if the close notification
races an in-flight message.

Node-secret rows and bindings are workspace-owned and loaded through the exact
workspace and graph. Only an Owner may configure or physically remove them; an
Editor checkpoint may make a binding inactive without deleting the protected
row. Secret values remain exclusively in that workflow. They must not enter
collaboration snapshots, commands, presence, errors, audit logs, or execution
announcements. Secret configure/remove requests identify the exact synchronized
head, checkpoint it when necessary, and publish only configured status after the
protected write commits.

## Consequences

### Positive

- Local and remote graph edits cross the same semantic command surface.
- Realtime conflicts are specific to the operation and target instead of a
  complete-document `409` after substantial work.
- Accepted changes survive browser and API restart even before a checkpoint is
  created.
- Saved graph revision keeps its current meaning for execution provenance,
  modules, and exact materializations.
- Cursor and drag traffic cannot create persistent graph churn.
- Every session can discover and display the same active execution.
- Existing execution SSE validation, sequencing, replay, polling, and
  cancellation reconciliation remain useful.
- React Flow renderer concerns no longer define the durable graph interface.
- Workspace membership provides one authorization boundary for the room,
  collaborative head, checkpoints, and execution observation.

### Negative

- Persistence gains a collaborative head, command receipts with idempotency
  rules, checkpoint mapping, and retention concerns. No command-payload journal
  is retained; complete head snapshots are the recovery representation.
- The frontend must reconcile optimistic commands, server acknowledgements,
  rejections, reconnects, and epoch changes.
- Complete-document REST/MCP replacement can no longer ignore an uncheckpointed
  collaborative head.
- Existing saved-graph reads remain checkpoint views and may lag the live
  authoring head; live consumers use the workspace-and-graph room rather than
  pairing a draft document with an older revision number.
- Save has two visible meanings to explain: draft synchronization and immutable
  checkpoint creation.
- Execution planning moves to the workspace-and-graph-scoped server contract
  rather than a client-submitted duplicate of the graph.
- The initial implementation remains unsuitable for horizontally scaled API
  ownership.
- Room admission and every durable operation add credential and WorkspaceAccess
  checks, while membership or role changes require clients to reconnect.

## Alternatives considered

### Continue whole-document optimistic saves

Rejected because it detects overlap only at save time, offers no realtime
presence, and requires manual conflict recovery.

### Advance saved graph revision for every accepted command

Rejected because revisions are complete immutable checkpoints and execution
provenance. High-frequency authoring would create snapshot churn and constantly
change exact materialization eligibility.

### Use a general CRDT document

Not selected because offline editing and character-level collaborative text are
not requirements. Graph topology and port contracts still require authoritative
semantic validation. Reconsider only if those product requirements become real.

### Use arbitrary JSON Patch commands

Rejected because callers would need the storage shape and compound graph
invariants would be split across clients.

### Send execution progress through the graph WebSocket

Rejected for the first implementation because the existing per-execution SSE
stream already owns sequenced, bounded live progress and polling fallback. The
missing capability is graph-level discovery.

### Allow concurrent graph executions

Rejected initially because the current activity bar and node overlays represent
one execution, and materialization precedence would become ambiguous.

### Add multi-process coordination immediately

Rejected until a second API owner becomes supported. Adding a broker seam
without execution leases, fencing, recovery, and cancellation routing would not
make the deployment safe.

## Follow-up

This ADR is Accepted. Remaining follow-up:

1. Add the accepted vocabulary to `CONTEXT.md` when that pass is scheduled.
2. Finish ADR 0003 workspace-bound graph route cutover before enabling the
   production room protocol.
3. Implement the collaboration migration phases in the linked technical design.
4. Update deployment documentation to state the WebSocket proxy requirements
   and single-API-owner constraint.
5. Record a separate ADR before enabling multiple API owners.
