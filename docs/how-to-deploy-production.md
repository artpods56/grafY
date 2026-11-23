# Deploy Grafy from GitHub

This guide deploys one reviewed `main` commit to a single Linux host from
pre-built container images. Application deployment needs no Git checkout or host
build. The API image contains the installed application families and GDAL.
PostgreSQL runs inside the Grafy Compose project and stores its data in a
dedicated Docker volume. The database has no host port.

The first SQLite-to-PostgreSQL cutover starts with an empty database. Archive
the old SQLite volume unless the owner explicitly approved a complete data
reset. The current PostgreSQL role owns one dedicated database and has bootstrap
privileges inside the private Grafy container network.

```mermaid
flowchart LR
	PR["Pull request"] --> CI["Required CI"]
	CI --> SHA["Approved main SHA"]
	SHA --> Images["CI publishes images tagged with the SHA"]
	Images --> Pull["Host pulls the SHA's images"]
	Pull --> DB["Back up and migrate PostgreSQL"]
	DB --> Ready["Check /api/ready"]
```

## Release images

The `publish-images` job in `.github/workflows/ci.yml` runs only for pushes to
`main`, and only after every other CI job passes. It builds `linux/amd64`
images and pushes them to GitHub Container Registry, tagged with the full
40-character commit SHA:

| Image | Source | Used by |
| --- | --- | --- |
| `ghcr.io/artpods56/grafy-api` | `api.Dockerfile`, `api-release` target | `migrate`, `api` |
| `ghcr.io/artpods56/grafy-web` | `web.Dockerfile` | `web` |
| `ghcr.io/artpods56/grafy-gateway` | `gateway.Dockerfile` (nginx config baked in) | `gateway` |
| `ghcr.io/artpods56/grafy-tiler` | `tiler.Dockerfile`, `tiler` target | `tiler` |

Because images are pushed only after green CI on `main`, a SHA that has images
is an approved commit. `GRAFY_BUILD_DIGEST` is the SHA-256 digest of
`git archive <sha>`, computed by CI and baked into the API image. Do not set it
on the host: Compose would override or remove the baked value.

The first publish creates each package as private. Either make the four
packages public in the GitHub package settings, or run `docker login ghcr.io`
on the host with a token that has `read:packages`.

## Prepare the host

Install Docker Engine, the Docker Compose plugin, and `curl`. No repository
clone is needed. Create the deployment directory and download the example
environment file for the commit you are deploying:

```bash
sudo install -d -m 700 -o "$USER" /opt/graphy/.deployment
curl --fail --location \
	--output /opt/graphy/.deployment/grafy.env \
	https://raw.githubusercontent.com/artpods56/grafY/<40-character-commit-sha>/infra/docker/.env.production.example
chmod 600 /opt/graphy/.deployment/grafy.env
```

Download the deployment script once, from a commit you trust, and keep it on the
host:

```bash
curl --fail --location --output /opt/graphy/deploy-production.sh \
	https://raw.githubusercontent.com/artpods56/grafY/<40-character-commit-sha>/scripts/deploy-production.sh
chmod 700 /opt/graphy/deploy-production.sh
```

Set the existing OIDC, public-origin, encryption, HMAC, and storage values in
`/opt/graphy/.deployment/grafy.env`. To put every `@ihpan.edu.pl`
login in one shared Workspace, add:

```dotenv
GRAFY_OIDC_DOMAIN_WORKSPACES=ihpan.edu.pl:ihpan:IHPAN
```

To let an account disable and re-enable other users through
`POST /api/v1/admin/users/{id}/disable` and `/enable`, list its verified email:

```dotenv
GRAFY_OPERATOR_EMAILS=you@example.org
```

To configure Tool packs, mount a TOML file read-only in the API service
using the site Compose override and set `GRAFY_CATALOG_CONFIG` to its path
inside the container. The API validates the file on startup.

```toml
[defaults]
workspace_packs = ["essentials", "document_ocr"]

[packs]
label_studio = false

[operators]
"ocr.filter_tiff_jev" = false
```

Defaults apply when a Workspace is created. The deployment switches apply
to discovery in every Workspace. Essentials is always available and subscribed.

Add these PostgreSQL values:

```dotenv
GRAFY_POSTGRES_DB=grafy
GRAFY_POSTGRES_USER=grafy
GRAFY_POSTGRES_PASSWORD=<64 lowercase hexadecimal characters>
GRAFY_POSTGRES_VOLUME=grafy-postgres
GRAFY_POSTGRES_IMAGE=postgres@sha256:<approved-image-digest>
```

Generate the password with `openssl rand -hex 32`. Keep it hexadecimal because
the Compose override uses the same value as both a PostgreSQL password and a
URL password.

The PostgreSQL override constructs the database URL and supplies it to
`migrate` and `api`. Pin `GRAFY_POSTGRES_IMAGE` to the digest that
you approved for the release. If the variable is absent, Compose uses the
current `postgres:17-alpine` image. A `GRAFY_DOCKER_DATABASE_URL` value affects
the base Compose file only; the PostgreSQL override ignores it.

To keep S3 or other site-specific Compose settings, put them in a separate
root-owned file. Set `GRAFY_STORAGE_COMPOSE_OVERRIDE` to its absolute path when
you run the deployment script.

## Perform the first cutover

Record the exact commit that passed CI. Use the 40-character SHA shown by
GitHub, not a branch name.

Stop the old deployment and save its volumes before you delete legacy data. If
the owner explicitly approved a complete reset, record that approval and skip
the legacy backup. The exact backup command depends on the old Compose project
and volume names. Confirm both names with `docker compose ls` and
`docker volume ls`.

Run the deployment script:

```bash
/opt/graphy/deploy-production.sh <40-character-commit-sha>
```

The script downloads that commit's `compose.yaml` and `compose.postgres.yaml`
into `/opt/graphy/.deployment/releases/<sha>/`, renders the merged Compose
configuration, and pulls the active services' SHA-tagged images before stopping
API traffic. Plugins run as application code and are included in the API image.
A SHA without published images fails at the pull, while the previous release is
still serving. The script then creates a PostgreSQL dump and removes the previous one-shot `migrate`
container. Compose runs Alembic once before it starts the API, waits for every
long-lived service, and requests `/api/ready` through the configured loopback
gateway port. A migration failure leaves the gateway stopped.

On the first cutover, the dump contains the new empty PostgreSQL database. On
later deployments, the dump contains the pre-migration production database.
The script never removes the `grafy-postgres` or `grafy-data` volume.

Check the result through the public TLS endpoint. Sign in and run one small
graph before you remove the archived SQLite volume.

## Deploy another release to ai-ihpan

Choose the release before changing the host:

```bash
git fetch origin
gh run list --branch main --workflow CI --limit 10
gh run view <run-id>
```

For the newest published image, select the newest `main` run whose four
`Publish grafy-* image` jobs succeeded. A newer merge can still be queued or
building. If the request names the newest `main` commit, wait for that commit's
images instead. Record the full SHA and keep the target fixed during deployment.

Inspect the running release and its Compose file paths:

```bash
ssh ai-ihpan 'cat /opt/graphy/.deployment/current-revision'
ssh ai-ihpan 'docker inspect grafy-api-1 --format \
	"{{ index .Config.Labels \"com.docker.compose.project.config_files\" }}"'
```

Use the deployment's existing wrapper. On `ai-ihpan`,
`/opt/graphy/.deployment/current-deployment` identifies the directory containing
`deploy.sh`. That wrapper supplies the production environment and combined site
override. Before the ADR 0017 cutover, remove the retired Plugin runtime and
egress-broker services from that override, including the API Docker socket
mount and runtime environment variables. Keep the storage, network, and secret
configuration. Do not replace the environment with an example file.

Run the pinned release and capture the complete output:

```bash
ssh ai-ihpan bash -s <<'REMOTE'
set -euo pipefail
umask 077
revision='<40-character-commit-sha>'
deployment_dir="$(cat /opt/graphy/.deployment/current-deployment)"
operation_dir="/opt/graphy/.deployment/deploy-${revision:0:8}-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$operation_dir"
cp /opt/graphy/.deployment/current-revision "$operation_dir/previous-revision"
"$deployment_dir/deploy.sh" "$revision" </dev/null >"$operation_dir/deploy.log" 2>&1
tail -20 "$operation_dir/deploy.log"
REMOTE
```

Keep `</dev/null` on the deployment command. A child Docker command can otherwise
consume the remaining script sent through SSH. Read the saved log after a
failure; do not pipe a running deployment into `head` or another command that
closes its input early.

Every family updates with the API image. Do not run Plugin publication,
promotion, or selection commands. Deploying a different source digest invalidates
node invocation caches, including GIS and provider calls.

Node requests now leave from the API network. Set
`GRAFY_EGRESS_TRUSTED_DESTINATIONS` only for deployment-owned private
services that nodes must reach. Keep deployment egress filtering as a backstop;
the application guard validates and pins graph-configured destinations.

An Agent uses the deployment default model unless whoever configured it gave it an
endpoint and key of its own, so set all three of `GRAFY_AGENT_DEFAULT_BASE_URL`,
`GRAFY_AGENT_DEFAULT_MODEL` and `GRAFY_AGENT_DEFAULT_API_KEY` or no Agent can answer.
The default endpoint may be a private model server listed in
`GRAFY_EGRESS_TRUSTED_DESTINATIONS`; an Agent's own endpoint is not, and goes through the
same pinned public-address guard as an LLM node's `base_url`. Agents do not fall back to
the deployment key: an Agent that names its own endpoint needs its own key set, and
configuring it costs the person setting it `edit_project`, not `manage_secrets`.

## Add the tiler

The `tiler` service renders TIFF artifacts into tiles and thumbnails on demand
(`docs/design/tiff-on-demand-tiles.md`). It is internal: no host port, no
gateway route, and it takes no URL, only an HMAC grant the API signs. The
release that introduces it fails `compose config` until the two operator inputs
below exist, so prepare them before deploying that SHA.

Nothing here touches the running host until you run it yourself. These steps
create secrets; keep them in the environment file and the MinIO account, never
in a commit, a ticket, or a chat.

**1. Generate the shared signing key** and put it in the environment file next
to the other keys. The API and the tiler read the same value; to rotate,
temporarily list two comma-separated keys on the tiler.

```bash
openssl rand -base64 32   # -> GRAFY_TILER_SHARED_KEY in grafy.env
```

**Manual signing-key rotation.** Keep at most current and previous keys. First
set `TILER_SIGNING_KEYS` on the tiler to `old,new` and recreate only the tiler.
Then set `GRAFY_TILER_SHARED_KEY=new,old` and recreate the API and tiler; the
API signs with the first trimmed key, while the tiler accepts both. After at
least 65 seconds (grant lifetime plus clock skew), set the shared value to
`new` and recreate both. Never print keys in logs. With Compose's common
variable mapping, override the tiler environment for the first stage. Rollback
within the overlap window is the same procedure with the order reversed.

**2. Create a read-only MinIO account.** The tiler reads objects through GDAL
and must not be able to write or list. With an `mc` alias for the operator's
MinIO (`mc alias set minio http://minio:9000 <admin-user> <admin-password>`):

```bash
cat > /tmp/grafy-tiler-read.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::workbench-artifacts/*"]
    }
  ]
}
JSON
mc admin policy create minio grafy-tiler-read /tmp/grafy-tiler-read.json
secret="$(openssl rand -hex 24)"  # a leading "-" is an mc flag
mc admin user add minio grafy-tiler "$secret"
mc admin policy attach minio grafy-tiler-read --user grafy-tiler
rm /tmp/grafy-tiler-read.json
printf 'GRAFY_TILER_S3_SECRET_ACCESS_KEY=%s\n' "$secret"   # copy into grafy.env
unset secret
```

Use the bucket in `GRAFY_STORAGE_BUCKET` if it is not `workbench-artifacts`.
Put the account's access key and secret in the environment file as
`GRAFY_TILER_S3_ACCESS_KEY_ID` and `GRAFY_TILER_S3_SECRET_ACCESS_KEY`. Do not
reuse the API's `GRAFY_S3_*` read-write key. The CI container test creates the
same account with these commands and proves that it can read an object but
cannot write or list.

**3. Attach the tiler to the MinIO network.** Add the `tiler` service to the
site storage override (`/etc/grafy/storage.override.yaml` on `ai-ihpan`), next
to `api` and `gateway`, the same way
`infra/docker/compose.shared-storage.yaml` does:

```yaml
services:
  tiler:
    networks:
      default:
      shared-storage:
```

The tiler reuses `GRAFY_S3_ENDPOINT_URL`, `GRAFY_S3_REGION` and
`GRAFY_S3_FORCE_PATH_STYLE` from the API, so set path-style addressing for
MinIO there (`GRAFY_S3_FORCE_PATH_STYLE=true`).

Enable the API proxy with `GRAFY_TILER_URL=http://tiler:8100`. The API uses
`GRAFY_TILER_SHARED_KEY` to sign reads after checking Workspace access. Unset
`GRAFY_TILER_URL` to disable the proxy without stopping the API.
`GRAFY_TILER_RENDERER_VERSION` defaults to `1` and must match the tiler renderer
version; update it whenever renderer settings change output. The API timeout
is `GRAFY_TILER_TIMEOUT_SECONDS=10` for tiles and thumbnails, and
`GRAFY_TILER_INFO_TIMEOUT_SECONDS=30` for info. These are whole-request
deadlines; the API does not retry. Rendering concurrency is bounded in the tiler.

**Sizing and limits.** The defaults suit `ai-ihpan`: 2 CPUs
(`GRAFY_TILER_CPUS`), 1.5 GiB RAM (`GRAFY_TILER_MEMORY`), an image of about
550 MB, and a 2 GiB tile cache on the `grafy-tiler-cache` volume
(`GRAFY_TILER_CACHE_MAX_BYTES`). The cache is derived data, evicted
least-recently-used, and safe to delete. `GRAFY_TILER_WORKERS` stays at 1;
concurrency is a bounded render pool (`GRAFY_TILER_RENDER_CONCURRENCY`, with
`GRAFY_TILER_QUEUE_DEPTH` waiting requests before it answers 503).

**Verify.** `docker compose ... ps tiler` should show `healthy`. The health
check opens `/health`, which also proves the cache volume is writable. The
tiler has no public URL; the API proxy that uses it ships separately.

**Roll back.** A release without a tiler needs nothing special:
`--remove-orphans` in the deploy script stops it. To retire the account,
`mc admin user remove minio grafy-tiler`.

## Verify and record the deployment

Check the host and the public endpoint:

```bash
ssh ai-ihpan 'cat /opt/graphy/.deployment/current-revision'
ssh ai-ihpan 'docker ps --filter name=grafy --format "{{.Names}} {{.Image}} {{.Status}}"'
curl --fail --silent --show-error https://graphs.ihpan.edu.pl/api/ready
curl --fail --silent --show-error --output /dev/null \
	--write-out 'HTTP %{http_code}\n' https://graphs.ihpan.edu.pl/
```

Confirm that API, web, and gateway use the target SHA and report healthy.
Verify catalog readiness in each affected Workspace. Python and SQL nodes must
be absent. Run the [GIS raster smoke procedure](how-to-run-gis.md) with a small
GeoTIFF and open its artifact before declaring the deployment usable.

Verify the source digest when release identity needs an independent check:

```bash
git archive <sha> --output=/tmp/grafy-release.tar
shasum -a 256 /tmp/grafy-release.tar
ssh ai-ihpan 'docker exec grafy-api-1 .venv/bin/python -c \
	"import os; print(os.environ[\"GRAFY_BUILD_DIGEST\"])"'
```

Keep the SHA, previous SHA, database dump path, deployment log, and verification
results in the operation directory. Keep database dumps protected. Never include environment contents or bearer
credentials in the report. Health and catalog checks do not prove an
authenticated graph run; record whether you exercised that separately.

## Roll back a failed release

The script records the deployed and previous SHAs in `/opt/graphy/.deployment`.
Database dumps use the timestamp and previous SHA in their filenames.

If the release fails before Alembic changes the database, run the script with
the previous SHA. Rollback targets must have published images, so they must be
commits from after the images were introduced. If Alembic changed the database, stop Grafy and restore the
matching dump before you start the previous commit. Do not run an older binary
against a newer schema. The schema is one baseline revision and its downgrade drops
every table, so never downgrade a deployed database to roll a release back: restore
the dump taken before the failed migration instead.

Restore a dump only during a maintenance window:

```bash
docker compose \
	--project-name grafy \
	--env-file /opt/graphy/.deployment/grafy.env \
	-f /opt/graphy/.deployment/releases/<sha>/compose.yaml \
	-f /opt/graphy/.deployment/releases/<sha>/compose.postgres.yaml \
	stop gateway api

docker compose \
	--project-name grafy \
	--env-file /opt/graphy/.deployment/grafy.env \
	-f /opt/graphy/.deployment/releases/<sha>/compose.yaml \
	-f /opt/graphy/.deployment/releases/<sha>/compose.postgres.yaml \
	exec -T postgres dropdb --if-exists --username grafy grafy

docker compose \
	--project-name grafy \
	--env-file /opt/graphy/.deployment/grafy.env \
	-f /opt/graphy/.deployment/releases/<sha>/compose.yaml \
	-f /opt/graphy/.deployment/releases/<sha>/compose.postgres.yaml \
	exec -T postgres createdb --username grafy --owner grafy grafy

docker compose \
	--project-name grafy \
	--env-file /opt/graphy/.deployment/grafy.env \
	-f /opt/graphy/.deployment/releases/<sha>/compose.yaml \
	-f /opt/graphy/.deployment/releases/<sha>/compose.postgres.yaml \
	exec -T postgres pg_restore --clean --if-exists --no-owner \
		--username grafy --dbname grafy < /opt/graphy/.deployment/<backup>.dump
```

Run the deployment script with the previous SHA, and set the same
`GRAFY_*_IMAGE` variables the script exports if you restore by hand. Use the
database name and user from `/opt/graphy/.deployment/grafy.env` when they differ
from the defaults above.

## Add a manual GitHub deployment job

The current `.github/workflows/ci.yml` is the release gate. It applies every
Alembic migration to PostgreSQL, runs backend tests, checks Python and web code,
builds the production web application and runs the automated test suites.
The workflow runs for pull requests and pushes to `main`. On `main`, it ends by
publishing the release images.

Keep production deployment separate from CI until the host has a dedicated
self-hosted runner or a narrowly scoped SSH deployment account. Add a
`workflow_dispatch` workflow when that account exists. Configure the job as
follows:

1. Require the GitHub `production` environment and its reviewer approval.
2. Accept a 40-character commit SHA as input.
3. Verify that the SHA's images exist. They exist only for CI-green `main` commits.
4. Send only the SHA to the host-side deployment command.
5. Run `/opt/graphy/deploy-production.sh <sha>` on the host.
6. Record the SHA and health-check result in the GitHub job summary.

Store the SSH key, host key, and connection details in GitHub environment
secrets. Keep `/opt/graphy/.deployment/grafy.env`, the PostgreSQL password,
OIDC client secret, encryption keys, and storage credentials on the host. The
GitHub job does not need those application secrets.

Protect `main`, require the existing CI jobs, and disable force pushes. The
manual job must deploy the approved SHA rather than whichever commit happens to
be at the tip of `main` when the job starts.

The Git commit SHA remains the release identifier for image tags, Compose files,
and rollback.
