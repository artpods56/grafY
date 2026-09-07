# Slice 1: Source freeze and project convention

- **Status:** Complete
- **Updated:** 2026-08-23
- **Depends on:** Existing catalog-only Plugin release foundation
- **Outcome:** Publication tests and inspects one immutable source snapshot,
  uses a fixed Plugin import convention, and stores generated release metadata
  outside the source archive

## Why this slice exists

The current publisher lock-checks, tests, and inspects the mutable working copy
before creating the archive. The bytes ultimately stored are therefore not
provably the bytes that passed verification. Plugin tests also run as ordinary
host subprocesses.

The source archive currently includes generated release metadata such as the
runtime-image digest. Once image construction exists, that creates a circular
dependency: the image digest depends on source bytes while the source digest
would depend on the image digest.

This slice establishes a clean publication boundary before executable images
or graph pins depend on it.

## Scope

- Fixed project layout and `from grafy_plugin import PLUGIN` convention.
- Immutable snapshot before any Plugin test or import.
- Deterministic source archive and source digest.
- Separate inspected contract and release descriptor.
- Clean verification environment for the frozen snapshot.
- Rejection of path dependencies that escape the Plugin tree.
- Implicit `(workspace, slug)` identity on first successful publish.
- Documentation reconciliation for the decisions already accepted here.

## Non-goals

- Building or running the final OCI image.
- Exact graph release pins.
- Artifact bundle execution.
- Public `grafy plugin register` or dirty working-copy status.
- Additional runtime profiles or capability grants.

## Fixed decisions

The canonical authoring shape is:

```text
plugins/
  notes/
    pyproject.toml
    uv.lock
    src/
      grafy_plugin/
        __init__.py   # exports PLUGIN
        nodes.py
        artifacts.py
    tests/
```

Every Plugin is installed and inspected in its own environment, so the common
`grafy_plugin` import package does not create a collision.

The immutable objects form this dependency chain:

```text
working copy
  → source archive + source digest
  → inspected contract + contract digest
  → later OCI image + image digest
  → release descriptor referencing those independent digests
```

`runtime_profile` is a deployment-owned default until a second real profile
exists. Requested capabilities come from the inspected declaration; approved
capabilities remain deployment policy. The first runtime supports only an empty
approved capability set.

## Expected ownership

- Source verification and freezing: `apps/api/src/grafy_api/plugins/publication/source.py`
- CLI boundary: `apps/api/src/grafy_api/cli.py`
- Release application workflow:
  `libs/core/src/grafy_core/application/plugin_releases.py`
- Release and contract models:
  `libs/core/src/grafy_core/domain/plugin_releases.py`
- Inspector: `libs/core/src/grafy_core/plugin_inspector.py`
- Fixture: `examples/plugin-notes/`
- Documentation: `CONTEXT.md` and `docs/design/plugin-unification.md`

Follow actual ownership discovered in the current tree; do not create a generic
publication helper package for one workflow.

## Implementation checklist

### Project convention

- [x] Remove the `[tool.grafy.plugin]` module/object loader contract.
- [x] Require the installed project to export `grafy_plugin.PLUGIN`.
- [x] Update the inspector to use the fixed import without caller-supplied
      module or object names.
- [x] Move code-owned capability requests into the inspected Plugin
      declaration.
- [x] Resolve the runtime profile from deployment policy rather than Plugin
      source metadata.
- [x] Validate that the inspected Plugin slug matches the publish target and
      established Workspace Plugin identity.
- [x] Update `examples/plugin-notes` to the fixed package convention.

### Snapshot and source digest

- [x] Resolve the requested directory canonically beneath an allowlisted
      Plugin root.
- [x] Define the exact included paths and default exclusions.
- [x] Reject symlinks, devices, traversal, excessive files, and escaping
      project paths before snapshotting.
- [x] Copy accepted regular files into a private staging directory.
- [x] Create the deterministic source archive before running Plugin code.
- [x] Compute the source digest only from canonical source archive bytes.
- [x] Ensure tests and inspection consume an unpacked copy of that exact
      archive, not the mutable working directory.
- [x] Ensure Plugin tests cannot mutate the archived source object.

### Dependency verification

- [x] Run `uv lock --check` against the frozen snapshot.
- [x] Reject `[tool.uv.sources]` path dependencies that resolve outside the
      snapshot.
- [x] Decide and document how the deployment supplies a versioned Grafy Plugin
      SDK or `grafy-core` wheel.
- [x] Remove the escaping `../../libs/core` dependency from
      `examples/plugin-notes`.
- [x] Separate network-enabled locked dependency acquisition from
      network-disabled tests and inspection.
- [x] Execute tests and inspection in a constrained clean environment rather
      than as ambient host subprocesses.

### Release objects and persistence

- [x] Remove generated release and image metadata from the source archive.
- [x] Persist the inspected catalog contract separately with its own digest.
- [x] Define a release descriptor that references source, contract, profile,
      protocol, capability, and later image digests.
- [x] Keep `runtime_image_digest` absent until the image-building slice fills
      it; do not fabricate a source-owned value.
- [x] Preserve idempotent publication for identical source, contract, and
      policy inputs.
- [x] Preserve monotonic Plugin release revision allocation for changed input.
- [x] Clean orphaned staging objects after failed publication or leave them in
      a known garbage-collectable namespace.

### Documentation reconciliation

- [x] Update `CONTEXT.md` so first publish may establish Plugin identity and
      Register is not mandatory before a real pre-publish workflow exists.
- [x] Update `CONTEXT.md` to distinguish operator version from Plugin release
      revision.
- [x] Update `docs/design/plugin-unification.md` to link this implementation
      plan and remove the source/image digest circularity.
- [x] Update the design explanation to describe the fixed `grafy_plugin.PLUGIN`
      convention.
- [x] Leave `docs/design/plugin-development.md` explicitly scoped to legacy
      in-process entry-point Plugins.

## Verification checklist

- [x] Publishing a project whose tests modify the original working copy still
      stores and inspects the pre-test snapshot.
- [x] Changing working-copy bytes after snapshot creation cannot change the
      source digest or inspected contract.
- [x] Reordering filesystem enumeration produces the same archive digest.
- [x] Changing generated release metadata does not change the source digest.
- [x] A symlink or path dependency escaping the Plugin root is rejected with
      contextual path information.
- [x] Plugin tests and inspection cannot read a sentinel secret outside their
      constrained environment.
- [x] Identical publication returns the existing release.
- [x] Changed source creates the next release revision.
- [x] The API process never imports `grafy_plugin` from the working copy.
- [x] Focused unit, persistence, publication, catalog, and migration tests pass.

## Exit criteria

- [x] One immutable snapshot is the source of tests, inspection, and later
      image construction.
- [x] Source and generated release metadata have independent digests.
- [x] The fixed import convention is the only Workspace Plugin loader path.
- [x] The example Plugin is freezeable without monorepo-relative dependencies.
- [x] Existing vocabulary and design docs no longer contradict this slice.
- [x] Catalog behavior remains unchanged and release nodes remain
      `runnable: false`.

## Agent handoff

- **Owner:** Slice 1 agent (opencode)
- **Branch or PR:** — (work done directly in the working tree; no commits made)
- **Implementation evidence:**
  - `apps/api/src/grafy_api/plugins/publication/source.py`: repaired corrupted class
    definition; allowlisted-root canonical resolution, pre-snapshot rejection
    of symlinks/special files/traversal/oversized trees with contextual
    errors, private staging, deterministic archive built before any Plugin
    code, unpacked-archive verification, `uv lock --check` + locked sync
    (network-enabled) vs constrained sanitized environment for Plugin tests
    and inspection (`-I` subprocess, private HOME/TMPDIR), escaping
    `[tool.uv.sources]` rejection, empty `py.typed` markers and vendored
    `wheels/*.whl` accepted, public `constrained_environment` helper.
  - `libs/core/src/grafy_core/plugin_inspector.py`: fixed
    `grafy_plugin.PLUGIN` import convention, no caller-supplied names;
    capability requests come from the inspected declaration.
  - `libs/core/src/grafy_core/domain/plugin_releases.py`: release descriptor
    with independent source/contract/capability/protocol/profile digests,
    nullable `runtime_image_digest`, contract-digest self-validation.
  - `libs/core/src/grafy_core/application/plugin_releases.py`: content-
    addressed `plugin-releases/` storage namespace (GC-able orphans),
    idempotent publish, monotonic revisions, metadata-mismatch rejection.
  - `apps/api/src/grafy_api/cli.py`: publish target slug must match the
    inspected declaration and established identity.
  - Persistence/migrations were already complete from prior foundation work:
    `infra/db/migrations/versions/0014_plugin_releases.py`,
    `0015_plugin_release_descriptor.py` (contract/protocol/profile digest
    columns); no additional migration needed.
  - `examples/plugin-notes`: fixed `src/grafy_plugin/__init__.py` exporting
    `PLUGIN`; removed duplicate declaration; self-contained `pyproject.toml`
    (vendored `grafy-core` wheel under `wheels/`, no monorepo path deps) plus
    committed `uv.lock` and own pytest config; README documents SDK wheel
    supply via vendored wheels or deployment `UV_FIND_LINKS` wheelhouse.
  - Docs reconciled: `CONTEXT.md` (first-publish identity, operator version
    vs release revision), `docs/design/plugin-unification.md` (plan link,
    one-way digest chain, snapshot-first publication, fixed import
    convention, optional Register, SDK wheel policy),
    `docs/design/plugin-development.md` (explicitly scoped to legacy
    in-process entry-point plugins).
- **Verification evidence:**
  - `uv run pytest tests/unit/api/test_plugin_publishing.py
    tests/unit/core/test_plugin_releases.py tests/unit/plugins tests/unit/persistence/test_plugin_release_persistence.py
    tests/integration/catalog -q` → 19 passed (rewritten publishing suite
    covers working-copy mutation during tests, archive stability under
    enumeration reorder, generated-metadata independence, symlink/path-dep/
    traversal rejection with contextual paths, sentinel-secret isolation,
    slug mismatch, idempotency, revision bump, catalog overlay with
    `runnable: false`).
  - Full focused sweep `uv run pytest tests/unit/api tests/unit/core
    tests/unit/persistence -q` → 434 passed.
  - `uv run ruff check` on all changed paths → clean.
  - `uv run basedpyright` on changed files → 0 errors.
- **Open decisions or blockers:** —
