# ADR 0012: The Python node runs on a System Plugin release

- **Status:** Accepted
- **Implements:** grafY issue #138
- **Replaces:** the draft ADR 0012 on the abandoned `t3code/user-defined-python-block`
  branch, which ran user code through its own Docker runner
- **Related:** ADR 0005 (releases and installations), ADR 0007 (builtin families),
  ADR 0008 (a port's type is an artifact type binding)

A Python node holds user code in its configuration: an optional `Params` class and
one `transform` function with one data input and one output. Presets are ready
filled Python nodes listed under familiar titles. Four one-line text operators
leave the node library in their favour. Three questions had to be settled before
any of that could be built.

## 1. User code reaches the existing Plugin sandbox as a System Plugin release

The Python runner is the System Plugin `external.python` in `plugins/python`. It
is published, installed and selected like every other System Plugin, and its
nodes run on `DockerPluginRuntime` through `ArtifactBundlePluginInvoker`. The
sandbox lifecycle is unchanged: hardening, labels, orphan recovery, capacity and the
reuse of one container per release within a run scope all apply as they are. A
`map` edge therefore runs every item of a split → map(replace) → join chain in
the same warm container.

The release has two nodes:

- `python.transform@1` runs the applied code from node config. Its ports are
  fixed (`input`, `output`) and generic over the artifact type variables `input`
  and `output`. It declares `NodeCachePolicy.EXACT`. The invocation cache key
  already covers operator, configuration (code, its hash, shapes, params),
  bindings, node identity, map index, input digests and the exact release, so a
  transform is expected to be deterministic.
- `python.inspect@1` is the Apply analysis. It runs the code in the sandbox,
  resolves the `transform` annotations against the artifact types the release
  declares, checks the `Params` field types and returns the derived contract and
  line-anchored diagnostics as JSON text. It is hidden from the node library.

Apply runs on the API host as an application service. It parses the code with
`ast` (never executing it), then invokes `python.inspect@1` of the selected
release through a dedicated invoker whose unit of work is in memory, inside a
sandbox scope of its own that it closes afterwards. Nothing the analysis writes
reaches the artifact store.

Option (b), a release-agnostic sandbox core, was not needed. Option (a) asked for generic additions, none specific to Python:

- a node registration flag that keeps a node out of the library (`listed`),
  serialized on the node contract;
- a port shape a node instance chooses through its configuration (decision 2),
  serialized on the port contract;
- admission of generic Plugin ports using their concrete invocation bindings,
  and resolution of their shapes at the bundle boundary;
- host validation of every inline JSON Plugin output against the exact payload
  schema of its artifact contract before the output is imported. Builtins have
  always validated through their writer models. Isolated outputs were only
  checked for bundle shape until now.

Default values are omitted from the contract digest, so earlier releases keep
their digest. Non-default visibility and shape fields remain covered by it.

**Port types are the release's declared types.** The Python runner declares
`scalar.text@1`, `scalar.integer@1`, `text.markdown@1` and `table.data@1` as
artifact type dependencies. Scalars unwrap to `str` and `int` as builtins receive
them. Structured types become Pydantic classes generated from their payload
schema and named after their catalog title (`Markdown`, `Table`). `list[T]` is a
`many` port. Adding a type to the runner is a new release. `text.markdown@1`
moved into `grafy_core.artifact_contracts` so the Text family and the runner
carry the same contract.

**Deployment consequence.** Presets appear only where an operator has published
and promoted `external.python`, see `docs/how-to-publish-plugins.md`. The four
text operators are hidden regardless and stay registered, so saved graphs that use
them keep opening and running.

## 2. A node chooses a port's shape through a configuration field

`InPort` and `OutPort` take `shape_field`, the name of a configuration field that
holds `one` or `many`. `resolve_node_contracts(node, bindings, config)` resolves
those fields alongside artifact type variables and returns concrete shapes. The
compiler validates `map` invocation and edge shapes against the resolved
contracts, and the guest resolves the same contract from the same configuration.
An absent field means the shape the port declares.

A shape-field input is annotated `ArtifactRef | ArtifactRefSequence`, so the node
receives references and does its own materialization.

The port's type stays an artifact type binding (ADR 0008): the bindings `input`
and `output` are the single source of truth for what the ports carry. Shape has
no such mechanism, and adding one beside the bindings would have meant a new
saved-graph field, collaboration commands, run request field, invocation envelope
field and client builder support. Configuration already flows through all of
those, through the invocation cache key and through materialization
invalidation. Four operator variants per shape combination were rejected as the
issue asked.

Apply therefore writes the contract in two places, as one user action: the
configuration (code, its SHA-256, both shapes, the params JSON Schema, params, and
the preset identity) and the two artifact type bindings. The guest re-derives the
contract from the code at run time and refuses to run when the code hash, the
bindings or the shapes disagree with it.

## 3. The params form lives in the Python node's own card body

The Workbench draws ordinary node configuration from the operator's fixed config
schema. A Python node's params schema is per node and stored in its
configuration, so the Python card draws it itself, as Schema Builder draws its
fields, with the existing schema form (`GenericBody`, given the node’s params schema
and values). `Params` fields are limited to what that form edits: `str`, `int`,
`float`, `bool`, `Literal[...]`, `list[str]` and their optional forms. The card
shows ports, the params form, then a collapsed Code section. The editor is
CodeMirror with Python highlighting. Errors appear on Apply only. There is no
live completion, hover or language server.

## Presets

A preset is data in `libs/workbench/src/grafy_workbench/presets/`: id,
version, title, description, input and output type and shape, params schema
and code. The catalog lists each preset as an entry of the selected
`python.transform@1` release. Inserting one creates a Python node already in its
applied state, carrying `preset_id` and `preset_version`. A preset is copied, not
linked. A test re-derives every preset's contract from its code so the stored
contract cannot drift.

A preset is not a **Template**: a Template copies a whole graph, a preset fills
one node.

## Exact caching after Map

The invocation cache deliberately includes a sequence container's identity. Map
used to rebuild its aggregate output with a random sequence ID, so a downstream
Join missed even when every mapped item hit. Map now derives the aggregate ID
from the source sequence, node/module identity, output port and ordered item
artifact IDs. Repeating the same mapped results preserves the container identity;
changing an item changes it. This keeps EXACT caching's container semantics.
