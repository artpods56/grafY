# ADR 0020: A Project holds graphs, and results belong to nodes

- **Status:** Proposed
- **Supersedes:** ADR 0016 (the Module half: in-project calls replace published
  Modules until cross-project reuse returns), the materialized-output binding
  model that issue #190 extends
- **Amends:** ADR 0002 and ADR 0014 (the collaborative document and its command
  batches become Project-scoped)
- **Related:** `docs/design/workbench-realtime-collaboration.md`,
  `docs/design/modules-conceptual-model.md`, `apps/api/src/grafy_api/execution/README.md`,
  `CONTEXT.md` (Saved graph, Module, Upstream output pin, Materialized output binding,
  Graph execution history, Invocation cache entry)

## Context

The collaborative document *is* one graph, and a run owns that graph while it runs.
Three things users hit follow directly from that shape:

1. **Getting one value means rerunning the graph.** Results belong to an execution, not
   to a node. "Run selected" pins upstream values from what the browser remembers of
   the last run (`execution-plan.ts`), so after a reload, a collaborator's run or an
   upstream edit the only way forward is **Run with dependencies**.
2. **One document runs one thing.** The room advertises "the one active graph
   execution" (`ActiveExecutionSummary`) and the web holds a single run lifecycle for
   the whole canvas. Two branches, or two people, cannot run independently.
3. **Reuse needs a second graph.** A subgraph is reusable only as a Module: built in
   another saved graph, published as a release, inserted with a pin. There is no way to
   define a graph once and call it from the same document.

The invocation cache already keys node outputs by operator, config and inputs, and
issue #190 adds per-node execution fingerprints to materialized outputs. Both point at
the same model; neither changes who owns a result.

## Decision

### A Project is the collaborative document; a Graph is a definition inside it

- A **Project** is the Workspace-owned object, the collaboration room and the unit of
  append-only checkpoints. It replaces Saved graph in those roles. Folders,
  archive, starring and last-opened state attach to Projects.
- A Project holds named **Graphs**. A Graph is a typed interface (inputs and outputs,
  declared by boundary nodes), nodes, edges and its own canvas layout. Any Graph can be
  run directly.
- A **call node** places a sibling Graph from the same Project as a node whose ports are
  that Graph's interface. The reference is live, not pinned: caller and callee are
  checkpointed together, so there is nothing to release.
- The call relation is acyclic. A command that would close a cycle is rejected.
  Deleting a Graph that still has callers is rejected; the way back from any accepted
  change is checkpoint restore. Changing a Graph's interface surfaces the broken
  connections at its call sites as connection issues, the same way an incompatible
  edge does today.

### Results are addressed by fingerprint, not by run

- Every node instance has a **fingerprint**: a digest over its operator id and
  version, implementation identity, config, secret revisions, artifact type bindings,
  ordered input plugs and, for each incoming connection, the upstream fingerprint,
  projection and conversion path. Origins contribute their artifact identity.
- The **result store** maps fingerprint → successful outputs. Entries are appended and
  never mutated. It subsumes the invocation cache and the materialized-output binding.
- A **node instance** is `(project, graph, call path, node id[, map index])`. Its
  state is derived, not stored: **fresh** when its current fingerprint has a result,
  **queued** or **running** when a computation for that fingerprint is in flight,
  **failed** when the last attempt at that fingerprint failed, otherwise **stale**. The
  only mutable per-instance record is a pointer to its last result and last failure,
  so a stale node keeps showing what it last produced.
- Failures are recorded on the instance, not in the result store. A rerun retries
  them.
- Two instances with the same fingerprint share one result, so two calls of the same
  Graph with the same inputs compute once.

### Implementation identity is scoped to the node

Deploying a build that did not change a node's code must not make that node stale.
A node's implementation identity is:

- its `operator_id@operator_version`,
- a digest of the source files its implementation module imports within its own family
  package (computed from the static import closure at catalog load),
- the locked versions of that family's third-party dependencies, and
- a deployment-wide **execution epoch**, bumped by hand to invalidate everything.

`grafy_core` is outside the closure. A core change that alters node outputs must bump
the affected artifact type's schema version or the execution epoch. Authors bump
`operator_version` for a semantic change the source digest cannot see, such as a
changed upstream service.

### Non-deterministic nodes refresh explicitly

A node whose cache policy is `NEVER` carries a **refresh generation** in its fingerprint.
It stays fresh until someone refreshes it. Refresh is a document command, so every
participant sees it and a checkpoint records it.

### A run is a demand for fresh targets

- A **Run** asks for a set of targets (node instances or Graph outputs) to become
  fresh. It schedules only the stale part of their upstream closure.
- Any number of Runs are active in a Project at once, started by any member with
  `execute_graph`. Computations are single-flight per fingerprint; a Run that needs a
  fingerprint already in flight waits on it.
- Cancelling a Run withdraws its demand. A computation is cancelled only when no active
  Run still needs it.
- Edits never lock the document. A computation finishes and stores its result under the
  fingerprint it started with; if the document has moved on, the instance reads as stale.
- Scheduling follows a per-computation lifecycle (`pending → ready → running →
  succeeded | failed | skipped | cancelled`) with a ready-set scheduler and one
  concurrency budget per Project.
- In-flight state lives in the single API owner. On restart, unfinished Runs are marked
  interrupted; stored results survive, so a rerun resumes from the fresh frontier.

### Run state is shared

The room broadcasts instance state changes and the list of active Runs with who started
each. Every participant derives the same canvas from the shared document and the
shared result store. There is no per-person view of results.

### No compatibility

No existing data, client or stored shape is kept. The rework does not preserve
anything for the sake of something that already exists:

- The Alembic history collapses into one baseline revision for the new schema. Its
  downgrade drops that schema.
- Stored-shape readers go: saved-document schema migrations, `plugin_release_pin`
  stripping, `kind: "plugin"` normalisation and `PluginImplementationIdentity`.
- Transport aliases go: the legacy head transport in `graph_contracts.py`, room protocol
  v1 head shapes, and the re-exported request and event models in route modules.
- Retired rows go: tables, enum members and capability strings kept only so old rows
  load (`schema.templates`, `DEPRECATED`/`WITHDRAWN`, retained Plugin lifecycle data,
  dropped PAT scopes).
- The API, `libs/client`, the MCP operations and the web client change together; no
  route keeps an old shape for an old caller.
- Vocabulary and capability names change freely to fit the new model.

The work lands on one integration branch and merges to `main` when the Project model
works end to end. Intermediate steps do not need to keep the current app running.

### Cross-project reuse waits

Published Modules and the Module library are removed with the clean break. Calling a
Graph from another Project returns later as a publication of a Project Graph, and gets
its own decision.

## Consequences

- "Run to here" works after reloads, collaborator runs and edits, because freshness is
  computed from the document rather than remembered by a browser.
- `RunExecutionManager`'s activity markers, revocation and cutover fences, queued
  recovery and saved-graph history shrink to Run bookkeeping over an append-only store.
- The fingerprint function and the source-closure digest become the correctness
  boundary for reuse. A missing input to the fingerprint serves a wrong result as fresh,
  so the fingerprint inputs need exhaustive tests and the execution epoch is the
  operational escape hatch.
- `CONTEXT.md` changes vocabulary: Project becomes the Workspace-owned object and Graph
  becomes a definition inside it, and capabilities are renamed to match.
- ADRs and design documents whose decisions the rework removes (Saved graph transport,
  the Module lifecycle, materialized-output bindings, retained Plugin data) are
  marked superseded rather than kept as history in force.
- The result store grows without bound. Garbage collection (results no instance
  pointer or checkpoint references) is required before production use and is not part
  of this decision.
- MAP items become instances keyed by map index, which opens per-item status, partial
  failure and item-wise pipelining. Each is a separate later decision.

## Considered and rejected

- **An external orchestrator (Dagster, Prefect).** Both expect developer-defined
  pipelines and would still leave compilation, typed edges, conversions, the cache
  and collaboration to Grafy. They replace only the queueing, at the cost of another
  service and per-run latency.
- **Keep run-centric execution and widen upstream pins (#190).** It makes reuse more
  precise but leaves results owned by runs, one active execution per graph, and reuse
  decided by what a client submits.
- **Fingerprint by whole-deployment build digest.** Every deploy would make every node
  stale.
- **Fingerprint by family digest.** A change to one GIS node would stale every GIS
  node. The import closure is no more expensive and follows what actually changed.
- **Cache failures in the result store.** Transient provider failures would become
  permanent until the document changed.
- **Migrate existing graphs into single-Graph Projects.** No data needs to survive,
  and a migration would keep the old document shape alive as a reader.
- **Pin in-project calls to a revision.** Caller and callee already share every
  checkpoint; a pin would reintroduce the release step this decision removes.
