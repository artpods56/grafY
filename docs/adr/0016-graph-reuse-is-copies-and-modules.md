# ADR 0016: Reusing a graph means copying it or calling it as a Module

- **Status:** Accepted (withdraws the Template aggregate and the Module
  deprecate/withdraw/import lifecycle)
- **Related:** ADR 0010 (Library folders), `docs/design/modules-conceptual-model.md`,
  `docs/design/graph-browser-organization.md`, `CONTEXT.md` (Module)

Grafy had three ways to reuse a graph. **Duplicate** copied a saved graph into a new
one. **Use Template** copied a frozen copy of a graph into a new one from a separate
per-workspace Template Library. **Insert Module call** ran a frozen contract of a graph
as a node. Two of those three produced the same thing — a new graph you own — and the
middle one existed only to hold the copies someone wanted to start from again.

Templates were a second durable aggregate with their own identity, state machine,
capability, routes, repository, ORM mapping, library page, publish dialog and search.
Their rules were a copy of the graph-copy rules minus the interesting parts: a Template
had no contract, no releases, no pins and could not be called, so a Template could never
answer "what does this take and produce" — the only question that distinguishes reusable
graphs from merely saved ones. Users met both entry points next to each other under
**Library** and had to know that one was executable and one was not.

Modules carried the mirror-image problem. A published release was already a freeze: a
checkpointed source graph plus a copied document, addressed by `(module_id, revision)`,
with every call site pinned to one revision. On top of that, a Module could be
deprecated (still insertable behind a browser confirmation), withdrawn (hidden from Add
node and library browse) and imported into another Workspace (copy-by-value, which
 minted a brand-new Module with new identity in the destination). Three states and two
transitions bought nothing that the freeze did not already buy: nothing in the system
ever saw a newer release unless the user deliberately repointed the pin, so there was no
"gone stale" condition to warn anybody about.

## Decision

**Reusing a graph means either copying it or calling it.**

- **Copying** is Duplicate: a new Saved graph in a chosen Workspace, by value. It was
  already complete for this use, and it is now the only way to get a graph into another
  Workspace.
- **Calling** is a Module: publish a release from a graph with Module Input/Output
  boundaries, then insert that exact release as a node.

**Templates are gone.** The routes, the domain aggregate, its ports and service, its
repository and ORM mapping, its three capabilities, its library page, its publish
dialog and its client functions are deleted. Nothing remains that a Template could have
done that Duplicate and Modules do not.

**Publishing a release is the only Module lifecycle transition.** Publication has one
reachable state: `published`. Publishing again adds another immutable release; nothing
takes one away. The library lists a Module and its releases, and Add node inserts one.

**A stored Module in a retired state keeps working, and stays hidden.**
`DEPRECATED` and `WITHDRAWN` remain members of `ModulePublicationState` and remain
readable from the `modules.publication_state` column, so rows already in a database load
rather than crash. Retired modules are absent from library browse and Add node —
`list_library` selects `published` only. A pinned call resolves its exact release
whatever that stored state says, because execution resolves a Module by
`(module_id, revision)` and never consults `publication_state`.

**No migration, no rewrite, no shim.** `schema.templates` keeps its definition so that
metadata against the retained migration head stays comparable, but nothing maps or
selects from it. No `ALTER TABLE`, `UPDATE`, `DELETE` or data-conversion revision is
added; the columns keep the values they hold.

## Consequences

- **A module's source graph is the editable artifact and the only place to fix it.**
  Withdrawing a release was one way to say "stop using this"; the way now is to publish
  a better release and let each owner repoint their pin. Cost: a genuinely broken
  published release stays listed until its workspace is deleted, and readers cannot tell
  from the library that it is known-bad. That signal was worth less than the state
  machine, because the release was never mutated under anybody and the person deciding
  whether to move a pin is the person who noticed.
- **Cross-workspace Module reuse is a copy, and the copy is a different graph.** Duplicating
  an imported source graph into another Workspace yields a saved graph with
  Module boundaries that its new Workspace can publish in its own name. What is lost is
  identity continuity: the copy has a new graph id, so nothing links the two Modules and
  an upstream fix does not propagate. This is the same trade Duplicate already made for
  ordinary graphs, and Import into workspace was the only place Grafy promised
  cross-Workspace identity for a graph.
- **A personal access token can hold a stored scope that is no longer a capability.**
  `create_template`, `manage_template_library` and `manage_module_library` were PAT-allowable.
  `WorkspaceCapabilityTupleType.process_result_value` now drops stored scope strings that
  are no longer in `WorkspaceCapability` instead of raising, so an old token loads with
  the permissions it still has. The strict check stays in `PersonalAccessToken.__post_init__`
  for every token minted from here on, which is where an unknown scope is a caller bug.
  Dropping is silent by design: the alternative was a token that fails to authenticate
  because the product stopped recognising one of its words.
- **Retiring a capability now has a known shape.** Enumerate it out of `WorkspaceCapability`,
  its role grants and `PAT_ALLOWED_CAPABILITIES`; let the column type drop it for stored
  rows; do not touch the data. The reverse direction was already free.
- **Templates and Modules no longer compete for the same reader.** The Library dialog
  holds Modules and says so. The graph **Library** menu keeps Duplicate, which is the
  entry point that used to be ambiguous.
- **Folder routes outlive their only caller.** `GET /v1/workspaces/{workspace_id}/graph-folders`
  is unchanged: it belongs to graph organisation, and Templates were its final consumer in
  the web client. The web helper for it is deleted with them; the backend contract stays
  as the app's own.
- **Retiring the Template Library dialog's folder picker leaves no orphans.** Folder rows
  were reachable only through that picker. They stay in the database — no cascade and no
  rewrite — and `GET /graph-folders` still lists them. The write-side routes
  (`POST/PATCH/DELETE /graph-folders/{folder_id}`) stay too, so an empty folder someone
  made two years ago is still addressable and still removable through the API. Nothing in
  the app creates one now; if folder organisation returns to the graph browser, the rows
  are already there.

## Considered and rejected

- **Keep Templates as read-only** (list and use, no new captures). Rejected: it keeps the
  aggregate, its routes, its capabilities and its library page alive to serve an
  alternative to Duplicate that no longer has a name. The half-state is the expensive one.
- **Fold Templates into a "kind" column on saved graphs.** Rejected: the Template rules
  that made it a separate thing — sanitised capture, no runtime capabilities, no
  secrets, one-level folder — are copy-time rules, not graph rules. A kind column would
  make saved graphs carry two mutually exclusive rule sets behind one identity, and
  still would not make a Template callable.
- **Delete the `templates` table with a migration.** Rejected on the repository's
  deliberate-retirement policy: schema changes land in the normal Alembic revision
  sequence when they land at all, and an untested migration against an unknown production
  count is a worse risk than an unreferenced table. `schema.templates` also stays so that
  `test_migrations.py`, which compares metadata against the retained migration head,
  keeps comparing like with like.
- **Rewrite stored `publication_state` to `published`.** Rejected: it would promote
  withdrawn Modules back into Add node, which is the one change a retired state must not
  imply. Leaving the value alone keeps history and keeps them hidden.
- **Hard-remove `DEPRECATED` and `WITHDRAWN` from the enum.** Rejected: any
  `StringEnumType`/`Enum` column change is a schema change, and keeping two unreachable
  values costs nothing while removing them breaks every stored retired row at load time.
- **Keep Deprecate as a warning-only flag with no state.** Rejected: the flag *was* the
  state, and the warning was a browser `confirm()` on insert — a prompt that fires at the
  worst moment to describe the least urgent condition.
- **Keep Import into workspace as the cross-Workspace door for Modules only.** Rejected:
  it was the sole asymmetry in graph movement, and the copy it produced silently broke
  the identity continuity that made Modules better than duplicating. If cross-Workspace
  module identity is ever a real requirement, it wants its own decision — a published,
  readable-elsewhere release — not a copy that pretends to be the same thing.
