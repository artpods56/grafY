# ADR 0023: MCP is a PAT-only adapter over the REST API

- **Status:** Accepted
- **Implements:** grafY issue #262
- **Amends:** ADR 0003 ("Mount Streamable HTTP MCP under the API authority"),
  ADR 0011 (the staged-upload bound)
- **Related:** ADR 0014 (validated command batches), ADR 0020 (Projects),
  `CONTEXT.md` (`PersonalAccessToken`, Capability, Programmatic graph authoring)

## Context

External coding and research agents need to discover nodes, author Graphs, run them and
read results. ADR 0003 already fixed the MCP transport (stateless Streamable HTTP at
`/mcp`, bearer PAT, per-request authorization) but no MCP code shipped. The REST routes
are where authorization actually happens: each route computes role ∩ PAT scope ∩
capability, reads the Project under the Workspace in its path, applies a command batch
against the live head, publishes the accepted batch to the room and re-derives instance
state. Several of those steps live in the route, not in the service below it.

Agents also uploaded large georeferenced scans, and the per-file limit was a 64 MiB
constant that was both the default and the maximum.

## Decision

**Transport.** A FastMCP server (`fastmcp` 4.x, over the `mcp` 2.x protocol types)
serves stateless Streamable HTTP with JSON responses at FastAPI `/mcp` (public
`/api/mcp`). Its HTTP app, and the session manager inside it, is built and run once per
API lifespan. There is no stdio server and no second port. FastMCP needs Starlette 1, so
the API no longer pins `starlette<1`; that pin only ever served Prefect, which is gone.
The gate in front of it reads at most 4 MiB of body and answers `413` beyond that.

**Admission is PAT-only.** A request needs exactly one `Authorization: Bearer` personal
access token, resolved by the same `AuthService` the REST routes use. A request that also
carries the browser session cookie is refused: MCP has no CSRF token, so ambient cookie
authority must never reach it. Failures answer `401` with `WWW-Authenticate: Bearer` and
write a metadata-only audit event. DNS-rebinding protection is off because it guards
ambient credentials, which this endpoint refuses.

**Tools act through the REST API, in process.** Every tool calls this API's own routes
through `grafy_client` over an ASGI transport, with the caller's bearer header. The route
that serves the call authorizes it again and does its post-commit work, so a tool can do
exactly what the token could do over HTTP and nothing else. A missing capability is the
route's `403`, relayed as a tool error. The Workspace comes from the token, never from a
tool argument. `tests/unit/architecture/test_import_boundaries.py` forbids the adapter
from importing routes, services, runs, persistence or storage.

**The tool set is what a person can do in the Workbench**, over the routes a PAT
reaches: file, star, archive, copy, export and import Projects; restore checkpoints;
edit a canvas; run and read results; keep results and folders in the Library; manage
node secrets; talk to canvas Agents. Routes a PAT cannot reach (identity, members,
personal credentials) have no tool, and a scope a token lacks is the route's `403`.

**Authoring is validated twice.** `author_graph` builds the Graph with `GraphBuilder`
against the live node catalog (operator identity, config schema, port shapes, artifact
types, conversions, required inputs, cycles), then writes it as one `add_graph` or
`replace_document` batch and checkpoints it. The server validates that batch again.

**A canvas edit is the Workbench's own commands.** The canvas tools (`move_items`,
`connect`, `configure_node`, `remove_items`, `add_card`, `arrange_graph`, ...) edit a
copy of one Graph's live document and submit the difference that
`grafy_client.graph_commands` derives: `move_nodes` for a drag, `add_edge` for a wire,
`update_node_configuration` per changed field, each carrying the value it expects to
replace. Peers in the room see the same events a collaborator's gestures produce, and a
stale edit is refused rather than overwriting someone else's change. A whole-document
`replace_document` is reserved for `author_graph`. Wiring is checked first by
`GraphBuilder.from_document`, which loads the live Graph (keeping nodes the catalog
cannot describe, layouts, annotations and Agents untouched) so `connect` and `place`
validate against the catalog exactly as they do for a new Graph.
Origins carry the exact `ArtifactRef`, content hash included; the tool resolves a
missing hash from the Library. `create_artifact` writes a new Workspace artifact
through REST with `edit_project` and returns the exact reference. To place that
artifact on the canvas, pass its hash and versioned type to `author_graph` as a
standalone card. The graph spec can also bind the card to node inputs and other
cards, or define a card that follows a node output.

**Workspace listing accepts a PAT.** `GET /v1/workspaces` answers a token with its one
Workspace and the capabilities it holds there (scopes ∩ role). Identity, credential and
`/me` routes stay cookie-only.

**Upload limit.** `GRAFY_STAGED_UPLOAD_MAX_BYTES` defaults to 64 MiB and may be raised
to a 2 GiB ceiling (`STAGED_UPLOAD_HARD_MAX_BYTES`), which is also the bound the reserve
contract publishes. Reserve, receive and complete enforce the configured value. The
target lifetime bounds when a PUT starts, not when its last byte arrives, and the local
content route refuses an expired target before reading the body. The gateway's
`client_max_body_size` is a second ceiling an operator raises with the setting.

## Consequences

- MCP, the SDK and the web client share one authorization, tenancy and publication path;
  a new REST rule applies to MCP without MCP code changing.
- Each tool call costs one extra PAT resolution per inner request. That is the
  per-request re-authorization ADR 0003 asks for.
- MCP is single-Workspace per token. An agent that needs two Workspaces holds two tokens.
- Tool arguments are bounded at 4 MiB per request; files larger than 2 MiB go through the
  staged upload API, which `grafy_client.UploadClient.upload` streams from a path.
- The adapter reaches only this API process, so `upload_file` serves the deployments
  whose API receives upload bytes. Where the API hands out signed object-storage URLs,
  no in-process client can PUT them and the tool refuses with that instruction; the
  bytes go to the bucket from a client outside the process.

## Alternatives considered

**Call application services from the tools.** Rejected: it duplicates capability
intersection and post-commit publication that live in the routes, and a missed step
leaves a room or instance state silently stale.

**Expose every REST operation as a tool automatically** (FastMCP's OpenAPI import).
Rejected: agents need task-shaped tools with validated authoring, not ninety
endpoints; one tool per Workbench gesture is the unit, and most gestures are command
batches, not routes.

**Submit every canvas edit as `replace_document`.** Rejected: peers would see the
Graph swapped wholesale and any concurrent edit anywhere in it would conflict.

**Keep the official SDK's `MCPServer`.** Rejected once the tool set grew: FastMCP adds
tool annotations (read-only, destructive, idempotent), tags, resource templates and
prompts the agent clients use, with the same wire protocol.

**Accept the browser session on `/mcp`.** Rejected: it would let a cross-site page drive
MCP with the user's cookie.
