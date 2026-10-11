# ADR 0014: Apply graph command batches as validated steps and broadcast entity diffs

- **Status:** Proposed
- **Date:** 2026-10-11
- **Scope:** Collaborative graph command application, the graph-room protocol,
  and the Workbench's confirmed head and authored document
- **Amends:** [ADR 0002](0002-server-authoritative-workbench-collaboration.md):
  the server broadcasts an entity diff, not only the accepted command, and a
  compound transition is a batch of commands rather than a dedicated command
  kind

## Context

The collaborative head is an immutable `SavedGraphDocument`. A client submits
one graph command; the server applies it, validates the result, persists it,
and broadcasts the accepted command to the room.

`_apply_graph_command` applies all 22 command kinds in one function. The
kinds have only six shapes: insert, remove, move, compare-and-set one node
field, compare-and-set a whole entity, and wholesale replace. Because each kind
is written out separately, the same rules diverge:

- compare-and-set uses five different equality checks;
- cascade rules (what is dropped when a node or input plug goes away) live in
  three places;
- `move_artifact_viewers` and `move_annotations` rebuild
  `GraphPresentationDocument` field by field, so a new presentation field
  would be reset silently;
- patching one node by id is written out seven times.

Gestures that must change several things atomically got their own command
kind, for example `update_node_configuration_and_input_plugs`. Each new
gesture of that kind adds a kind, and its logic repeats parts of the
single-purpose kinds.

The browser applies the same commands with a TypeScript copy of the logic in
two places: the room session replays every accepted command onto its
confirmed head (`applyRoomCommandToHead`), and the Workbench replays remote
commands onto the authored document. When the copies disagree and the
TypeScript side does not throw, a peer keeps a different graph until it next
rehydrates. Nothing detects that. The author's own optimistic document is never
reconciled with the server result.

Every rejection reaches the client as `command_rejected`, so the client cannot
tell a stale compare-and-set value from an invalid document and always reloads
the head.

## Decision

### A command batch is the unit of acceptance

A client submits an ordered, non-empty batch of graph commands for one graph.
The batch has one command id, is accepted or rejected as a whole, and advances
the collaboration sequence by exactly one. A single command is a batch of one.

`graph.command.submit` and `POST /graphs/{id}/commands` gain `commands`, an
ordered batch of at most 64 commands, alongside the existing `command` field
until every client sends batches; a submission sets exactly one of the two. The
idempotency HMAC covers the canonical batch, and a batch of one hashes exactly
like the single-command submissions that predate batches, so receipts stored
before batches keep matching their retries. A batch requires the exact observed
sequence when any of its commands does. MCP authoring uses the same
collaboration application and therefore the same batches.

Batching keeps a multi-edit gesture (paste, delete with cleanup, schema builder
edits) to one request, one transaction, and one broadcast, instead of a queue
of separately sequenced commands aimed at the same document.

### Commands expand into assertion and change steps

The server expands every command into steps through the command's own
`steps()` method, so the type checker requires every command kind to define
its expansion and there is no central dispatch:

- an **assertion step** checks the current document and changes nothing. A
  command's `expected_*` fields become assertion steps. Assertions stay on the
  commands; there is no standalone assertion command on the wire.
- a **change step** returns a new document.

The batch's steps run in order. The first failing step rejects the batch.
Rollback discards the intermediate documents: they were never persisted, and
the head still holds the starting document.

### Validate after every change step

Every change step produces a validated `SavedGraphDocument`. A failure names
the step that caused it rather than surfacing at the end of the batch.

Document validation runs on every change step, but pydantic does not
re-validate a nested model it is handed, so a presentation edited with
`model_copy` skips `GraphPresentationDocument`'s own validator; the
document-level checks (for example, links must name existing nodes) still run.
Today's presentation edits (moving items, dropping links with a removed node)
cannot break the presentation's rules. A future presentation edit that adds or
retargets items must validate the new presentation explicitly.
Document validation is structural (unique ids and references to existing
nodes, plugs, and ports), so a gesture expressed as several single-purpose
commands passes through valid intermediate documents.

### Change logic lives on `SavedGraphDocument`

Each primitive edit is one `SavedGraphDocument` method, and that method owns
its cascades: removing a node drops its edges, origins, and the card links it
sources; replacing a node's input plugs drops the edges and origins that
targeted a removed plug. Presentation changes go through `model_copy`, never a
field-by-field rebuild. Steps call these methods and contain no cascade logic
of their own. Replacing a node always applies the input-plug cascade (a no-op
when the plugs are unchanged), so every node edit goes through one method.

### Uniform semantics

- **Remove** skips ids that no longer exist. Two people deleting the same node
  both succeed.
- **Move and update** reject a missing id with a specific code such as
  `missing_node`.
- **Compare-and-set** uses one comparison everywhere: equality of the
  canonical JSON form (`model_dump(mode="json")`).

### Compound command kinds become batches

The Workbench sends `update_node_configuration_and_input_plugs` as the batch
`[replace_node_configuration, set_node_input_plugs]`. `replace_node_configuration`
is a new primitive that replaces a node's whole configuration, guarded by
`expected_config`; the existing per-field `update_node_configuration` cannot
delete a key. The server keeps accepting the compound kind by expanding it
into the same steps, and retires it once no client sends it.

### Rejections carry a specific code

`graph.command.rejected` carries the failing step's `error_code` (for example
`field_conflict`, `missing_node`, `invalid_document`) and `command_index`, the
index of the failing command in the batch. The client may rebuild and resubmit after a
compare-and-set conflict instead of always reloading the head.

### Broadcast an entity diff

`graph.command.accepted` gains `diff`, computed by the server from the
documents before and after the batch. The diff lists, per collection (nodes,
edges, origins, viewers, links, bindings, annotations, plus the graph name),
the entities whose value changed, keyed by id, each with `before` and
`after`. `before` is `null` for an insert and `after` is `null` for a removal.

All seven collections are always present; entries are keyed by sorted id and
hold the entity's canonical JSON (`model_dump(mode="json")`), and an entity
appears only when that JSON changed. Peers apply the diff to their confirmed
head instead of replaying the command: a changed entity keeps its place, a
removed one goes, and a new one is appended in key order. A diff does not
carry collection order, so after a batch inserts several entities a peer's
order can differ from the server's until it next loads the head; nothing reads
meaning from that order. Applying a diff needs no graph logic and cannot fail on graph rules;
it can fail only on a sequence gap, which reloads the head as today. The
`command` field stays in the message during migration.

This does not reverse ADR 0002's rule that the protocol exposes no arbitrary
JSON Patch: clients still submit semantic commands; the diff is server output
only, keyed by entity id rather than by array position.

### The author's document follows the confirmed head

The Workbench's authored document is the confirmed head with the pending local
batches applied on top. A batch counts as pending until its own accepted
message arrives; from then on the diff already contains it. When an accepted diff arrives, the authored document
is rebuilt from the new confirmed head and the batches still pending. The
TypeScript command logic remains for instant local feedback, and any mismatch
with the server lasts only until the server's diff arrives.

### Diffs are undo-ready

Because every diff entry keeps `before` and `after`, a later undo can submit
the inverse diff guarded by compare-and-set on the `after` values. An undo
then reverts only the user's own change and is rejected if someone else has
edited the same entity since. Undo is out of scope for this ADR.

## Consequences

- One function per primitive edit, one place per cascade rule, and one
  compare-and-set comparison replace the 22-way dispatch.
- Moving logic onto `SavedGraphDocument` grows `saved_graphs.py` while
  shrinking `collaboration.py`, so `scripts/complexity_ratchet.py` compares the
  summed total of the changed files rather than each file's own total; the
  per-function checks are unchanged.
- New gestures compose existing commands instead of adding command kinds.
- Peers cannot silently diverge; the author's document converges on every
  accepted diff.
- Accepted messages grow by the size of the diff. A diff is bounded by the
  entities the batch touched, not by the document size.
- Validating after every step costs one document validation per change step.
  This is acceptable at current graph sizes and can be revisited by measuring.
- The protocol change ships behind the existing `protocol_version: 1` as
  additive fields; removing `command` from accepted messages and the compound
  kinds from submissions is a later, separate change.

## Delivery

Each item is one pull request; each keeps the existing test suite and the
complexity ratchet (`scripts/complexity_ratchet.py`) green.

1. `SavedGraphDocument` primitive edit methods with their cascades.
2. Steps, command expansion, and batch application replacing
   `_apply_graph_command`; uniform remove, missing-id, and compare-and-set
   semantics.
3. Batch submission (`commands`) and `replace_node_configuration`; the
   Workbench sends the schema-builder gesture as a batch.
4. Specific rejection codes and the failing command index on the wire.
5. Entity diff in accepted messages; peers apply the diff; the authored
   document is rebuilt from the confirmed head plus pending batches.
