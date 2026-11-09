# ADR 0006: Authenticate Plugin publication with scoped tokens

- **Status:** Superseded by ADR 0017 (there is no publication to authenticate, and the
  Platform Access Token that carried its scopes is removed). Narrowed earlier by ADR 0015.
- **Amended by:** ADR 0015 (publication is platform-only; the Workspace-User
  authority and its `publish_plugin` capability are removed)

## Context

Plugin publication previously accepted Workspace ids and actor references as
CLI arguments. Those values described who the caller claimed to be; they did
not authenticate the caller. Global operations also reused an untyped platform
actor string, while Workspace operations depended on a User UUID supplied next
to it.

Publication needed authorities that described the caller rather than
authenticated it: a Workspace User publishing into their own Workspace, and a
deployment operator or CI job publishing, promoting, or revoking global Plugins
without being a Workspace User.

## Decision

Plugin publication authenticates with a `PlatformAccessToken` and nothing else.
Its principal reference is the operation actor, and its scopes are limited to
`plugin.publish_global`, `plugin.promote_global`, and
`plugin.revoke_global`. The Workspace-User authority described below was part of
this decision until ADR 0015 removed Workspace Plugins: a personal access token
no longer grants any Plugin publication capability.

Interactive credentials were stored in the operating-system keychain after
`grafy auth login`, and non-interactive callers provided a protected file path in
`GRAFY_TOKEN_FILE`. That operator CLI did not accept a raw token argument or
token-value environment variable. Raw bearer values were parsed and hashed in its
credential adapter; domain and persistence objects contained only digests and
safe references. Operator commands lived in a `grafy admin` command group rather
than a separate `grafy-admin` executable.

That CLI has since been deleted, so the keychain and `GRAFY_TOKEN_FILE` mechanics
above describe how the decision was carried, not a live surface. What stands is the
credential shape: a bearer token the server only ever sees hashed, and domain and
persistence objects that hold digests and safe references rather than raw values.

## Consequences

- A personal access token cannot publish, promote, or revoke a Plugin; the
  platform credential that owns those scopes must reach the publisher.
- Platform operators can rotate and independently scope publishing, promotion,
  and revocation credentials.
- The CLI no longer accepts `--actor` or `--workspace`; callers must
  authenticate with the credential that owns those values.
- Keychain access is deployment-specific, based on a sanitized database
  identity. CI files remain the caller's responsibility to protect.
