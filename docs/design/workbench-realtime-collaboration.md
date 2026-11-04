# Realtime Workbench collaboration

- **Status:** Accepted; implemented on the Project model
- **Date:** 2026-11-03
- **Audience:** Engineers changing the Workbench canvas, Project persistence, the room
  protocol, or Runs
- **Document type:** Technical design explanation
- **Related:** [ADR 0002 — server-authoritative collaboration](../adr/0002-server-authoritative-workbench-collaboration.md),
  [ADR 0003 — workspace scoping](../adr/0003-authenticate-users-and-scope-collaboration-to-workspaces.md),
  [ADR 0014 — command batches as validated steps](../adr/0014-apply-graph-command-batches-as-validated-steps.md),
  [ADR 0020 — Projects hold Graphs, results belong to nodes](../adr/0020-projects-hold-graphs-and-results-belong-to-nodes.md),
  [authentication and workspace tenancy](authentication-and-workspace-tenancy.md),
  [Runs ownership](../../apps/api/src/grafy_api/runs/README.md),
  [product vocabulary](../../CONTEXT.md),
  [web conventions](../../apps/web/AGENTS.md)

## Superseded

[ADR 0020](../adr/0020-projects-hold-graphs-and-results-belong-to-nodes.md) superseded
the design this document held before it, in which a room was held around one **Graph**,
carried one graph-level revision, and pointed clients at an event stream for the one
active **Execution**. Three moves, restated in the vocabulary of
[CONTEXT.md](../../CONTEXT.md):

1. **The room is held around a Project.** One room per Project, addressed by
   `(workspace_id, project_id)`, whose document holds all of the Project's Graphs.
   A Graph is a definition inside the Project, not a room of its own.
2. **Clients submit ordered command batches, addressed per Graph.** A batch is one unit
   of acceptance and advances the Project sequence exactly once; a command that acts
   inside a Graph is wrapped in `in_graph(graph_id, command)`, and the Project-level
   commands sit beside it rather than inside it.
3. **Results belong to node instances, not to an Execution.** The room publishes the
   list of active Runs and derived per-instance state; there is no "the active
   execution", no execution-scoped event stream, and no revision that a run owns.

What the old text still got right is rewritten in place below (transport discipline,
presence rules, backpressure, revocation, failure behavior, the single-owner
constraint). What is gone is listed under [Gone](#gone). How a Run is scheduled,
fingerprinted and stored is not repeated here —
[apps/api/src/grafy_api/runs/README.md](../../apps/api/src/grafy_api/runs/README.md)
owns that.

## The shape of it

One Project, one room, one command sequence, many Runs.

1. A Project is the collaborative document. Its **head** is the draft everyone edits;
   its **checkpoints** are the immutable revisions it is periodically made durable
   as. Both live in one row set owned by
   [`CollaborationService`](../../libs/core/src/grafy_core/application/collaboration.py),
   which is the only writer of a head.
2. Clients submit **semantic command batches** over a workspace-and-project-scoped
   WebSocket. A batch is accepted or rejected as a whole; the server validates, orders,
   and persists it as the next collaboration sequence in one transaction, and only then
   fans it out.
3. Cursor position, remote selection, editing activity and drag previews are **ephemeral
   presence**. They never create a checkpoint and are dropped before anything else when
   a session falls behind.
4. React Flow remains the canvas renderer, not the canonical document.
5. **Results belong to node instances.** Any number of Runs are active in a Project at
   once; the room announces `run.started`, `run.finished` and `instances.changed`, and
   REST stays the source of truth for what they mean.
6. **Edits never lock the document.** A computation stores its result under the
   fingerprint it started with; if the document moved on, the instance reads as stale.
7. Checkpoints are append-only. Restoring one is the way back from an accepted change,
   and a restore reopens the room on a fresh epoch rather than rewinding it.
8. The deployment assumes **one owning API process**. In-flight scheduling and presence
   live in that process; a second one is refused at startup rather than coordinated
   with.

## Vocabulary

[CONTEXT.md](../../CONTEXT.md) defines Project, Graph, Call node, Node instance,
Fingerprint, Result store, Instance state, Run and the room frames. This document uses
those words and adds:

- **Project room** — the transient, in-process set of sockets viewing one Project,
  keyed by `(workspace_id, project_id)`
  ([`realtime/hub.py`](../../apps/api/src/grafy_api/realtime/hub.py)). It publishes; it
  is never the source of truth.
- **Project head** — the latest durable draft: the whole Project document plus
  `room_epoch`, `collaboration_sequence`, `checkpoint_sequence` and
  `checkpoint_revision`
  ([`project_contracts.py:271`](../../apps/api/src/grafy_api/project_contracts.py)).
- **Project room session** — one live socket, with a server-assigned
  `project_room_session_id`. It is not an actor, an auth session, or an authorization
  boundary.
- **Batch** — the ordered list of Project commands in one submission, identified by one
  `command_id`.
- **Room epoch** — the uuid4 identity of one run of a Project's collaboration. A
  checkpoint restore mints a new one so every participant must rehydrate.

Actor, auth session, capability snapshot and presence keep the meanings the
[authentication and workspace design](authentication-and-workspace-tenancy.md) gives
them; ADR 0020 changed none of them.

## Identity: what a room is addressed to

The socket is
`/v1/workspaces/{workspace_id}/projects/{project_id}/room`
([`collaboration/views.py:138`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py),
built by
[`project-room-url.ts`](../../apps/web/src/features/workbench/room/project-room-url.ts)).
There is no graph id in the address: a participant is in the Project's room, and names a
Graph in each command or presence frame that needs one.

**Admission is authorization, in this order.** `Origin` must equal the configured
public origin; then the handshake authorizes `join_project_room` and requires
`view_project` on the resolved Workspace; then the head is read. A Project of another
Workspace, or one with no head, is a `404` — the same answer as one that was never
opened — and a disabled user is a `401`
([`views.py:139-200`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py)).
Capability names are the ones in
[`domain/identity.py:34`](../../libs/core/src/grafy_core/domain/identity.py):
`view_project`, `view_artifacts`, `view_runs`, `join_project_room`, `publish_presence`,
`create_project`, `edit_project`, `checkpoint_project`, `start_run`, `cancel_run`,
`manage_secrets`, `delete_project`, `manage_members`, `rename_workspace`.

**Commands carry a Graph id when they act inside one.** The command union is
[`domain/collaboration.py:306-366`](../../libs/core/src/grafy_core/domain/collaboration.py):

| Level | Kinds |
| --- | --- |
| Project | `rename_project`, `add_graph`, `rename_graph`, `remove_graph`, `refresh_node`, `add_call_node` |
| Inside one Graph | `in_graph(graph_id, command)` wrapping `add_node`, `duplicate_node`, `remove_nodes`, `move_nodes`, `update_node_configuration`, `update_node_layout`, `set_node_input_plugs`, `update_node_configuration_and_input_plugs`, `set_node_artifact_type_binding`, `clear_node_artifact_type_binding`, `add_edge`, `update_edge`, `remove_edges`, `add_origin`, `update_origin`, `remove_origins`, `replace_document`, `replace_presentation`, `move_artifact_viewers`, `move_annotations` |

`rename_graph` and `rename_project` are Project-level commands, not bodies of a Graph
document: a Graph's name is not inside its document, so a save that carries a new name
submits `[rename_graph, in_graph(replace_document)]` as one batch
([`Workbench.tsx:1346-1362`](../../apps/web/src/features/workbench/ui/Workbench.tsx)).
`rename_project` and `rename_graph` both carry the name they expect to replace, which is
where their conflict policy lives.

**Presence names the Graph it is about.** A participant frame carries
`graph_id: str | None` so a collaborator's cursor and selection are attributed to the
Graph they are looking at, while every participant of the Project shares one list
([`realtime/protocol.py:84-101`](../../apps/api/src/grafy_api/realtime/protocol.py)).

Deleting a Project closes its room with `4010 / project_deleted`
([`projects/views.py:283`](../../apps/api/src/grafy_api/v1/routes/projects/views.py),
[`hub.py:34`](../../apps/api/src/grafy_api/realtime/hub.py)); a membership change or
revocation closes that user's rooms
([`workspaces/views.py:204`](../../apps/api/src/grafy_api/v1/routes/workspaces/views.py)).

## Sequence: two counters on one head

A head carries one monotonic **`collaboration_sequence`** and the **`checkpoint_sequence`
/ `checkpoint_revision`** pair marking the last durable save
([`domain/collaboration.py:1178-1242`](../../libs/core/src/grafy_core/domain/collaboration.py)).
The head's own invariants are the contract: `checkpoint_sequence ≤
collaboration_sequence`, `checkpoint_revision ≥ 1`, and fully checkpointed means the two
sequences are equal. A new Project, a copy, and a restore all open at
`collaboration_sequence = 0` with the checkpoint pair already set
([`for_existing_project`, `domain/collaboration.py:1245`](../../libs/core/src/grafy_core/domain/collaboration.py)),
so a Project's head is born fully checkpointed at revision 1 and its first accepted batch
lands at sequence 1
([`stage_project`, `project_creation.py:43-86`](../../libs/core/src/grafy_core/application/project_creation.py)).

- **`collaboration_sequence`** advances exactly once per accepted batch and implies no
  durable save. It orders edits.
- **`checkpoint_revision`** advances only when `checkpoint` is called and marks an
  immutable `ProjectCheckpoint`. It is what a durable state is addressed by.

**What a caller asserts.** Everything that changes the document asserts the
`collaboration_sequence` it read plus the `room_epoch` it read — never a checkpoint
revision:

| Operation | Asserts | On mismatch | Ref |
| --- | --- | --- | --- |
| Submit a batch | `room_epoch`, `observed_sequence` | head conflict, if the epoch differs or the head has already passed what you read | [`application/collaboration.py:360-385`](../../libs/core/src/grafy_core/application/collaboration.py) |
| Submit a batch containing `in_graph(replace_document)` or `in_graph(replace_presentation)` | the **exact** current sequence | head conflict | [`command_requires_exact_sequence`, `domain/collaboration.py:426`](../../libs/core/src/grafy_core/domain/collaboration.py) |
| Checkpoint | exact `collaboration_sequence` and epoch | head conflict; already-checkpointed heads replay their revision | [`application/collaboration.py:419-470`](../../libs/core/src/grafy_core/application/collaboration.py) |
| Configure or remove a node secret | exact `collaboration_sequence` | `409` before secret storage is touched | [`node_secrets.py:206,263`](../../apps/api/src/grafy_api/node_secrets.py) |
| Delete or copy a Project | exact `collaboration_sequence` and epoch when supplied; without them, an uncheckpointed head is refused | head conflict / uncheckpointed | [`application/collaboration.py:624-741,742-790`](../../libs/core/src/grafy_core/application/collaboration.py) |
| Start a Run | nothing | — a Run is planned against the live head document as it reads it | [`runs/service.py:174`](../../apps/api/src/grafy_api/runs/service.py) |

**Why the number the canvas holds is not automatically the right one.** A batch is
accepted against the *latest* head, not against the sequence you stamped: ordinary
commands carry their own compare-and-set (`expected_name`, `expected_generation`,
plug membership), so a stale-but-lower `observed_sequence` rebases rather than fails.
That is exactly why a whole-document or whole-presentation replace, which carries no
prior value to compare, is refused unless it arrives at the exact sequence its author
read. Two consequences a writer must get right:

1. A caller editing outside the room must read `GET …/projects/{id}/head` first and
   stamp the submission with *that* sequence, not with whatever the canvas last
   rendered.
2. The checkpoint that follows must assert the sequence the batch was **accepted at**
   (`receipt.accepted_sequence`, or the head returned by the submission), never the one
   it read before submitting — otherwise a peer's interleaved batch makes your own work
   uncheckpointable. The save path does exactly this
   ([`useSavedGraphLifecycle.ts:119-151`](../../apps/web/src/features/workbench/ui/useSavedGraphLifecycle.ts)).

High-frequency gestures do not touch either counter until the gesture commits: cursor
updates are presence, positions under a held pointer are drag previews, and pointer
release submits one `move_nodes`. Configuration edits commit on blur or a bounded
debounce, not per keystroke. Compound gestures (a generic binding plus the edge that
needs it) are one batch.

## Transport: the Project room socket

**Ordering at join is deliberate.** The route registers the session with the hub, reads
the head, writes `room.ready` straight to the socket, and only then activates it
([`views.py:211-236`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py)).
Between registration and activation the hub buffers the session's outbound queue, so a
batch committed while the head was being read arrives *after* the head it moved past,
never instead of it.

**One writer after activation.** Every frame a session receives goes through one sender
task fed by one bounded queue of 64
([`hub.py:27`](../../apps/api/src/grafy_api/realtime/hub.py)). That is what keeps
fanout, private receipts and heartbeats in one FIFO, and what makes a slow consumer
bounded: a full queue closes the session with `4009 / slow_consumer` rather than
buffering. Presence frames are dropped at a queue depth of 48 before that point.
`room.ready` is the one frame written directly, before activation.

**The message set** is versioned by `protocol_version: 1`, and both sides validate
strictly — server models are `extra="forbid"`, and the TypeScript parser in
[`room/protocol.ts`](../../apps/web/src/features/workbench/room/protocol.ts) rejects a
flat head or a Graph document without its Graphs rather than papering over them.

| Direction | Types |
| --- | --- |
| client → server | `project.command.submit`, `presence.update` — and nothing else ([`realtime/protocol.py:294-303`](../../apps/api/src/grafy_api/realtime/protocol.py)) |
| server → client | `room.ready`, `room.rehydrate`, `room.heartbeat`, `project.command.accepted`, `project.command.receipt`, `project.command.rejected`, `presence.join`, `presence.leave`, `presence.update`, `run.started`, `run.finished`, `instances.changed`, `agent.turn.started`, `agent.event.appended`, `agent.delta`, `agent.turn.finished` |

`room.ready` carries workspace id, project id, room session id, actor presentation, the
capability snapshot with its authorization version, the complete head, the current
participants, `active_runs`, `instances`, and a `registry_marker` the client parses but
does not yet act on. A message type the
client does not know is ignored. A wrong protocol version stops the session terminally
(`protocol_incompatible`) and the user must reload; a known type that fails to parse — a
flat head, a Graph document without its Graphs — is a retryable `protocol_error` that
reconnects and rehydrates.

**Heartbeats are server-driven.** A per-connection timer fires every
`realtime.graph_room_heartbeat_seconds` (default 15s) and, before it emits
`room.heartbeat`, re-authorizes membership: revocation closes with `4004 /
access_revoked`, a changed authorization version closes with `4003 / permissions_changed`
([`views.py:365-425`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py)).
It is a timer rather than a receive timeout because the ASGI receive is an anyio
checkpoint, and a chatty client cannot starve the revalidation. This is also the safety
net for a lost post-commit invalidation, which is why permission changes are handled by
*closing* a session rather than by pushing a new capability snapshot into it.

**Close codes** are shared between hub and client
([`hub.py:30-34`](../../apps/api/src/grafy_api/realtime/hub.py),
[`room/protocol.ts:12-16`](../../apps/web/src/features/workbench/room/protocol.ts)):
`4003` permissions changed, `4004` access revoked, `4008` protocol error, `4009` slow
consumer, `4010` project deleted.

**The client's states** are `idle`, `connecting`, `ready`, `reconnecting`,
`unsynchronized`, `stopped`
([`graph-room-session.ts`](../../apps/web/src/features/workbench/room/graph-room-session.ts)).
A recovery reason (`connection_lost`, `permissions_changed`, `protocol_error`,
`slow_consumer`) keeps the session and retries; a terminal reason (`access_revoked`,
`project_deleted`, `protocol_incompatible`, `reconnect_exhausted`) stops it and drops
every queued batch. Backoff is `min(750 · 2ⁿ, 10 000)` ms for five attempts, after which
reconnection stops until the user asks for it.

**Reconnection** resubmits unacknowledged batches with their original command ids after
the fresh `room.ready` lands. There is no "resolve an unknown command" round trip any
more: resubmitting an already-committed batch is simply a retry, and the server replies
with the original receipt marked `idempotent_replay`
([`views.py:519-536`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py)).

**Head replacement is monotone.** A snapshot or accepted batch is applied only when the
epoch changed or its sequence is not older, so a late HTTP head read cannot wipe a head
the socket already moved forward
([`shouldReplaceCollaborativeHead`, `graph-room-session.ts:88`](../../apps/web/src/features/workbench/room/graph-room-session.ts)).
An epoch change arrives as `room.rehydrate` — a checkpoint restore reopens the room and
publishes it
([`projects/views.py:472`](../../apps/api/src/grafy_api/v1/routes/projects/views.py)).
Full-snapshot recovery is the correctness path; incremental application is the
optimization.

## Commands and batches

**A batch is the unit of acceptance.** `commands` is non-empty on both sides;
`apply_project_commands` folds it over the document and names the index that broke
("rejected at index 3"), because the client resends from there. An accepted batch calls
`head.apply_accepted_batch`, which increments `collaboration_sequence` by one and leaves
the checkpoint pair alone ([`domain/collaboration.py:1015-1060,1208`](../../libs/core/src/grafy_core/domain/collaboration.py)).

**A command id is a promise.** The server stores a keyed HMAC over `(workspace, project,
actor, room_epoch, observed_sequence, commands in order)`; command order is part of the
signature, so the same commands in another order are a different batch
([`command_hmac_digest`, `domain/collaboration.py:390-424`](../../libs/core/src/grafy_core/domain/collaboration.py)).
The same id with the same signature replays the original receipt and moves nothing; the
same id with a different signature is `idempotency_mismatch`. The receipt is re-read
*under the head lock* so two simultaneous submissions of one id cannot both insert a
receipt ([`application/collaboration.py:340-365`](../../libs/core/src/grafy_core/application/collaboration.py)).

**Receipt and broadcast are separate.** Peers get `project.command.accepted`; the
submitter additionally gets `project.command.receipt`. A replay of an already-committed
batch is answered with the private receipt alone and owes no fanout and no instance
republish, because it moved no document
([`_handle_command_submit`, `views.py:466-551`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py)).
They may arrive in either order, so the client correlates by command id and mutates the
confirmed document only from the ordered broadcast. An accepted frame whose sequence is
not `head + 1` in the same epoch pauses sending and asks the driver for a full head
snapshot ([`graph-room-session.ts:726-760`](../../apps/web/src/features/workbench/room/graph-room-session.ts)).

**Conflict behavior belongs to each command**, not to a universal rule. Removing an
absent node is a no-op; a move is revalidated against the latest document; a rename or a
refresh carries the value it expects and conflicts without it; a call node is refused
when the Project has no such Graph; adding a Graph with an id the Project already has is
`duplicate_graph`
([`_apply_project_command`, `domain/collaboration.py:1055-1176`](../../libs/core/src/grafy_core/domain/collaboration.py)).
**Command application is a pure document fold.** Nothing in it consults the plugin
registry: a batch that names an operator this build does not register is accepted, is
fanned out, and stays accepted. That document fails later, at Run planning and at
instance derivation, with the stable codes `unknown_operator` and `invalid_document`
([`runs/views.py`](../../apps/api/src/grafy_api/v1/routes/runs/views.py)), and the room
that cannot derive its own instances says so by opening with an empty list
([`views.py:554-575`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py)).
Connection-shaped validation therefore belongs to the client that draws the edge and to
the derivation that computes it, not to the command layer — which is also why a stored
unsupported node survives until its registration returns or a user removes it.

**The optimistic client keeps one batch in flight.** The outbox holds a FIFO with a cap
of 32 batches, stamps each frame from the confirmed head, pauses sending while a head
refresh is outstanding, and replaces a queued snapshot-style batch with a newer one of
the same kind rather than sending both
([`command-outbox.ts`](../../apps/web/src/features/workbench/room/command-outbox.ts)).
Reaching the cap pauses durable authoring and shows a waiting state; offline editing
beyond it is not supported and the UI must not imply it is. A private field draft stays
browser-private: a remote accepted value never silently erases an active draft, and a
conflicted commit keeps the draft for an explicit retry.

## Runs and instances on the room

A Run is a demand for freshness, so the room carries **many** Runs and the state of the
instances they touch. The frames
([`realtime/protocol.py:155-232`](../../apps/api/src/grafy_api/realtime/protocol.py),
published by [`realtime/run_events.py`](../../apps/api/src/grafy_api/realtime/run_events.py)):

- `run.started` — one `ActiveRunSummary`: run id, root Graph, targets, who started it,
  start time, cancellable.
- `run.finished` — run id, terminal status (`succeeded`, `failed`, `cancelled`,
  `interrupted`), and a bounded error.
- `instances.changed` — `changed` instance states, `removed` instance keys, and the
  `head_sequence` they were derived against.

`room.ready` carries the same two collections as lists: `active_runs` (the Runs that
started before you joined, which you cannot see any other way) and `instances` for every
Graph of the head. If instance derivation fails — the document names an operator this
deployment does not register — the room opens with **no** instances rather than locking
a participant out of the only room that could repair the document
([`views.py:337-363`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py)).

**Frames are events, not answers.** A delta says *read the results again*; REST is the
source of truth: `GET …/projects/{id}/runs`, `GET …/runs/{run_id}`, `POST …/runs`,
`POST …/runs/{run_id}/cancel`, `GET …/graphs/{graph_id}/instances`, and
`GET …/instance-result`
([`runs/views.py`](../../apps/api/src/grafy_api/v1/routes/runs/views.py)). The surface
turns each room push into exactly one read
([`useRunExecution.ts:352-364`](../../apps/web/src/features/workbench/ui/useRunExecution.ts)).
Because a listener cannot tell "the room pushed" from "the list looks the same as last
time", a revision counter travels beside each list: `runsRevision` bumps on
`room.ready`, `run.started` and `run.finished`, `instancesRevision` bumps on
`instances.changed`
([`useProjectRoomSession.ts:49-56,124-143`](../../apps/web/src/features/workbench/room/useProjectRoomSession.ts)).
A push whose list happens to be identical still has to trigger a re-read, which is why
identity of the array is not stood in for the fact that the room spoke. Without a room,
the surface polls, and only while something could still move.

**There is no SSE endpoint.** This is a decision, not an oversight: the per-execution
event journal, its replay window, its heartbeat and its polling fallback all existed to
follow *one* execution that a client had to discover first. With results owned by
instances, that stream would have to be one subscription per Run and would still not
tell you why a node you never ran is stale. What replaced it is the room's three Run and
instance frames plus re-reads of the Run and instance REST collections; instance state
is recomputed and diffed per Project after scheduler transitions and accepted batches,
serialized and coalesced so a slow subscriber cannot block a computation
([`runs/service.py`](../../apps/api/src/grafy_api/runs/service.py),
[`runs/state.py`](../../apps/api/src/grafy_api/runs/state.py)).
The only streaming HTTP response in the API is artifact bytes
([`artifacts/views.py:47`](../../apps/api/src/grafy_api/v1/routes/artifacts/views.py));
nothing in the collaboration path streams events.

**Instance identity.** A node instance is
`(project, graph, call path, node id[, map index])`
([`kernel/instances.py:13`](../../libs/core/src/grafy_core/kernel/instances.py)):
`call_path` lists the call-node ids entered to reach the Graph, outermost first, and is
empty for a Graph run directly; `map_index` is reserved for MAP items and stays `null`
until that decision is taken. Over the wire the client keys its instance map with
`instanceKeyText`, which joins `graph_id`, `call_path` joined by `/`, `node_id` and
`map_index` (empty when `null`) with U+0000
([`room/protocol.ts:798`](../../apps/web/src/features/workbench/room/protocol.ts)).
The composed text deliberately omits `project_id`, which every frame still carries: the
map belongs to one room for one Project, so the Project is already implied.

State is looked up **by instance and never by Run**. The canvas asks for the instance of
the node it is drawing — `(project, open graph, [], node id, null)` — and paints what
that instance's fingerprint holds
([`Workbench.tsx:1425-1441`](../../apps/web/src/features/workbench/ui/Workbench.tsx)).
A Run is a demand that has come and gone; several Runs may have touched one Graph, one
Run may span several Graphs through call nodes, and two calls of the same Graph with the
same inputs share one result. Reading state off a Run would resurrect the behaviour the
rework removed: a value that only the browser which ran something could see, and a
reload that forces a full re-run.

Editing while a Run is active changes nothing about locking: an accepted batch moves
fingerprints, the affected instances go stale in the next `instances.changed`, and a
computation that lands later still stores under the fingerprint it started with, so no
participant sees a wrong value as fresh. Cancelling a Run withdraws that Run's demand
and cancels a computation only when no other active Run needs it
([`runs/service.py:213-250`](../../apps/api/src/grafy_api/runs/service.py)).

## Agents on the room

A turn answers in the room so a second tab sees the answer arrive, and so a browser that
sent the request is not the only one holding the text. The frames
([`realtime/protocol.py`](../../apps/api/src/grafy_api/realtime/protocol.py), published
by [`realtime/agent_events.py`](../../apps/api/src/grafy_api/realtime/agent_events.py))
are scoped by the Project room. They identify the Graph, Agent, conversation
and turn, and carry the relevant receipt, event or text.

- `agent.turn.started` — the turn is running, who started it, and when.
- `agent.event.appended` — one stored event with its `sequence`: the
  question, the finished answer, the turn outcome.
- `agent.delta` — coalesced text with the `offset` it begins at in the stored message,
  so a reader can detect a gap and recover. Deltas do not declare completion.
- `agent.turn.finished` — the outcome and optional detail. Read stored events to recover missed messages.

**Authoritative frames queue, deltas drop.** The three factual frames travel the hub's
queued path, the same one a command receipt does: losing one would leave a participant
missing a message the room said happened. `agent.delta` goes through
`hub.publish_transient`, which uses the hub's drop-if-busy offer. The hub closes a
session whose queue fills ([`hub.py:118-135`](../../apps/api/src/grafy_api/realtime/hub.py)),
and a model streaming quickly can fill it, so queueing deltas would take every
participant off the Project each time someone sent an Agent a long question. A dropped
delta costs one reader one stutter: the stored message is on the conversation route and
the `agent.event.appended` that carries it replaces the streamed text.

**The order is the contract** ([`agents/publishing.py`](../../apps/api/src/grafy_api/agents/publishing.py)):
`turn.started`, then the question's `event.appended`, then deltas, then the answer's
`event.appended`, then any outcome event, then `turn.finished`. Telling a stored event
*after* its flushed text is deliberate — a reader that saw the whole message and then a
partial would put a fragment back over an answer it already had. A delta longer than
`agent_delta_max_text_chars` is discarded rather than truncated: half a message spliced
to the next is worse than none, and the whole message follows as a stored event anyway.

**Telling is never part of the turn.** The receipt and events are committed before a frame
is built, and a publisher that raises loses its telling and a log line only
([`realtime/agent_events.py`](../../apps/api/src/grafy_api/realtime/agent_events.py)).
A participant that missed frames reads the conversation back
(`GET …/conversations/{id}/events`) and the active turn
(`GET …/conversations/{id}/active-turn`); `room.ready` does not carry conversations.

## Presence

Presence explains collaborators without becoming a second document.

- It is keyed by `project_room_session_id`, not actor id, so two tabs of one person are
  two independently expiring cursors; participant UI may group them and show a count.
- Publishing requires `publish_presence`, checked per update at handling time. A client
  that lacks it is dropped silently — presence is best-effort and never an error path
  ([`views.py:438-463`](../../apps/api/src/grafy_api/v1/routes/collaboration/views.py)).
- A frame may carry: the Graph it is about, cursor position in graph coordinates,
  selected node and edge ids, an activity kind (`moving_nodes`, `editing_node`,
  `connecting`) with target ids, live node positions for a drag preview, and a
  session-local sequence. Server-assigned display name and colour come from the room, and
  id lists are de-duplicated and capped.
- A frame must never carry node configuration values, secret names paired with values,
  artifact payloads, progress text copied from computations, viewport or device data, or
  caller-provided HTML, CSS, image URLs or colours.
- Rates: about 20 updates/s server-side (`graph_room_presence_max_updates_per_second`),
  a 50 ms client floor, TTL 5s to clear cursor and activity fields and 2× TTL to drop the
  entry
  ([`grafy_shared/config/realtime.py:16-27`](../../libs/shared/src/grafy_shared/config/realtime.py)).
  An out-of-order or rate-violating update is dropped, not rejected. TTL clears presence,
  never room membership.
- Remote selection is an annotation: it never changes the local React Flow selection or
  keyboard target. Editing activity is a soft claim, not a lock; the command's own
  conflict policy decides who wins. Dragging publishes transient positions and submits
  one durable `move_nodes` on release; a rejected move leaves the confirmed document
  winner and the preview simply disappears.
- Only the local session's own cursor is suppressed; another tab of the same actor stays
  a distinct remote session.

## Where it lives in the web client

The durable document no longer wears React Flow's shape, which is the part of
[ADR 0001](../adr/0001-workbench-feature-architecture.md)'s recorded debt this rework
cleared: the renderer types and the document are now on opposite sides of one adapter.
The `model -> canvas` edge the ADR allows still exists elsewhere (`model/artifact-drop.ts`
imports canvas helpers), so the ADR's wider extraction stays open.

- [`model/graph-document.ts`](../../apps/web/src/features/workbench/model/graph-document.ts)
  owns the graph document as a value: pure application of commands
  (`applyGraphCommandNormalized`), the authored document a save serializes to, and the
  nodes an execution change invalidates. It imports no renderer type.
- [`canvas/graph-document-adapter.ts`](../../apps/web/src/features/workbench/canvas/graph-document-adapter.ts)
  turns React Flow node and edge changes and connection attempts into commands, and adds
  run, execution and progress overlays at render time. An overlay is never written back
  to the document except as a user gesture that becomes a command.
- [`room/`](../../apps/web/src/features/workbench/room) is the collaboration seam:
  `protocol.ts` (wire types and the strict parser), `graph-room-session.ts` (socket,
  confirmed head, presence throttle, reconnect and terminal states), `command-outbox.ts`
  (single in-flight batch, queue cap, head-rehydration gate), `room-command-bridge.ts`
  (accepted commands folded onto the Project head), `useProjectRoomSession.ts` (the React
  surface: head, capability gates, participants, Runs with `runsRevision`, instances with
  `instancesRevision`), `graph-readiness.ts` (one trust policy for every consumer of the
  displayed document) and `project-room-url.ts`.
- `ui/Workbench.tsx` composes; [`ui/useRunExecution.ts`](../../apps/web/src/features/workbench/ui/useRunExecution.ts)
  is the Run surface (a room push is the event, a REST read is the answer, polling only
  while there is no room); [`ui/useSavedGraphLifecycle.ts`](../../apps/web/src/features/workbench/ui/useSavedGraphLifecycle.ts)
  is the out-of-room save-and-checkpoint path.

One rule holds these apart: a durable gesture may act only on a confirmed head. A session
that is not `ready`, or has no confirmed head, is untrusted
([`graph-readiness.ts:12`](../../apps/web/src/features/workbench/room/graph-readiness.ts)),
and [`apps/web/src/architecture.test.ts`](../../apps/web/src/architecture.test.ts) fails
the build on a module cycle or a feature reaching into a route module.

## State ownership

| State | Owner | Durable | Shared |
| --- | --- | --- | --- |
| Project name; each Graph's name, nodes, positions, configuration, plugs, artifact-type bindings, edges, projections, conversions, collection modes, origins, layout; Artifact Viewer structure and annotations | Project head, via accepted batches | On checkpoint | Yes |
| Cursor, remote selection, editing activity, soft claim, drag preview | room session | No; expires | Yes, to room participants |
| Active Runs, who started each | `RunService` rows; room frames announce | Run records are durable; in-flight scheduling is not | Yes |
| Node instance state (fresh, queued, running, failed, stale) | derived from document + result store + in-flight set | Never stored | Yes |
| Last result and last failure pointer per instance | result store plus the per-instance pointer | Yes (append-only, no GC yet) | Yes |
| Viewport, zoom, local selection, open drawers, field drafts, outbox, private viewer interaction | browser | No | No |
| Secret values | encrypted node-secret store | Yes | Never |
| Secret configured/unconfigured metadata | node-secret module over protected HTTP | Yes | Refetched per Graph by authorized clients |

Nothing Project-scoped is persisted in the browser today: the local keys that exist
(`grafy-theme`, `grafy-side-panel-*`, the canvas grid setting) are device-wide
preferences, which is where such a preference belongs. Anything Project-scoped that ever
is persisted must never be keyed by a workspace slug and a Graph id alone — slug-to-id
resolution is not atomic, so a reused slug could load someone else's layout. Key it by
`(user_id, workspace_id, project_id)`, clear it on sign-out, actor change or view
revocation, and re-key only after an authorized bootstrap. Artifact Viewer structure is
not browser state at all: it lives on the shared head.

## Node secrets, the head, and four traps

Secret values keep their own protected HTTP boundary and never become room frames.
Configure and remove require `manage_secrets`, assert the head, and never checkpoint —
which is what makes an editor with `checkpoint_project` unable to reach an
owner-managed secret row indirectly
([`node_secrets.py:194-280`](../../apps/api/src/grafy_api/node_secrets.py)). A secret's
revision enters the fingerprints of the nodes that declare it, so the next derivation
re-reads it and an affected instance simply goes stale
([`runs/facts.py:196-235`](../../apps/api/src/grafy_api/runs/facts.py)).

Four things in this corner are not guessable from the shapes, and are documented here
so nobody re-derives them:

1. **The listing and the writes address a Graph differently.**
   `GET …/projects/{id}/node-secrets` takes `graph_id` as a **query parameter that
   defaults to `MAIN_GRAPH_ID`**
   ([`node_secrets/views.py:41`](../../apps/api/src/grafy_api/v1/routes/node_secrets/views.py)),
   while `PUT` and `DELETE` carry it in the **path** as
   `/graphs/{graph_id}/nodes/{node_id}/secrets/{name}`
   ([`views.py:57,91`](../../apps/api/src/grafy_api/v1/routes/node_secrets/views.py)).
   A listing call that omits `graph_id` is therefore not an error — it silently reads
   the main Graph's secrets and can report a secret as unconfigured for a node that sits
   in another Graph of the same Project. Always send the Graph you are looking at.
2. **A secret write's own response cannot refresh the client's head token.**
   `NodeSecretStatusResponse` is `{node_id, name, configured}` and carries no Project,
   no Graph, no epoch and no sequence
   ([`node_secrets/models.py:25`](../../apps/api/src/grafy_api/v1/routes/node_secrets/models.py)).
   A caller that overwrites its stored head token from that response loses it. This is
   survivable only because configure and remove **do not advance the collaboration
   sequence** — they lock the head, compare it, and write a secret row — so the head
   token read before the write is still the right one afterwards. Any future change that
   makes a secret write advance the sequence breaks every caller that relied on this.
3. **A fresh head's sequence really is `0`, and `ge=0` does not mean `0` is a safe
   guess.** A new Project's head opens at `collaboration_sequence = 0`
   ([`domain/collaboration.py:1245-1262`](../../libs/core/src/grafy_core/domain/collaboration.py))
   and the delete route declares `expected_sequence: int | None = Query(ge=0)`
   ([`projects/views.py:258`](../../apps/api/src/grafy_api/v1/routes/projects/views.py)).
   A zero therefore validates and then asserts a real precondition, so a client that has
   not read a listing must send **nothing** rather than a plausible-looking `0`: with no
   pair supplied, the server refuses an uncheckpointed head instead of deleting what
   nobody looked at
   ([`application/collaboration.py:742-790`](../../libs/core/src/grafy_core/application/collaboration.py)).
   The web client encodes this by omitting both parameters unless it holds both
   ([`lib/api/projects.ts:84-102`](../../apps/web/src/lib/api/projects.ts)).
4. **The head a secret write asserts moves without any checkpoint the client can see.**
   Every accepted command batch advances the head's `collaboration_sequence`, whether or
   not the Project has checkpointed, while the web client re-reads the secret listing only
   when a checkpoint lands or a Graph is opened or saved. So the token from that listing
   can name a head that one dragged node — or one peer's batch — has already retired, and
   the exact-sequence assert turns
   an ordinary edit into a 409. The client recovers by re-reading the listing after that
   409 and sending the same write once more at the sequence the new answer names; a second
   conflict is reported with the newer token held rather than chased
   ([`useNodeSecrets.ts`](../../apps/web/src/features/workbench/ui/useNodeSecrets.ts)).
   The recovery is the reason the token stays the listing's own: a client that re-addressed
   a write from a locally guessed sequence would be asserting a head it never read, which
   is what trap 3 forbids.

## Authorization and sensitive state

Login, membership and workspace tenancy belong to the
[authentication and workspace design](authentication-and-workspace-tenancy.md). For
collaboration:

- Every room frame, HTTP command, checkpoint, Run, secret and delete operation is
  authorized at handling time against the effective capability (role ∩ PAT scope ∩
  capability). Socket admission is not continuing authority: the heartbeat loop is the
  backstop for an authority change the post-commit invalidation missed.
- Membership and role changes close affected sessions rather than rewriting their
  capability snapshot in place. A still-authorized browser rejoins and gets a fresh
  snapshot and authorization version before resuming protected traffic.
- `view_project` revocation closes with `4004`; the client must not fall back to its
  network-failure behavior. It stops HTTP work, clears the Project document, Run and
  artifact references, purges actor/workspace/Project-scoped caches and personal state,
  and navigates to a safe authorized route without a local confirmation that could
  retain the revoked data.
- Auth-session expiry is not revocation: it pauses protected traffic and requires a fresh
  join. Renewal for the same actor may resolve in-flight command ids; a different actor
  purges the previous actor's drafts, batches and personal state, and replays none of it.
- Identity is server-derived. Workspace id, project id, actor id, room session id and the
  effective authorization are never trusted from a frame; the HMAC is computed over the
  server-derived scope.
- Bounded models everywhere: `extra="forbid"`, capped id lists, capped details, capped
  error text.
- Audit records are metadata-only — operation, outcome, resource id, error code — and
  never copy a command body, a configuration value or a secret
  ([`application/collaboration.py:_audit`](../../libs/core/src/grafy_core/application/collaboration.py)).
  Logs carry ids, kind, sequence, outcome and safe error code, never a whole frame.
- Secret values must never appear in a snapshot, an accepted batch, a presence frame, a
  protocol error or a captured log. The secret suite covers storage, binding, head
  gating and key rotation
  ([`tests/integration/node_secrets/test_node_secrets.py`](../../tests/integration/node_secrets/test_node_secrets.py));
  no test yet asserts the room's silence about a configured value, so treat that as
  required coverage before anything secret-shaped is added to a frame.

## Failure behavior

| Failure | Required behavior |
| --- | --- |
| Socket interruption | Keep the confirmed head visible, mark the session `unsynchronized`, expire remote presence, drop the active-Run view, reconnect with a full snapshot, replay unacknowledged batches under their original ids. |
| Reconnect attempts exhausted | Stop with `reconnect_exhausted`, reject queued batches, and offer an explicit retry rather than an infinite loop. |
| Auth session expired | Stop commands and observation, re-authenticate, rejoin. Resolve pending ids only for the same actor; purge rather than replay after an actor change. |
| Role or capabilities changed | Close with `4003`; rebuild from the newly authorized head without unsent optimistic commands; retain at most explicitly copyable draft text while view remains. |
| View capability revoked | Close with `4004`; clear presence and all actor/workspace/Project-sensitive client state and navigate away. Do not leave the Project visible. |
| Project deleted (locally or remotely) | Close with `4010`; the remote delete already committed and cannot wait for local confirmation. |
| Batch acknowledgement lost | Resubmit the same command id; a committed batch returns its original receipt as `idempotent_replay` and moves nothing. |
| Batch rejected | Restore confirmed server state, keep unrelated pending batches, show the operation and the index that failed. |
| Head sequence gap | Pause sending, request a full head snapshot, resume once it lands. |
| Presence update dropped | Nothing to do; a later update supersedes it. |
| Slow collaborator | Drop presence at depth 48, close at depth 64 with `4009`, recover from a snapshot. |
| Instance derivation fails for the document | Open the room with no instances and log it; the room is the way to fix the document. |
| API restart | Heads, receipts and checkpoints survive. Unfinished Runs are marked `interrupted`, stored results stay fresh, so a rerun resumes from the fresh frontier. All presence disappears. |
| Graph edited while a Run is active | No lock. Affected instances go stale; computations in flight still store under their original fingerprint. |

## Operational hazards

- **One API owner.** In-flight scheduling, per-Project publish coalescing and presence
  are process state, so startup takes an exclusive file lock and refuses a second owner;
  `WEB_CONCURRENCY`/`UVICORN_WORKERS` other than 1 fails startup
  ([`single_owner.py:26-58`](../../apps/api/src/grafy_api/single_owner.py)).
  Horizontal ownership needs leases, shared publication, shared scheduling and
  connection draining — none of which is provided by adding another socket.
- **Do not add a broker abstraction before a second owner exists.** Presence and
  publication have one adapter on purpose.
- **The result store grows without bound.** It has no garbage collection; collecting
  results no instance pointer or checkpoint references is required before production use
  (ADR 0020 consequence).
- **The heartbeat is the authority backstop.** With it disabled
  (`graph_room_heartbeat_seconds = 0`, which tests do), a membership change only reaches
  a session through the post-commit invalidation path.
- **Instance state is derived on demand.** Nothing stores it, so a room that cannot read
  the catalog cannot describe its own document — which is why that failure degrades to an
  empty instance list instead of a closed room.

## What proves it

Tests cross the same interfaces production uses
([`tests/unit/architecture/test_import_boundaries.py`](../../tests/unit/architecture/test_import_boundaries.py)
keeps the route/execution/realtime seams honest):

- [`tests/unit/application/test_collaboration.py`](../../tests/unit/application/test_collaboration.py)
  — batch acceptance, idempotency, checkpointing, restore, copy, delete.
- [`tests/unit/api/test_project_head_transport.py`](../../tests/unit/api/test_project_head_transport.py)
  — head transport and command submission shapes.
- [`tests/unit/api/test_project_node_secrets.py`](../../tests/unit/api/test_project_node_secrets.py)
  — secret addressing, head assertion, capability split.
- [`tests/integration/collaboration/test_project_room.py`](../../tests/integration/collaboration/test_project_room.py)
  and
  [`test_collaboration_acceptance.py`](../../tests/integration/collaboration/test_collaboration_acceptance.py)
  — two sessions, join ordering, presence, revocation, Run frames.
- [`tests/unit/runs/`](../../tests/unit/runs) — Run service, instance state, results.
- [`tests/integration/node_secrets/test_node_secrets.py`](../../tests/integration/node_secrets/test_node_secrets.py)
  — a secret is addressed by Project and Graph, only writes are head-gated, and an
  unavailable operator leaves a secret dormant rather than dropping it.
- [`room/graph-room-session.test.ts`](../../apps/web/src/features/workbench/room/graph-room-session.test.ts),
  [`command-outbox.ts`](../../apps/web/src/features/workbench/room/command-outbox.ts)
  tests — reconnect, replay, queue caps, head replacement.
- [`tests/fixtures/project_room_ready.v1.json`](../../tests/fixtures/project_room_ready.v1.json)
  keeps the Python and TypeScript protocol shapes compatible.

## Open questions

These are places where the code looks wrong rather than merely undocumented. They are
recorded here rather than written down as intended behavior:

1. **The client's `room.heartbeat` handling is unreachable.** `handleMessage` returns
   early for any frame whose `type` is `room.heartbeat` before parsing
   ([`graph-room-session.ts:525-532`](../../apps/web/src/features/workbench/room/graph-room-session.ts)),
   so the handler that would update `authorizationVersion` and fire
   `onAuthorizationVersionChange`
   ([`graph-room-session.ts:628-634`](../../apps/web/src/features/workbench/room/graph-room-session.ts))
   never runs, and no consumer passes that listener anyway — the hook's options do not
   offer it. The heartbeat's *server* half is load-bearing (it is what re-authorizes and
   closes), so the frame is not dead; the client half is. Authorization changes reach the
   client through the close it triggers, never through the frame. The dead branch, the
   listener and the `authorizationVersion` field it would be the only writer of after
   join are removable.
2. **No order is promised for `activeRuns`.** The `room.ready` snapshot comes from a
   listing ordered `created_at DESC`
   ([`repositories/runs.py:213`](../../libs/persistence/src/grafy_persistence/adapters/repositories/runs.py),
   [`in_memory.py:1042`](../../libs/core/src/grafy_core/runtime/in_memory.py)) while a
   locally observed `run.started` appends, so a client that joined before a Run began and one
   that joined after can see the two in the opposite order. Nothing may depend on it: the
   activity bar filters by Graph and counts, and a Run is addressed by its id. A surface that
   ever wants "the newest Run" must sort on `created_at` rather than trust the list.
3. **A secret write publishes nothing.** [CONTEXT.md](../../CONTEXT.md) says instance
   state is recomputed after scheduler transitions, accepted batches *and secret
   changes*, and the derivation does re-read secret revisions
   ([`runs/facts.py:209`](../../apps/api/src/grafy_api/runs/facts.py)), but no room frame
   is emitted from the secret routes
   ([`node_secrets/views.py`](../../apps/api/src/grafy_api/v1/routes/node_secrets/views.py)).
   Peers see a newly-configured secret's effect on freshness only at the next batch or
   transition. Either the write should call `runs.project_changed`, or the vocabulary
   should stop claiming secret changes are a recompute trigger.

## Gone

Removed from this document rather than kept beside the new text, because ADR 0020 removed
the thing itself:

- rooms, heads, revisions, commands, presence and execution slots keyed by
  `(workspace_id, graph_id)`;
- `graph.command.submit/accepted/receipt/rejected/resolve` and the epoch-reset
  `graph.command.resolve` round trip (a resubmitted idempotent batch replaced it);
- the one-active-execution-per-graph invariant, its active slot, `ActiveExecutionSummary`
  and the start-race that returned the same summary to the loser;
- the execution event journal, its SSE endpoint, bounded replay, `replay_truncated`,
  polling fallback and the per-node "observation snapshot";
- saved-graph revision as the identity of an execution or of materialized outputs, and
  the checkpoint-that-a-run-start-creates-or-reuses;
- the graph-head persistence sketch (tables, room-epoch reset on full-document
  replacement, sequence-1 bootstrap), superseded by the Project head and its checkpoint
  pair;
- Module publication, releases and pins, and the materialized output binding — see ADR
  0020 and ADR 0016, which it supersedes;
- the seven-phase migration plan and its per-phase exit criteria, all of which have been
  executed.

Alternatives that ADR 0020 does not already record, and which still hold: a general CRDT
document (the graph's invariants still need a server-side command module, and offline
authoring and character-level text merge are non-goals), arbitrary JSON Patch (callers
would need the storage shape and compound invariants would be fragile), and a broker
abstraction before a second API owner exists.
