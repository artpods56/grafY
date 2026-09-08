# Slice 2: Exact release pins and compiler proxy

- **Status:** Complete
- **Updated:** 2026-08-24
- **Depends on:** [Slice 1](01-source-freeze-and-convention.md)
- **Outcome:** Saved and submitted graph nodes identify one immutable Workspace
  Plugin release independently from operator version, and the compiler builds a
  ref-preserving Plugin proxy from persisted contracts

## Why this slice exists

`notes.table.summarize@1` identifies an operator contract, not the Plugin bytes
that implement it. Plugin release 4 and release 5 may both contain operator
version 1. A graph that stores only the operator identity can silently drift to
new code and can reuse cache entries created by another release.

The current compiler resolves only host registry nodes and Modules. Workspace
Plugin catalog rows cannot become executable until saved graphs, run requests,
repository lookups, compiler output, and cache identity agree on an exact
release.

## Scope

- Typed exact Plugin release pin on saved graph nodes and run requests.
- Persistence migration and API/web contract propagation.
- Exact release repository lookup.
- Compiler discrimination between host and Workspace Plugin nodes.
- `WorkspacePluginReleaseNode` proxy built from persisted contracts.
- Ref-preserving input and output behavior through existing node execution.
- Release-aware cache fingerprint shape with caching still forced off.
- Execution provenance sufficient to explain the resolved release.

## Non-goals

- Docker or OCI image execution.
- Artifact staging and bundle import.
- Enabling Workspace Plugin catalog nodes in Add Node.
- Automatic upgrade to a newer release.
- Plugin-owned conversions.

## Fixed decisions

Every Workspace Plugin node has two independent identities:

```text
operator:       notes.table.summarize@1
Plugin release: notes revision 4
```

The persisted graph representation uses an explicit structured release pin. It
must not infer release identity from the operator string. Workspace identity is
provided by the owning graph; the pin records the stable Plugin slug or id and
exact release revision.

Publishing release 5 does not modify a graph pinned to release 4. A future UI
upgrade command creates a graph revision containing the new pin.

The compiler-level adapter is the preferred low-churn seam:

```text
host registration      → ordinary Node
Workspace release pin  → WorkspacePluginReleaseNode → PluginInvoker port
```

`NodeExecutionService` retains ONCE/MAP behavior. `NodeRuntime` retains cache
orchestration and passes host-minted output refs through the existing
persister. The proxy must receive ref-preserving inputs rather than host-
materialized Plugin Python values.

## Expected ownership

- Saved graph domain models: `libs/core/src/grafy_core/domain/saved_graphs.py`
- Run request API models: `apps/api/src/grafy_api/v1/routes/executions/models.py`
- Release repository port: `libs/core/src/grafy_core/ports/plugin_releases.py`
- Persistence schema, ORM, repository, migration, and UoW
- Compiler: `apps/api/src/grafy_api/execution/compiler.py`
- Core node proxy and invocation port near the caller that owns the need
- Invocation cache fingerprint: `libs/core/src/grafy_core/runtime/`
- Web API contract and saved-graph serialization

## Implementation checklist

### Domain and persistence

- [x] Add a typed optional Workspace Plugin release pin to a saved graph node.
- [x] Add the same typed pin to submitted run-node requests.
- [x] Require the pin exactly for Workspace Plugin release nodes and reject it
      for host nodes and Modules.
- [x] Add persistence and migration support without rewriting unrelated graph
      nodes.
- [x] Add `get_by_revision(workspace_id, slug, revision)` or the equivalent
      exact lookup to the release repository port and adapter.
- [x] Ensure referenced releases cannot be hard-deleted while graphs or
      retained execution provenance depend on them.
- [x] Propagate the field through OpenAPI, generated web contracts, canvas
      serialization, and graph revision tests.

### Compiler

- [x] Resolve an explicit Plugin release pin before constructing an executable
      node.
- [x] Verify that the release belongs to the graph Workspace.
- [x] Verify that the pinned release declares the requested operator id and
      operator version.
- [x] Build the node contract from persisted release data without importing
      Plugin Python.
- [x] Introduce a discriminated compiled Workspace Plugin node or a focused
      proxy node without serializing live compiled graph objects.
- [x] Preserve projections, cardinality, required-input validation, ONCE, and
      MAP semantics through the existing compiler and execution pipeline.
- [x] Produce a clear compile error for missing, incompatible, or contract-
      mismatched releases. Withdrawal remains deferred until the append-only
      release lifecycle gains a real withdrawal state.

### Ref-preserving proxy

- [x] Define a caller-owned `PluginInvoker` port using typed request and result
      models.
- [x] Make `WorkspacePluginReleaseNode.run()` delegate through that port.
- [x] Configure proxy input ports so `InputMaterializer` preserves authorized
      `ArtifactRef` and `ArtifactRefSequence` containers.
- [x] Ensure the proxy returns only host-minted refs from the invoker.
- [x] Verify `OutputPersister` passes matching refs through without calling a
      host writer for Plugin-owned Python values.
- [x] Keep authoritative Plugin config and model validation in the later guest
      path; host validation uses only the serialized contract it can safely
      reconstruct.
- [x] Do not branch or duplicate MAP handling inside `NodeExecutionService`.

### Cache and provenance

- [x] Force the executable Workspace Plugin proxy registration to
      `NodeCachePolicy.NEVER`, even when the inspected declaration says
      `EXACT`.
- [x] Add exact release identity or source digest to the invocation fingerprint
      preimage.
- [x] Bump the fingerprint version and update compatibility tests.
- [x] Include the resolved release revision and immutable digests in execution
      diagnostics or retained provenance.
- [x] Ensure graph revision changes caused by a release upgrade cannot reuse
      incompatible materialized-output bindings.

## Verification checklist

- [x] A graph pinned to release 1 still resolves release 1 after release 2 is
      published.
- [x] Two releases containing the same operator version compile to distinct
      release identities.
- [x] A pin to another Workspace fails without disclosing that release.
- [x] A host node cannot smuggle a Plugin release pin.
- [x] A Workspace Plugin node without a release pin fails closed.
- [x] Plugin source is not imported during graph load, validation, or compile.
- [x] Ref-valued inputs reach the proxy unchanged for ONCE and MAP.
- [x] Host-minted output refs pass through the existing persister.
- [x] A declaration with `NodeCachePolicy.EXACT` still executes with caching
      disabled on the Workspace release path.
- [x] Fingerprints for release 1 and release 2 differ.
- [x] Saved-graph, API, compiler, persistence, and web contract tests pass.

## Exit criteria

- [x] Every Workspace Plugin node in a saved or submitted graph has one exact
      release pin.
- [x] Compiler resolution uses persisted release contracts only.
- [x] Host execution behavior is unchanged.
- [x] The proxy seam is proven ref-preserving through focused tests.
- [x] Workspace Plugin invocation caching is fail-closed.
- [x] Catalog nodes remain `runnable: false` until a real invoker exists.

## Agent handoff

- **Owner:** Slice 2 agents (opencode, Codex)
- **Branch or PR:** —
- **Implementation evidence:**
  - `SavedGraphPluginReleasePin`, `PluginReleasePinModel`, and the generated web
    contract carry the structured slug/revision pin through save and run
    transport; canvas hydration and serialization preserve it.
  - `PluginReleaseService.get_by_revision()` and the append-only SQL repository
    resolve exact Workspace-scoped revisions without exposing cross-Workspace
    releases.
  - `GraphCompiler` builds `WorkspacePluginReleaseNode` from the persisted
    catalog contract and a caller-owned `PluginInvoker`; host and Module nodes
    reject release pins.
  - The proxy preserves `ArtifactRef` containers through ordinary ONCE/MAP
    execution, forces cache policy `NEVER`, and records immutable release
    identity in cache fingerprints and retained execution diagnostics.
  - `0016_execution_node_diagnostics.py` adds metadata-only durable provenance;
    materialized-output compatibility now includes the exact release pin.
- **Verification evidence:**
  - Focused Python sweep: 99 passed, followed by a 93-test post-review sweep.
  - Focused basedpyright: 0 errors; Ruff: clean.
  - `npm --prefix apps/web run check:api` and `typecheck`: clean.
  - Focused Vitest sweep: 98 passed; post-fix saved-graph suite: 22 passed.
- **Open decisions or blockers:**
  - Release withdrawal is not modeled. Releases are append-only and cannot be
    deleted; add fail-closed compiler handling with the future withdrawal
    lifecycle instead of speculating a state now.
