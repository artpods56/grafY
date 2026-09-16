# ADR 0008: The interpret node picks its format through an artifact type binding

- **Status:** Accepted

## Context

Ingest writes `file.blob@1` for bytes whose extension the deployment does not
recognize. The blob has no format, so no port that wants a claimed `file.*` type
can take it. Issue #44 decided the way out is one visible node: `file.interpret@1`
takes the blob, confirms the bytes against one chosen format, and writes a new
artifact of that type.

The ticket describes that choice as a node `config` field holding one claimed
`file.*` type from the deployment extension table. The framework has no
config-driven port type: an `ArtifactTypeVariable` in a port contract is resolved
from `artifact_type_bindings` (see `resolve_node_contracts`), and node config is
validated per node without any reach into port contracts.

## Decision

`file.interpret@1` carries no config field. Its format is the artifact type bound
to the variable `format` on the node's output port.

One binding is the single source of truth: the compiler resolves the output port
to that exact type, the runtime hands the resolved map to the node, and the
persister refuses any output ref whose key differs from the resolved port type.
An unbound `file.interpret@1` fails contract resolution rather than running with
an implied format.

The compiler treats declared artifact type dependencies as bindable, because the
chosen formats (`file.jpeg@1`, `file.csv@1`) are declared as dependencies by the
builtin families rather than owned by them. Without that, the only bindable types
would be the ones a family itself registers as output contracts.

## Consequences

- The workbench picks the format from the node card: a variable port renders a
  type select (empty means "binds on connect"), so the choice is explicit and
  does not depend on a downstream consumer happening to declare that format as
  its primary accepted type. No new control, storage field, or migration is
  added.
- `file.interpret@1` reads `NodeExecutionContext.artifact_type_bindings` and the
  deployment's artifact type specs from `PluginRuntimeContext`.
- The node itself refuses `file.blob@1` and types that claim no extension, so a
  blob cannot be "interpreted" as a blob.
- A reviewer looking for a `format` config field on the node should read this ADR
  first: its absence is deliberate, not an oversight.
