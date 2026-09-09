# ADR 0003: Authenticate users and scope collaboration to workspaces

- **Status:** Accepted; amended 2026-08-26 to remove the legacy local workspace;
  amended 2026-09-01 to authenticate workspace HTTP automation with PATs
- **Date:** 2026-08-06
- **Scope:** Identity, workspace tenancy, browser sessions, collaboration authorization, HTTP automation, and MCP access
- **Designs:** [Authentication and workspace tenancy design](../design/authentication-and-workspace-tenancy.md), [realtime Workbench collaboration rework](../design/workbench-realtime-collaboration.md)
- **Plan:** [Authentication and workspace refactor](../plans/authentication-workspace-refactor.md)

## Context

Grafy currently treats the `local` workspace slug as a route label. The API
does not authenticate a caller, saved graphs are globally addressable, and the
MCP adapter reaches the same unauthenticated HTTP operations. Binding the web,
API, Prefect, and MCP ports to loopback reduces network exposure but does not
establish application identity or determine which saved graphs a caller may
read, edit, execute, or share.

[ADR 0002](0002-server-authoritative-workbench-collaboration.md) proposes server-authoritative graph rooms, durable collaboration
commands, shared execution discovery, and authenticated actor presentation.
A WebSocket admission check alone cannot provide continuing edit authority:
browser sessions expire, workspace membership changes, and a caller may lose a
capability while a room remains connected. The collaboration journal,
checkpoint workflow, execution history, node secrets, artifacts, uploads, and
invocation cache also need the same tenancy boundary as the saved graph.

Users need both a private place for their own graphs and a shared place where a
known group can collaborate. Sharing one graph through an independent access
list would leave its revisions, executions, artifacts, uploads, secrets, and
cached outputs with ambiguous ownership. Moving a graph between security
boundaries would create the same ambiguity and could silently transfer secret
or runtime capabilities.

Browser and automation callers use different credentials, but they must not
acquire different authorization semantics. The browser needs an interactive
login and revocable session. SDK, CLI, and MCP clients need a non-browser
credential and the live workspace-aware graph contracts. Both must resolve an
authenticated user and call the same application-owned authorization and
mutation workflows.

## Decision

### Use users, workspaces, and memberships

Grafy has an internal `User` identity with a stable application id. An
external OpenID Connect identity is uniquely identified by `(issuer, subject)`
and maps to one user. Email address and display name are profile data; neither
is an authorization key or sufficient evidence for automatically linking two
identities.

A `Workspace` is the tenant, sharing boundary, and durable owner of graphs and
their derived resources. A workspace is one of:

- **personal**, created for one user and not shareable through membership
  invitations; or
- **shared**, created for collaboration by multiple users.

Every graph belongs to exactly one workspace. Saved revisions, collaborative
heads and journals, node secrets, executions, materializations, artifacts,
uploads, storage objects, and invocation-cache entries inherit that workspace.
Repositories require the workspace identity explicitly rather than relying on
an ambient current workspace.

A `WorkspaceMembership` relates one user to one workspace with one role:

- `viewer` may discover and read graphs, checkpoints, presence, executions, and
  accessible artifacts;
- `editor` includes viewer capabilities and may create, copy, edit, checkpoint,
  execute, and cancel graphs; and
- `owner` includes editor capabilities and may manage members, mutate node
  secrets, delete graphs, and rename a shared workspace. Workspace deletion is
  outside this decision.

A shared workspace always retains at least one owner. A personal workspace has
its user as its owner and does not accept additional memberships. New OIDC
identities always receive a personal workspace.

A deployment may also list email domains that receive membership in a named
shared workspace on login (`GRAFY_OIDC_DOMAIN_WORKSPACES`). Email is still not
an identity-linking key: the grant runs after the `(issuer, subject)` user
exists and uses the email asserted by that configured issuer. An existing
membership, including a revoked one, is left alone. The first active member
becomes owner; later members become editors. There is no special local
workspace or first-owner bootstrap path.

The removal migration deletes the deterministic legacy workspace only when it
is empty and unowned. When it has an active owner, the migration preserves its
tenant data and renames it into an ordinary shared workspace. An unowned legacy
workspace containing tenant data blocks the upgrade so the previous release
can assign its owner without data loss.

Roles are translated into operation-specific capabilities by the application.
They are not copied into a long-lived session or treated as a permanent claim.
Every durable graph command, checkpoint, execution transition, secret mutation,
replacement, copy, and deletion reloads the current membership inside the same
unit of work as its state change. A missing graph and a graph inaccessible in
the requested workspace produce the same not-found response.

### Share by workspace, without per-graph access lists

All members of a workspace receive the graph capabilities granted by their
workspace role. Grafy does not add per-graph grants, guest links, or nested
teams in this decision.

Cross-workspace sharing creates a copy rather than changing the source graph's
workspace. The caller needs read access to the source and editor access to the
target. The request identifies the expected source room epoch and collaboration
sequence so the workflow copies one exact synchronized head, not merely the
latest checkpoint. A copy receives a new graph identity, room epoch, sequence 1,
and revision 1 and copies only the authoring document. It does not copy node
secrets, execution history, materialized outputs, invocation-cache entries,
artifacts, or other runtime capabilities. References that are not valid in the
target workspace are rejected or left explicitly unresolved. The source graph
and its history remain unchanged, and later edits do not synchronize the two
copies.

Moving a graph across workspaces is not supported. A future product that needs
selective or linked cross-workspace sharing requires another access model and a
separate decision.

### Use OpenID Connect and opaque server-side browser sessions

FastAPI acts as the OpenID Connect relying party. Browser login uses the
Authorization Code flow with PKCE, state, and nonce. The server validates the
issuer, audience, signature, time claims, state, nonce, and code verifier before
mapping the external identity. Provider access, refresh, and ID tokens do not
enter browser JavaScript and are not persisted when login is their only use.

After login, the browser receives a random opaque session cookie. The database
stores only the session-token hash and server-owned session state, including
user identity, creation and activity times, idle and absolute expiry, CSRF
state, and revocation state. A production cookie is host-only, `Secure`,
`HttpOnly`, `SameSite=Lax`, and scoped to `/`. Authentication rotates the
session id; logout and administrator revocation invalidate it server-side.

Unsafe cookie-authenticated HTTP requests require a session-bound CSRF token
and an exact allowed `Origin`. The web application, API, SSE endpoints, and
WebSocket endpoint share one HTTPS origin. OIDC callback URLs and production
cookies therefore require a valid TLS deployment even when users reach the
service through an SSH tunnel.

The same-origin gateway exposes public `/api/v1/...` paths by stripping `/api`
and forwarding to FastAPI `/v1/...`. The registered browser callback is exactly
`<GRAFY_PUBLIC_ORIGIN>/api/v1/auth/oidc/callback`; it is not derived from
untrusted forwarded headers.

The application does not implement local passwords, password recovery, or MFA.
Those responsibilities remain with the configured identity provider.

### Authorize every application surface by workspace

An authenticated request resolves a server-owned actor containing the internal
user id, credential audit reference, and requested workspace id. Application
services use that identity to load current membership and authorize the
operation. A browser or MCP caller cannot submit another actor id or role.

Workspace scoping applies to REST reads and mutations, SSE execution
observation, collaboration rooms, graph-module discovery, upload resolution,
artifact delivery, storage access, invocation-cache lookup, and node-secret
resolution. Guessing a UUID or storage key must not cross that boundary.

Security-relevant operations record the actor, workspace, action, resource
identity, outcome, and safe error code. Cookies, bearer credentials, OIDC codes,
PKCE verifiers, provider tokens, secret values, semantic command or
configuration values, artifact payloads, presigned URLs, and one-time URLs do
not enter ordinary logs, exceptions, traces, or audit records.

The operational collaboration journal is a different store: it may retain the
authorized semantic payload required for replay and recovery and is protected
like the complete graph document. Long-lived idempotency tombstones retain only
workspace/graph/actor metadata, outcome, and a versioned server-keyed HMAC; they
never retain command values.

### Authenticate graph rooms and recheck continuing authority

The browser opens a workspace- and graph-scoped WebSocket using its same-origin
session cookie. Before accepting the connection, the API validates the cookie,
user status, session expiry, exact WebSocket `Origin`, current workspace
membership, and graph visibility. Authentication material is never placed in a
WebSocket URL or client message.

One collaboration connection has a random connection id distinct from both the
user id and browser-session id. The server derives bounded participant name and
presentation metadata from the authenticated user. Clients may not claim user
identity, membership role, display style, or another session identity.

Room admission grants no continuing edit authority. Each durable message is
authorized for its operation when handled, and its membership check participates
in the mutation transaction. Presence publishing requires continuing view
access but may use a short-lived access snapshot because it is bounded,
ephemeral, and rate limited. Membership mutation and session revocation notify
the in-process room hub after commit; the hub closes affected connections.
Heartbeat revalidation closes connections after an expiry or an out-of-band
change that did not reach the hub.

Execution SSE streams apply the same admission and periodic revalidation. A
viewer may observe a shared execution, while only an editor or owner may cancel
it. Secret configure and remove operations remain protected HTTP workflows for
owners. They never carry secret values over the collaboration protocol and may
publish only bounded configured or unconfigured metadata after commit.

### Use Workspace PATs for non-browser HTTP automation

Workspace-qualified REST routes accept exactly one of the opaque browser
session cookie or a Workspace-bound PAT in an `Authorization: Bearer` header.
Cookie-authenticated unsafe requests retain Origin and CSRF checks. PAT requests
do not use CSRF because they do not rely on ambient browser credentials. A
request carrying both credential kinds is rejected instead of choosing one.

The PAT supplies the authenticated User and its sole Workspace; neither value
is caller input. Its effective authority is the intersection of its scopes and
the User's current membership capabilities. That Workspace binding is retained
through secondary authorization inside cross-Workspace workflows, so entering
through a route for one Workspace cannot turn the User's ambient membership in
another Workspace into token authority. The `manage_secrets` scope is explicit
and required for programmatic node-secret configuration.

Browser identity, credential-management, and `/me` routes remain cookie-only.
They never accept a PAT that could issue or manage its own credential. Bearer
failures and authorized operations use the PAT's safe audit reference; the raw
token and secret request values never enter errors, logs, or audit rows.

### Mount Streamable HTTP MCP under the API authority

The FastMCP Streamable HTTP application is mounted at `/mcp` under the same
FastAPI deployment and public authority as the REST, SSE, and WebSocket
surfaces. First delivery uses **stateless** Streamable HTTP: every request is
authenticated and authorized independently, and no process-global or
transport-session caller token is retained. It is not published on a separate
unauthenticated port and does not use an ambient service credential that
bypasses user authorization. Grafy does not retain a stdio MCP server or
entry point; HTTP is the MCP transport.

An automation user creates a random opaque access token scoped to one workspace
and a bounded set of capabilities. The database stores only its hash, public
lookup prefix, user and workspace identities, expiry, last-used metadata, and
revocation state. SDK, CLI, and MCP clients present it only as an
`Authorization: Bearer` header. Bearer-authenticated calls do not use browser
cookies or CSRF tokens.

Every MCP request resolves the token, active user, current workspace membership,
and required capability. Membership removal and role loss that leave a token's
scopes outside the member's remaining capabilities revoke the affected
workspace-bound PATs in the same transaction as the membership mutation; user
deactivation revokes all of that user's PATs in the same transaction. Because
MCP authorization is re-resolved per request, the next request fails closed
when the credential or capability is no longer effective.
MCP graph reads and writes use workspace-scoped live-head and collaboration
application contracts, so an MCP mutation cannot bypass an uncheckpointed
collaborative head or silently replace connected browser state. A committed MCP
mutation is published to the graph room like any other external mutation.

### Make revocation application-owned and fail closed

Logout, session or access-token revocation, user deactivation, membership
removal, and role changes take effect in the application database. Membership
removal, role loss affecting PAT scopes, and user deactivation revoke the
affected workspace-bound PATs in the same unit of work as the membership or
user mutation. Ordinary requests reload the affected state. Long-lived
WebSocket and SSE connections are actively closed by the single-process
connection owners and periodically revalidated as a fallback. Stateless MCP
relies on per-request credential resolution plus those transactional PAT
revocations rather than a retained MCP authorization session.

OIDC-provider logout does not by itself prove immediate local revocation unless
the provider supplies a verified back-channel logout event. Local sessions
therefore retain finite idle and absolute lifetimes. Failure to load identity,
membership, session, token, provider metadata, or signing keys denies access
rather than falling back to an anonymous or global workspace.

## Consequences

### Positive

- Browser, REST, SSE, WebSocket, and MCP callers share one application identity
  and authorization model.
- Workspaces give graph sharing, runtime data, node secrets, and collaboration a
  single durable tenancy boundary.
- Server-side opaque sessions and MCP tokens can be revoked immediately without
  exposing provider tokens to browser JavaScript or storing bearer credentials
  in the database.
- Collaboration presence and audit records carry trusted application users
  rather than client-supplied identities.
- Workspace copies avoid silently transferring secrets, execution provenance,
  caches, or storage capabilities.
- Direct API forwarding through SSH does not bypass object authorization.

### Negative

- Existing graph, execution, artifact, upload, secret, cache, and storage paths
  require a workspace migration rather than only an authentication middleware.
- Durable operations perform membership checks, and long-lived transports need
  revocation indexes, close behavior, and periodic revalidation.
- OIDC and secure cookies require a stable HTTPS callback origin even for the
  initial SSH-tunnel deployment.
- Users cannot share only one graph with an outsider; they must use a shared
  workspace or create an independent copy.
- Copies intentionally diverge and may require the target user to replace
  unavailable uploads, artifacts, or node secrets.
- The API owns browser sessions and opaque MCP-token lifecycle, including
  expiry, cleanup, audit, and recovery procedures.

## Alternatives considered

### Store local email and password credentials

Rejected because Grafy would own password hashing, verification, recovery,
rate limiting, MFA, and credential-breach response instead of delegating those
responsibilities to the configured identity provider.

### Protect only the reverse proxy with OIDC

Rejected because a perimeter session does not give the application a durable
user and workspace membership for object authorization. Direct loopback or SSH
access could bypass the proxy, and MCP and WebSocket authorization would remain
separate special cases.

### Expose provider access tokens to the browser or use stateless application JWTs

Rejected because browser-held provider tokens increase extraction and refresh
complexity, while stateless application tokens make immediate local session and
membership revocation harder. The application needs only an opaque session
identifier in the browser.

### Add per-graph access control lists

Rejected for the first shared product because derived revisions, executions,
artifacts, uploads, secrets, modules, and caches would need parallel grant and
revocation semantics. Workspace roles cover the current sharing requirement
with one inspectable boundary.

### Move graphs between workspaces

Rejected because changing tenancy in place could transfer node-secret use,
execution history, materializations, caches, storage objects, and links with
unclear or unsafe semantics. Copying authoring state makes the boundary crossing
explicit and leaves the source intact.

### Run MCP on a separate port or trust one global MCP credential

Rejected because it would create a second authority or a privileged bypass
around workspace authorization. Mounting Streamable HTTP under FastAPI keeps
authentication, revocation, audit, and collaboration coordination consistent.

## Follow-up

This ADR is Accepted. Remaining follow-up:

1. Add user, workspace, membership, browser session, MCP token, and authenticated
   actor vocabulary to `CONTEXT.md` when the accepted vocabulary pass is
   scheduled.
2. Continue implementing and verifying the migration phases in the linked
   authentication and workspace plan, including finishing Phase 2 route cutover
   and the later collaboration/MCP phases.
3. Register and test the exact HTTPS OIDC callback for the SSH-tunnel deployment
   before enabling browser login in a shared environment.
4. Update deployment documentation for the shared HTTPS authority, `/mcp`,
   WebSocket upgrade forwarding, cookie settings, revocation behavior, backups,
   and the existing single-API-owner constraint.
5. Add cross-workspace isolation, role matrix, CSRF, OIDC replay, session/token
   revocation, WebSocket/SSE revocation, MCP per-request fail-closed coverage,
   copy sanitization, and sentinel-secret acceptance tests.
6. Record a separate ADR before adding public links, guests, nested teams,
   identity-provider group synchronization, linked cross-workspace graphs, or
   multiple API owners.
