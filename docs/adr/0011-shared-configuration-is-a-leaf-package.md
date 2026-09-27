# ADR 0011: Shared configuration is a leaf package

- **Status:** Accepted
- **Implements:** grafY issue #113

`grafy_shared.config` holds every operator-facing `GRAFY_*` variable as one of nine
responsibility-owned `BaseSettings` sections: `AppConfig`, `AuthConfig`, `KeysConfig`,
`ExecutionConfig`, `RealtimeConfig`, `StorageConfig`, `UploadConfig`, `PluginsConfig`,
`EgressConfig`. `apps/api` composes them into one plain-`BaseModel` `Settings`, and only
the composition root reads that object.

Before this, one `Settings(BaseSettings)` held all 72 fields and imported
`grafy_api.plugins.runtime.{egress,network_policy}` in order to construct two runtime
policy objects. Configuration imported the thing it configures, so the runtime could not
import its own configuration without a cycle, and the god object flowed whole into every
DI seam.

## Invariants

**Config never imports runtime.** `grafy_shared` imports nothing from this workspace, and
`apps/api/src/grafy_api/settings.py` imports nothing from `grafy_api.plugins.runtime`.
`tests/unit/architecture/test_import_boundaries.py` enforces both. This is the invariant
that makes the split permanent; without it the next convenience property re-couples the
layers.

Runtime policy objects invert instead: `NetworkPolicy.from_config(egress)` and
`PluginEgressBrokerPolicy.from_config(egress)` live with the policy types and take an
`EgressConfig`.

**The leaf is why `grafy-shared` has no `grafy-core` dependency.** With a core
dependency, `grafy_core` and `libs/storage` could never import their own configuration
without a cycle. The cost is that `AuthConfig.oidc_domain_workspaces` stays a tuple of
raw `domain:slug[:name]` strings and `apps/api` parses them with
`parse_oidc_domain_workspace_grants`. That is the right trade: a leaf config package is
importable by every layer, a core-dependent one is importable by the outer layers only.

**Nothing plugin-side imports `grafy_shared`.** Plugin environments resolve `grafy_core`
from the wheel vendored in `plugins/*/wheels`, never from the monorepo. A shared config
import inside a Plugin would silently break guest isolation and would not resolve at
runtime. Configuring a Plugin sandbox remains the host's job: the host reads its sections
and passes concrete values into the sandbox environment.

**No operator-facing rename.** All 72 `GRAFY_*` names, their defaults and their bounds
survive; `tests/unit/api/test_settings.py` pins that set and cross-checks `.env.example`.
Each section uses `env_prefix="GRAFY_"` and **never** `env_nested_delimiter`, so
`GRAFY_STORAGE_BUCKET` stays `GRAFY_STORAGE_BUCKET` rather than becoming
`GRAFY_STORAGE__BUCKET`. `extra="ignore"` is mandatory per section: every section sees
the other sections' variables in the same flat namespace and must not reject them.

**Secrets stay `SecretStr` with no dump path.** `oidc_client_secret`,
`oidc_auth_wrapping_key`, `credential_encryption_key`, `command_hmac_key`,
`database_url`, `s3_access_key_id` and `s3_secret_access_key` are secret material. No
section and no composed parent gains an export, and the redaction tests cover the
composed parent so nesting cannot weaken them.

## Considered alternatives

**Reshape `Settings` in place inside `apps/api`.** Rejected: it leaves the inversion
intact. The reason the object could not be narrowed was the cycle, not its location, and
a `libs/shared` package that has existed as two zero-byte files since `313d2a07` is the
declared home for this.

**Give each section its own prefix (`GRAFY_AUTH_`, `GRAFY_STORAGE_`).** Rejected: it is
an operator-visible rename of 72 variables for an internal refactor.

**`Settings.__getattr__` delegation to sections during migration.** Rejected: invisible
to the type checker, so it hides exactly the readers the refactor exists to eliminate.
Callers name the section they use, or they do not compile.

**`app.state.settings` retained with narrowing at the call sites.** Rejected: keeping the
whole object reachable from routes is what let new code reach for it. Its three readers
now take a narrow carrier (`AppIdentity.public_origin`, `GraphRoomHub.heartbeat_seconds`,
`AuthService.pat_max_lifetime_seconds`).

## Consequences

Destination-syntax and pinned-broker-image validation moved from `EgressConfig` parsing
to `PluginEgressBrokerPolicy.from_config`, because the destination grammar belongs to the
Plugin runtime and config may not import it. `create_app` therefore builds the egress
policy up front, so a half-wired egress deployment still fails before it serves a request
rather than at first sandbox start.
