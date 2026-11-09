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

Node secrets keep their existing encryption and authenticated-data versions.
The registry supplies declarations and config dependencies, so a historical
release does not need to exist to resolve a secret for a registered operator.
Workspace and saved-revision checks still bind each run to its authorized graph.

The release tables are gone: the one baseline revision never creates them, so no stored
release, installation, selection or revocation row exists to read, and the release
descriptor types are gone with them. The publication service, the Docker sandbox, the guest protocol and the egress broker are
gone, along with the `grafy plugin` and `network-policy` command groups that drove them.
Graph Modules retain their separate immutable publication model.
