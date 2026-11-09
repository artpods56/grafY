# Authentication and workspace tenancy

- **Status:** Accepted; Phase 0–6 implemented; Phase 7 operator release gate open
- **Date:** 2026-08-06
- **Audience:** Engineers changing identity, persistence, API, Workbench,
  collaboration, execution, MCP, or deployment
- **Document type:** Technical design explanation and reference
- **Related:** [Authenticated workspace ADR](../adr/0003-authenticate-users-and-scope-collaboration-to-workspaces.md),
  [server-authoritative collaboration ADR](../adr/0002-server-authoritative-workbench-collaboration.md),
  [realtime collaboration design](workbench-realtime-collaboration.md), and
  [product vocabulary](../../CONTEXT.md)

## Summary

This design adds application identity, workspace tenancy, and continuing
authorization to Grafy. The implementation through Phase 6 matches this
contract; Phase 7 still needs live SSH/OIDC and backup/restore operator
rehearsal before calling the refactor release-ready.

The design makes these decisions:

1. Grafy uses `User`, `Workspace`, and `WorkspaceMembership`. A shared
   workspace is the product's team or organization boundary; there is no second
   team aggregate and no per-graph ACL in the first delivery.
2. FastAPI is the OpenID Connect relying party. The browser receives an opaque,
   revocable server session rather than an identity-provider token.
3. Every graph belongs to exactly one workspace. Independently addressed graph,
   execution, artifact, upload, cache, and collaboration data carries that
   workspace scope from persistence through runtime execution.
4. Workspace roles provide default capabilities, but the server authorizes the
   specific operation using current membership when it is handled.
6. Authentication or room admission is not continuing authority. Revocation
   and role changes affect ordinary requests immediately and terminate
   long-lived transports.
7. Sharing an existing graph copies one exact synchronized collaborative head
   into another workspace. It does not move or copy secrets, runtime history,
   artifacts, uploads, or cache capabilities.

## Goals

- Let users keep private graphs and collaborate in shared workspaces.
- Prevent UUIDs, storage keys, command ids, and cached results from crossing a
  workspace boundary.
- Make logout, user disablement, token revocation, membership removal, and role
  change take effect without waiting for a deployment restart.
- Preserve the collaboration design's durable head, immutable checkpoint,
  shared execution, and one-API-owner decisions.

## Non-goals

- Local passwords, password reset, or application-owned MFA.
- Public registration, invitation email, SAML, SCIM, or identity-provider group
  synchronization.
- Per-graph guests, public links, or exceptions to workspace membership.
- Moving a graph and its dependent state between workspaces.
- Sharing the browser-local Artifact Viewer document.
- Multiple API owners, replicas, or a distributed graph-room broker.
- Giving an unrelated Streamlit application access to Grafy sessions,
  cookies, tokens, or workspace data.
- Workspace deletion in the first delivery. Graph deletion remains an
  owner-only workflow; bulk workspace destruction needs a separate lifecycle.

## Vocabulary and identity boundaries

### User

An internal application identity with a stable UUID, active or disabled state,
and bounded profile fields. Email and display name are presentation data and do
not determine authorization or automatically link identities.

### OIDC identity

The exact `(issuer, subject)` pair asserted by one configured OpenID Connect
provider and mapped to one User. The pair is unique. A changed email does not
create or merge an account.

### Workspace

The tenant, sharing boundary, and owner of graphs and workspace resources.

- A `personal` workspace has one owner and accepts no additional members.
- A `shared` workspace has one or more members and always retains an owner.

There is no local workspace kind or bootstrap workspace. A new OIDC identity
creates a personal workspace. Shared workspaces are created by authenticated
users, or by a deployment-configured email-domain grant that adds membership
after the OIDC user exists. The grant uses the email asserted by the configured
issuer; it does not require the IdP `email_verified` claim.

“Team” and “organization” are product-language synonyms for a shared
workspace. They do not introduce additional aggregates.

The graph browser may present a personal Workspace as **My graphs** and a shared
Workspace as a Team save/share location. That presentation does not create a
new owner or weaken the Workspace boundary.

### Workspace membership

The retained relation between one User and one Workspace, with a Viewer,
Editor, or Owner role, active or revoked state, and a monotonically changing
authorization version. Removal sets `revoked_at` instead of deleting attribution
history; re-adding the User reactivates the same relation and advances its
version. The version helps invalidate long-lived observations, but it is not a
bearer capability.

### Workspace access

A short-lived application value derived from the current active user,
membership, role, and requested workspace. It supplies effective capabilities
for one operation. It is loaded again for every durable mutation.

### Actor context

Audit attribution containing the User id and a non-secret credential public
identifier. It does not contain the session secret, PAT, mutable role, or a
permanent authorization decision. Background work receives immutable actor and
workspace ids, never a browser request or bearer credential.

### OIDC login transaction

A single-use, short-lived server record for state, nonce, PKCE verifier, return
path, expiry, and consumption. Its verifier and other sensitive values are
encrypted or irreversibly digested according to how callback validation uses
them. It is not a user session.

### Auth session

The browser credential created after a valid OIDC callback. The browser holds a
random opaque cookie; the database stores only a lookup id, secret digest,
session-bound CSRF state, timestamps, and revocation state.

### Personal access token

A random opaque bearer credential created by a User for one Workspace with
explicit scopes and expiry. The plaintext appears once at creation. The
database stores only a public prefix, secret digest, ownership, scopes, expiry,
last use, and revocation state.

## Browser authentication

### Login flow

1. The browser requests the OIDC login-start endpoint with an application-local
   return path.
2. FastAPI creates a short-lived OIDC login transaction, generates state,
   nonce, and PKCE S256 material, stores only the required digests/encrypted
   verifier, sets a host-only `Secure`, `HttpOnly`, `SameSite=Lax` transaction
   cookie scoped to `/api/v1/auth/oidc`, and redirects to the configured provider.
3. The callback resolves the transaction and validates exact issuer, signature,
   allowed algorithm, audience and authorized party where applicable, time
   claims, state, nonce, PKCE verifier, expiry, and single use.
4. FastAPI maps exact `(issuer, subject)` to OidcIdentity. For a new identity it
   creates User, personal Workspace, and Owner membership atomically.
5. FastAPI creates a fresh opaque AuthSession and redirects only to the
   validated application-local return path.
6. Provider tokens are discarded after identity mapping unless a later
   accepted feature genuinely needs a provider API.

The application never merges users by email and never accepts a callback
issuer, return URL, or public origin from untrusted forwarded headers.

### Session cookie and CSRF

Production session cookies are host-only, `Secure`, `HttpOnly`,
`SameSite=Lax`, `Path=/`, and have no `Domain`. Sessions have finite idle and
absolute expiry and rotate after authentication. Logout and administrative
revocation invalidate the database row.

Unsafe cookie-authenticated HTTP requests require both:

- an exact allowed `Origin`; and
- a session-bound CSRF token in `X-CSRF-Token`.

CORS is not CSRF protection. Authentication endpoints and validation errors do
not echo codes, verifiers, session values, or submitted secrets.

### Public endpoints

Only process health, OIDC login start, and the exact callback are public.
Health does not reveal users, workspaces, provider metadata, bootstrap state,
or schema details. Every resource endpoint fails closed when authentication or
authorization state cannot be loaded.

Login start and callback failures are rate limited, outstanding transactions
per browser are bounded, and expired or consumed transactions are cleaned up on
a fixed schedule. Abuse controls do not log submitted protocol values or claims.

Development and acceptance tests use a configured OIDC provider or protocol-
level test issuer. There is no trusted-user header, anonymous workspace, or
authentication-disable mode.

## Personal access tokens

A User creates a PAT only in a Workspace they currently belong to. Requested
scopes must be a subset of both the allowed PAT scope set and the User's current
role capabilities. The returned token has a recognizable public prefix and at
least 256 random secret bits.

For every request, the server verifies:

1. token digest, expiry, and revocation;
2. active User;
3. current WorkspaceMembership;
4. intersection of PAT scopes and current role capabilities; and
5. operation-specific permission.

Bearer requests do not use cookies or CSRF. A request presenting both browser
cookie and bearer authentication is rejected rather than silently selecting an
identity.

Membership removal revokes that user's PATs for the affected workspace in the
same transaction. A role change that leaves an existing PAT's scopes outside the
member's remaining capabilities likewise revokes those PATs before commit. User
disablement revokes all of that user's sessions and PATs in one transaction.
Revoked PATs are not revived when membership is later restored.

## HTTP authorization order and errors

Workspace API paths use stable Workspace UUIDs. Browser routes may retain
`/workspaces/{workspace_slug}/...`, but the authenticated web shell resolves the
slug to a permitted UUID before calling the API.

1. authenticate the credential allowed for that surface;
2. reject ambiguous authentication;
3. load active User;
4. resolve the route Workspace or token Workspace and current membership;
5. require the operation capability;
6. load the resource with workspace and resource ids in the same query; and
7. invoke the typed application workflow with actor and workspace context.

Responses use:

- `401` for missing, invalid, expired, or revoked authentication;
- `404` when the caller is not a member or the resource belongs to another
  workspace, so existence is not disclosed;
- `403` when a member lacks an operation capability;
- `404` for an absent resource inside an authorized workspace;
- `409` for revision, room epoch, collaboration sequence, or idempotency
  conflicts; and
- `422` for structurally invalid bounded input.

Errors preserve safe operation and resource context without including
credentials, secret-bearing input, provider responses, or foreign resource
existence.

## Command journal, idempotency, audit, and logs

These stores have distinct sensitivity and retention contracts:

| Store | Purpose | Allowed content |
| --- | --- | --- |
| Operational command journal | Short reconnect replay and operational recovery | Authorized semantic payload; protected like the complete graph document |
| Security audit record | Attribute security-relevant outcomes | Explicit actor kind; stable actor and non-secret credential reference for authenticated events; workspace/graph/resource ids, operation kind, safe target ids, outcome, and safe error code. Unauthenticated events never copy submitted identity. |
| Structured logs and traces | Operate the service | Bounded metadata only; never journal payload or user-entered configuration |

A plain digest of low-entropy configuration can be a guessing oracle. Persisted
command and request digests use a server-keyed HMAC. HMAC key material is
sensitive state and is supplied through protected deployment configuration.

Presence payloads are neither journaled nor copied into audit records. Display
names and colors are presentation; stable User ids provide attribution.
Historical UI may render a removed user as “former member” without exposing an
email or requiring current membership.

The first delivery exposes no user-facing audit-query API. Audit storage is an
operator security boundary with explicit retention and backup handling; it is
not a substitute for the workspace-visible graph history.

## API and gateway shape

Internal FastAPI routes use `/v1`. The browser sees one HTTPS origin through a
loopback-bound gateway:

| Public path | Destination |
| --- | --- |
| `/` and static assets | Next.js web |
| `/api/v1/...` | FastAPI `/v1/...` after stripping `/api` |

The gateway preserves WebSocket Upgrade, disables response buffering for SSE,
and sets timeouts longer than transport heartbeats. API, database, and storage
services are not published directly.

The public OIDC callback is
`https://<configured-host>:<port>/api/v1/auth/oidc/callback`. The complete URL
must exactly match provider registration, while its origin must equal
`GRAFY_PUBLIC_ORIGIN`. The browser must trust the TLS certificate for that
hostname even when SSH forwards the gateway port.

## Persistence model

### Identity tables

- `users`
- `oidc_identities`
- `oidc_login_transactions`
- `workspaces`
- `workspace_memberships`
- `auth_sessions`
- `personal_access_tokens`
- `security_audit_events`

Important constraints include unique `(issuer, subject)`, unique workspace
slug, membership uniqueness, role and workspace-kind choices, token/session
lookup and expiry indexes, one-use login state, one personal owner,
retained membership revocation/version state, protection against removing the
last shared-workspace owner, and bounded audit-event indexes for
actor, workspace, operation, and retention.

### Operational requirements

SQLite batch rebuilds need working disk space for old and replacement tables,
indexes, WAL or rollback journal, and a verified backup. Migration is a
maintenance-window operation. Back up database, data root, uploads, local
object storage, encryption and HMAC keys, and migration metadata; restore the
backup into scratch storage before changing production data.

Do not run a pre-tenancy binary against the migrated database. A full rollback
restores database and data-root backup together. Collaboration rollback first
drains commands, checkpoints every head, verifies head and checkpoint sequence
equality, and closes rooms.

## Sensitive state and observability

Sensitive state includes OIDC code and provider tokens, state, nonce, PKCE
verifier, session and CSRF secrets, PATs, node-secret values, encryption/HMAC
keys, one-time URLs, and any serializable object carrying them.

Sensitive values are excluded from ordinary model dumps, repr, validation
errors, exception details, logs, traces, command audit, presence, execution
announcements, and MCP errors. A sentinel test proves the exclusion across all
boundaries.

## Failure behavior

| Failure | Required behavior |
| --- | --- |
| OIDC state, nonce, issuer, audience, signature, PKCE, time, or replay failure | Deny login, consume or invalidate unsafe transaction state, and return a bounded error without provider payload |
| Provider metadata/JWK temporarily unavailable | Use only an unexpired validated cache; otherwise fail closed |
| Session expired or revoked | Return `401`; stop protected retries and require a new login |
| Role changed | Close room and SSE as applicable; revoke workspace PATs whose scopes exceed the member's remaining capabilities in the same membership transaction; require a fresh browser authorization snapshot |
| Workspace membership removed | Revoke that user's workspace-bound PATs in the same transaction, conceal resources, close browser transports, remove presence, and purge client caches |
| Foreign resource UUID or command id | Behave as not found without revealing existence or idempotency outcome |
| Command races revocation | Whichever transaction commits first determines whether the command is accepted or rejected |
| Running execution starter removed | Continue the already accepted workspace execution; former member loses observation/cancel access |
| Graph copied across workspace | Sanitize or reject foreign references; never preserve source runtime capability |

## Open decisions before implementation

- Exact provider issuer, client registration, allowed algorithms, and callback
  registration for the SSH-forwarded HTTPS hostname.
- Idle and absolute AuthSession lifetimes, PAT maximum lifetime, and cleanup
  schedules.
- OIDC login transaction, command-journal payload, and security-audit event
  retention.
- Whether owner-added users must have completed first login or whether a later
  invitation workflow may reserve an identity safely.
