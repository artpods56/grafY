# Run Grafy with the Compose same-origin gateway

This Compose project runs four processes:

1. `migrate` applies Alembic migrations and exits.
2. `api` runs one FastAPI process. It imports no System Plugin package unless
   an exact deployment manifest binds the installed bytes to a selected
   release. Isolated-only GIS, LLM, OCR, and SQL implementations live in their
   retained Plugin images rather than the online API image.
3. `web` runs the minimal Next.js standalone server.
4. `gateway` is the only Grafy application listener (`127.0.0.1:8080` by
   default). It serves plain HTTP and does not terminate TLS.

Web and API stay on the Compose network. Do not scale the `api` service and
do not set `WEB_CONCURRENCY` or Uvicorn `--workers` above 1.

Production OIDC still requires an operator-supplied TLS endpoint for the exact
registered public origin. This repository does not provide that TLS or the
complete forwarded-header design between an additional edge proxy and the
Compose gateway.

## Prepare the VPS

Install Docker Engine with the Compose plugin, clone the repository, and create
the production environment file:

```bash
cp infra/docker/.env.production.example .env.production
openssl rand -base64 32
openssl rand -base64 32
openssl rand -base64 32
```

Put the three independently generated values in
`GRAFY_CREDENTIAL_ENCRYPTION_KEY`, `GRAFY_COMMAND_HMAC_KEY`, and
`GRAFY_OIDC_AUTH_WRAPPING_KEY`. Set `GRAFY_OIDC_ISSUER`,
`GRAFY_OIDC_CLIENT_ID`, and the client secret only when the provider uses a
confidential client. Then set the exact public HTTPS origin in
`GRAFY_PUBLIC_ORIGIN` and `GRAFY_CORS_ORIGINS`. Compose refuses to render
the deployment while a required value is unset or empty. Register the callback
`${GRAFY_PUBLIC_ORIGIN}/api/v1/auth/oidc/callback`
with the identity provider before opening login.

`GRAFY_DOCKER_DATABASE_URL` is deliberately separate from the local
`GRAFY_DATABASE_URL`. This prevents a development `.env` file with a relative
SQLite path from sending migrations to a container-local, non-persistent file.

Keep `.env.production` outside version control and restrict it to the deployment
user:

```bash
chmod 600 .env.production
```

## Start the application

```bash
docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  up --build --detach
```

Isolated Plugin execution is deliberately absent from the base Compose file.
To execute a Workspace release or an isolated System release, include the
opt-in Docker sandbox override:

```bash
docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  -f infra/docker/compose.plugin-runtime.yaml \
  up --build --detach
```

The override mounts `/var/run/docker.sock` into the API container. Possession
of that socket is effectively root-equivalent authority over the Docker host:
an API-process compromise can create privileged containers or mount host
paths. The socket is never mounted into a Plugin container. Plugin containers
run with a read-only root filesystem, UID/GID 65532, no Linux capabilities,
`no-new-privileges`, seccomp, and bounded tmpfs/resource limits. Nodes without
an exact egress capability, including `sql.artifacts.query`, retain
`--network=none`.
This protects against mistakes and ordinary unsafe Plugin code; it is not a
hostile-public-tenant kernel boundary. Keep the API private, use one API owner,
and omit the override when isolated Plugin execution is not required. A
narrow same-VPS runner can replace this socket-bearing adapter later without
changing the provider-neutral invocation contract.

### Build and pin the first-party egress broker

`network.egress` and `postgresql.egress` stay unavailable until the deployment
provides the repository-owned broker image by immutable registry digest and at
least one exact destination. Build the broker image, publish it, and record the
registry-reported manifest digest:

```bash
docker build \
  -f infra/docker/plugin-egress-broker.Dockerfile \
  -t registry.example/grafy/plugin-egress-broker:<version> \
  .
docker push registry.example/grafy/plugin-egress-broker:<version>
docker buildx imagetools inspect \
  registry.example/grafy/plugin-egress-broker:<version>
```

Build the broker from the same Grafy revision as the API. The image declares
its policy contract version, and the API checks that version during startup and
on `/ready`. A missing or different version keeps the API out of service. Update
the broker digest and the API image in the same deployment. Gate deployment
traffic on `/ready`; `/health` does not validate the broker contract.

Configure the resulting immutable reference and JSON arrays of exact
`scheme://dns-name:port` destinations:

```dotenv
GRAFY_PLUGIN_EGRESS_BROKER_IMAGE=registry.example/grafy/plugin-egress-broker@sha256:<digest>
GRAFY_PLUGIN_HTTP_EGRESS_DESTINATIONS=["https://api.example.com:443"]
GRAFY_PLUGIN_POSTGRESQL_EGRESS_DESTINATIONS=["postgresql://database.example.com:5432"]
```

For each admitted sandbox, the runtime creates a dedicated internal network
and a dedicated outbound network. The Plugin joins only the internal network;
the pinned broker is the only container on the outbound network. The API
resolves every destination once, rejects the complete answer if any address is
non-public, and gives the broker numeric connect targets. HTTPS remains an
end-to-end CONNECT tunnel. PostgreSQL uses a destination-specific raw TCP relay
under the original DNS alias and port so TLS SNI and `verify-full` identity are
preserved. The non-secret policy contains no database or proxy credentials.

Tune `GRAFY_MAX_ACTIVE_EXECUTIONS`, `GRAFY_MAX_PENDING_GRAPHS`,
`GRAFY_MAX_ACTIVE_PLUGIN_INVOCATIONS`, `GRAFY_MAX_LIVE_PLUGIN_SANDBOXES`, and
`GRAFY_MAX_DISTINCT_PLUGIN_RELEASES_PER_GRAPH` together using representative
CPU, memory, disk, and artifact workloads. The distinct-release limit must not
exceed the live-sandbox limit.

`GRAFY_PLUGIN_ROOTS` and `GRAFY_PLUGIN_AUTHORING_ROOT` default to
`/data/plugins` in the production example so coding-agent working copies live
on the durable `grafy-data` volume. Run `grafy plugin scaffold`, `review`, and
`publish-reviewed` inside the API container with an authorized Workspace owner
UUID. The scaffold builds the SDK wheel from the deployment-owned
`GRAFY_PLUGIN_SDK_PROJECT`; it never writes build output into that SDK source.

The existing Workspace commands use sanitized host subprocesses by default for
local compatibility. That mode is not a filesystem or network isolation
boundary. Operators may add `--publisher-sandbox --sandbox-image <image>` to a
direct `grafy plugin publish` invocation, but reviewed publication from the
online API remains a trusted-workspace feature rather than a hostile-code
boundary.

## One-shot System Plugin publisher

Publish System candidates with the opt-in `publisher` profile. The job is
separate from the online API and is the only service in the base Compose file
that mounts the Docker socket. It receives storage/database configuration but
none of the OIDC, credential-encryption, command-HMAC, LLM, or other online API
secrets.

Set `GRAFY_PUBLISHER_SOURCE_ROOT` to an absolute, deployment-owned host
directory containing System Plugin projects. `GRAFY_PUBLISHER_SCRATCH_ROOT`
must also be an absolute host path and is mounted at the identical path in the
job so sibling sandbox containers can bind the exact frozen snapshot. The
Compose passes that path to Grafy as
`GRAFY_PLUGIN_PUBLISHER_SCRATCH_ROOT`. The default scratch path is
`/tmp/grafy-plugin-publisher`.

Build the publisher image, then publish one candidate globally:

```bash
docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  --profile publisher \
  build publisher

docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  --profile publisher \
  run --rm publisher \
  plugin publish /publisher-input/<plugin-directory> \
  --global \
  --slug <plugin-slug> \
  --sandbox-image "${GRAFY_PUBLISHER_IMAGE:-grafy-publisher:local}"
```

Mount a protected platform-token file into the one-shot container and set
`GRAFY_TOKEN_FILE` to that in-container path. The token must include
`plugin.publish_global`.

The checked-in `publisher` Dockerfile target owns this image. It extends the
`api-plugins` target with the Docker CLI and buildx plugin. Keep
`GRAFY_PUBLISHER_IMAGE` pointed at a digest-pinned build in production. See
[How to publish native System Plugins](../../docs/how-to-publish-native-system-plugins.md)
for the native base image, registry, token rotation, promotion, and retirement
steps.

`publish --global` has no host-verification option. Dependency lock checking and
locked sync run in resource-bounded containers with package-network access.
Candidate tests and catalog inspection then run in fresh containers with no
network, a read-only root filesystem, a read-only frozen source mount, a
read-only environment mount, no Linux capabilities, `no-new-privileges`, and
explicit CPU, memory, PID, timeout, temporary-disk, and captured-output limits.
Only an explicit non-secret environment is passed to those containers.

Global publication does not select the release. Promote its exact revision
separately:

```bash
docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  --profile publisher \
  run --rm publisher \
  plugin promote <plugin-slug>@<revision>
```

Promotion requires `plugin.promote_global`. Add `--if-generation
<current-generation>` only when the job must fail if another operator changed
the selection concurrently.

Docker-socket possession remains root-equivalent host authority. Restrict this
job to platform operators/CI, pin `GRAFY_PUBLISHER_IMAGE` by digest in
production, and never run it as a long-lived service. Dependency fetch still
trusts the configured package indexes and image supply chain; this repository
does not provide package provenance verification, a remote Docker authorization
proxy, or a stronger VM/microVM tenant boundary. Every checked-in System project
is a self-contained publisher input with its own tests, lock, and exact vendored
SDK wheel; additional candidates must meet the same non-escaping dependency
contract. Authenticated private package indexes are unsupported because the
sandbox deliberately has no credential injection contract.

Check readiness and logs:

```bash
docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  ps

docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  logs --follow gateway api web
```

Compose waits for migration and Prefect health before starting the API, waits
for the API before starting the web server, and waits for both before starting
the gateway.

## SSH tunnel for plain-HTTP diagnostics

On a host such as `ai-test-ihpan`, forward the loopback gateway locally for
unauthenticated HTTP diagnostics:

```bash
ssh -N -L 8080:127.0.0.1:8080 ai-test-ihpan
```

The local end of this tunnel is `http://127.0.0.1:8080`. SSH protects the
transport, but it does not turn the gateway into an HTTPS server. Do not point
an HTTPS client at this port. OIDC login, Secure cookies, and an authenticated
production smoke must go through a separately configured TLS endpoint for the
registered public origin.

## Prefect

The Prefect image is pinned to the same `3.6.21` version used by the Grafy
API. Grafy submits local flows to `http://prefect:4200/api`; execution still
happens inside the API container, so this topology does not require a Prefect
worker.

Prefect stores its SQLite database in the separate `prefect-data` volume.
Its dashboard port is bound to `127.0.0.1:4200`. Access it without adding a
public gateway route:

```bash
ssh -L 4200:127.0.0.1:4200 deploy@your-vps
```

Then open `http://127.0.0.1:4200`.

## Same-origin routing contract

Checked configuration lives at `infra/docker/gateway/nginx.conf`:

The checked gateway listens on plain HTTP port 8080. Its forwarding-header
rules describe the direct gateway-to-API hop only; they overwrite incoming
forwarded headers with the gateway's direct peer and scheme. Do not treat this
file as TLS termination or as a complete two-proxy configuration.

- `/` proxies to the Next.js web process.
- `/api/` proxies to the API process with a trailing-slash `proxy_pass` that
  strips only `/api`, so public `/api/v1/...` becomes FastAPI `/v1/...`.
- Preserve WebSocket upgrade on graph-room paths and disable proxy buffering
  for SSE and long-lived responses.
- For this direct plain-HTTP hop, overwrite rather than append forwarding
  headers:

  ```nginx
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-For $remote_addr;
  proxy_set_header X-Forwarded-Proto $scheme;
  ```

  The Compose network uses subnet `172.30.0.0/24` with bridge gateway
  `172.30.0.1`. Because the gateway container receives a dynamic address in
  that subnet, Uvicorn trusts the configured subnet CIDR rather than the bridge
  gateway address. If the subnet overlaps another Docker network, set
  `GRAFY_DOCKER_SUBNET` and `GRAFY_DOCKER_GATEWAY` together; never use
  `*` as the trusted range.

Browser traffic uses the opaque Grafy session cookie after OIDC login. The
operator-supplied public endpoint must terminate TLS for that origin before
production login.

## One API owner

Collaboration rooms, journals, presence, and shared execution assume exactly one
FastAPI owner process. Compose sets `GRAFY_REQUIRE_SINGLE_API_OWNER=true` and
`WEB_CONCURRENCY=1`. On startup the API acquires an exclusive lock file under
the data workspace; a second owner fails closed. Do not add replicas, Uvicorn
`--workers`, or shared room pubsub across processes until a separate design is
accepted.

## Persistence, backup, and rollback

The `grafy-data` volume contains the Grafy SQLite database, staged
uploads, and local artifact objects. The `prefect-data` volume contains Prefect
orchestration state. Treat migrations as a maintenance window for SQLite:

Each staged file is limited to 64 MiB. The gateway allows 65 MiB request bodies
to leave room for multipart framing, while the API enforces the exact file-byte
limit. Staged files are durable graph inputs: saved graphs retain their upload
keys and reread the files on later runs. There is therefore no age-based cleanup
or workspace quota yet; monitor the data volume until upload promotion/reference
tracking can make deletion and transactional quota reservation safe.

With `GRAFY_STORAGE_BACKEND=s3`, browsers PUT directly to presigned URLs. Keep
MinIO private: include `compose.shared-storage.yaml` and set
`GRAFY_S3_SIGNING_ENDPOINT_URL=${GRAFY_PUBLIC_ORIGIN}/storage` so uploads go
through the gateway's `/storage/` location. See
[`docs/deploy/upload-storage.md`](../../docs/deploy/upload-storage.md).

1. stop gateway and API traffic (and Prefect if it might touch shared state);
2. confirm one API owner and no active execution;
3. checkpoint/truncate the SQLite WAL and create a consistent backup with the
   SQLite backup API or a stopped-volume snapshot;
4. back up the complete Grafy data volume and separately protect encryption,
   auth-wrapping, command-HMAC, and OIDC client secrets;
5. run `PRAGMA integrity_check` and restore the backup into a scratch location
   before upgrading.

Backup while the stack is stopped:

```bash
docker run --rm \
  --volume grafy_grafy-data:/source:ro \
  --volume "$PWD/backups:/backup" \
  alpine \
  tar -czf /backup/grafy-data.tgz -C /source .

docker run --rm \
  --volume grafy_prefect-data:/source:ro \
  --volume "$PWD/backups:/backup" \
  alpine \
  tar -czf /backup/prefect-data.tgz -C /source .
```

Restore only while the Compose project is stopped. Roll back by restoring the
volume backup, checking out the previous known-good image/git revision, and
bringing the stack up without re-running forward migrations against restored
data unless that revision's Alembic head matches. Use external PostgreSQL and
S3-compatible storage before introducing multiple API replicas; that topology
is out of scope for the current release gate.

## Phase 7 release checklist (operator)

Automatable pieces already covered in CI/unit tests: one-owner fence, Compose
gateway/proxy contract, and two-session API/WS collaboration acceptance
(`tests/unit/api/test_collaboration_acceptance.py`). The items below still need
a human on a real host/IdP/data copy.

- [ ] Exact `GRAFY_PUBLIC_ORIGIN` and OIDC callback registered
- [ ] Secrets generated and backed up outside the data volume
- [ ] Plain HTTP gateway serves `/`, `/api/v1` on loopback `:8080` only
- [ ] Separate TLS endpoint and both proxy hops validated for the public origin
- [ ] One API replica / one worker; second owner fails startup
- [ ] Backup + integrity check rehearsed on a copy of realistic data
- [ ] Authenticated browser smoke through the gateway
- [ ] Live two-browser collaboration smoke (converge, presence, shared run, revoke)
- [ ] Collaboration drain before upgrade; restore rehearsed

## Stop or upgrade

```bash
docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  down

git pull --ff-only

docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  up --build --detach
```

Do not add `--volumes` to `down` unless deleting all persisted Grafy data is
intentional.
