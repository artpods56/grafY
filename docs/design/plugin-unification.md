# Application-owned node families

[ADR 0017](../adr/0017-plugins-are-application-code-in-process.md) replaces the
published Plugin runtime with one static, in-process registry. The same family
tuple supplies development, test and production. Installing a package alone does
not expose it in the catalog; the application composition must register it.

A family owns its node declarations, artifact contracts and resolver/writer
factories. It depends inward on `grafy_core`, without importing API routes or
concrete storage adapters. HTTP routes remain application-owned. The API composes
all registered artifact contracts before building upload extension claims,
execution materializers and artifact readers. Families that consume another
family's type carry the same exact contract as a dependency.

All registered operators have `BuiltinImplementationIdentity(build_digest)`.
Invocation-cache keys include that identity. Materialized outputs are reusable
only when their artifact provenance names the current build. Historical artifacts
and execution records remain readable after deployment, while old outputs must
be recomputed. Bindings with no producer identity, including empty sequences,
are conservatively treated as stale.

Saved graph checkpoints keep schema version 7. Reads normalize `kind: plugin` to
`builtin` and discard `plugin_release_pin`; recovered run requests also discard
`plugin_release`. The stored checkpoint is never rewritten. New documents and
requests contain no release pins. Collaboration rejects the retired release
update command. Missing operators report the node id and operator identity;
Python operators report that Python execution was retired. The four former
Python text operators stay unavailable. SQL is absent from the application tuple
until its execution safety review is complete.

Node secrets keep their existing encryption and authenticated-data versions.
The registry supplies declarations and config dependencies, so a historical
release does not need to exist to resolve a secret for a registered operator.
Workspace and saved-revision checks still bind each run to its authorized graph.

The first usable milestone retains release tables, publication helpers and
historical descriptor types. They are outside catalog selection and graph
execution. There is no destructive migration in this milestone. Remaining
publication commands do not change which operators the API executes. Graph
Modules retain their separate immutable publication model.
