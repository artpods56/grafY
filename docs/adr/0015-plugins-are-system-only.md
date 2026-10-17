# ADR 0015: Plugins are System-only

- **Status:** Accepted
- **Implements:** removal of Workspace Plugins and coding-agent Plugin authoring
- **Supersedes:** ADR 0004 (already superseded by ADR 0005) and, for its
  Workspace half, ADR 0005 (releases and installations), ADR 0006 (publication
  tokens), ADR 0013 (specialized file operators as published Plugins)
- **Related:** ADR 0007 (builtin families are application code), ADR 0012 (the
  Python node runs on a System Plugin release)

## Context

ADR 0005 made one immutable, scope-neutral release installable either globally
or into a single Workspace, and the coding-agent authoring workflow put that
second path in front of every Workspace member: scaffold a working copy under a
Workspace-namespaced root, reserve the slug, review a capability diff, publish
into the caller's own catalog.

Neither half earned its keep. Nothing in the deployment published a Workspace
Plugin: every Plugin in `plugins/system-plugins.toml` is System-owned, and every
Plugin node in a real graph carries a System pin. A Workspace could publish a
slug whose node or file-format identity belonged to a System Plugin, so the
catalog needed cross-scope collision refusal, per-Workspace selection state,
per-Workspace revocation, a Workspace publication capability, and a reservation
fence — all to protect a surface nobody used. The remaining authority question
(coding agents publishing executable code into a shared deployment) is now a
deployment question with a clear answer: publication is a platform operation.

## Decision

Plugins exist in one namespace: the deployment-owned System namespace.

**One namespace, same durable shapes.** `PluginReleaseNamespace`,
`PluginInstallation`, `PluginReleaseSelection` and `PluginReleaseRevocation`
reject any scope other than System, and an installation always names a platform
actor. The stored columns, the wire shape of a release pin
(`{scope, slug, revision}`) and `PluginReleaseScope.WORKSPACE` stay in place,
because graph documents, graph revisions and collaboration heads already store
pins that way. Replacing the vocabulary would be a data migration for no
behaviour.

**Stored Workspace pins refuse, they do not crash.** A pin whose scope is
`workspace` resolves to no release: preflight and compilation report
`unsupported_plugin_release_scope` and tell the user to re-insert the node from
the catalog. Cross-workspace graph copy refuses such a pin on the way in.
Nothing reads or rewrites historical rows.

**Publication authority is platform-only.** `WorkspaceCapability.PUBLISH_PLUGIN`
is gone from roles, PAT scopes and the CLI's personal-token path. `grafy plugin
publish` requires a platform access token with `publish_global`, a `--slug` that
appears in `plugins/system-plugins.toml`, and `--sandbox-image`; it stages a
release without activating it, and `grafy plugin promote` remains the separate
`promote_global` step. Revocation keeps `revoke_global`. `grafy plugin check`
stays a read-only local verification.

**Authoring is deleted, not deprecated.** The CLI's `scaffold`, `reserve`,
`review`, `publish-reviewed` and `release-reservation` commands,
`PluginAuthoringService`, the two-step publication workflow and its reservation
fence are removed, along with `GRAFY_PLUGIN_AUTHORING_ROOT` and
`GRAFY_PLUGIN_SDK_PROJECT`. The working copy a publisher reads is a checked-in
`plugins/<family>` project (see ADR 0007 for what belongs in the application
instead). `examples/` goes with it; the freeze tests keep a fixture project under
`tests/fixtures/plugin-notes` because the source-freeze path still needs a real,
publishable Plugin to freeze.

**What a new Plugin takes instead.** A node family that is broadly reusable,
deterministic and dependency-light is a builtin family in the application
(ADR 0007). Anything needing a pinned dependency set, an image, or egress is a
System Plugin: add the project under `plugins/`, list it in
`plugins/system-plugins.toml`, and publish it through the deployment pipeline in
`docs/how-to-publish-plugins.md`.

## Consequences

- The node catalog has one Plugin source. `CatalogSnapshot` no longer merges a
  Workspace catalog with the System one, and `list_catalog()` takes no
  Workspace. Removing the merge also removes the cross-scope slug collision rule:
  two System catalogs cannot claim the same identity because the inventory
  assigns each prefix to exactly one slug.
- Extension-claim collisions are now checked at promotion, the only moment a
  System catalog becomes insertable. A refused promotion still retains the
  release, so the operator fixes the claim and promotes again rather than
  republishing.
- Two revocation lookup paths collapse into `get_system_revocation`, and Python
  node and Docker runtime admission read that one path.
- The guest invocation envelope keeps its serialized `scope` and `workspace_id`
  fields, because the protocol versions independently of the deployment, but only
  a System release validates. Network profile assignments select a slug and
  revision: a manifest that still names `scope` or `workspace_id` fails to load
  with the reason, rather than configuring a rule that can never match.
- The web UI loses the "Plugin publishing" personal-access-token purpose. The
  remaining purposes are graph automation and module publishing; Modules are
  unchanged and still Workspace-owned.
- Deployments that stored Workspace Plugin rows keep them. The rows are inert:
  the repository reads only the System namespace, the PAT scope decorator drops
  a stored `publish_plugin` when it decodes a token, and pins naming that scope
  are reported as unsupported. A later cleanup can drop the columns once no
  stored pin names them; that is not part of this decision.
- `docs/plans/workspace-plugins/` describes the removed workflow as delivered
  history. ADR 0015 governs the vocabulary from here.
