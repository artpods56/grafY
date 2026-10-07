# Deploy Grafy from GitHub

This guide deploys one reviewed `main` commit to a single Linux host from
pre-built container images. The host needs no Git checkout and builds nothing.
PostgreSQL
runs inside the Grafy Compose project and stores its data in a dedicated Docker
volume. The database has no host port.

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
| `ghcr.io/artpods56/grafy-publisher` | `api.Dockerfile`, `publisher` target | `publisher` profile |

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
`migrate`, `api`, and `publisher`. Pin `GRAFY_POSTGRES_IMAGE` to the digest that
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
configuration, and pulls the four SHA-tagged images before stopping API
traffic. A SHA without published images fails at the pull, while the previous
release is still serving. The script then creates a PostgreSQL dump and removes the previous one-shot `migrate`
container. Compose runs Alembic once before it starts the API, waits for every
long-lived service, and requests `/api/ready` through the configured loopback
gateway port. A migration failure leaves the gateway stopped.

On the first cutover, the dump contains the new empty PostgreSQL database. On
later deployments, the dump contains the pre-migration production database.
The script never removes the `grafy-postgres` or `grafy-data` volume.

Check the result through the public TLS endpoint. Sign in and run one small
graph before you remove the archived SQLite volume.

## Roll back a failed release

The script records the deployed and previous SHAs in `/opt/graphy/.deployment`.
Database dumps use the timestamp and previous SHA in their filenames.

If the release fails before Alembic changes the database, run the script with
the previous SHA. Rollback targets must have published images, so they must be
commits from after the images were introduced. If Alembic changed the database, stop Grafy and restore the
matching dump before you start the previous commit. Do not run an older binary
against a newer schema.

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
