set dotenv-load
set shell := ["bash", "-euo", "pipefail", "-c"]

grafy_env := env_var_or_default("GRAFY_ENV_FILE", "/etc/grafy/grafy.env")
grafy_override := env_var_or_default("GRAFY_COMPOSE_OVERRIDE", "/etc/grafy/storage.override.yaml")

# List available recipes.
default:
    @just --list

# Install the default Python and web workspaces.
install:
    uv sync
    npm --prefix apps/web ci

# Install all optional plugins and the web workspace.
install-all:
    uv sync --all-extras
    npm --prefix apps/web ci

# Start the API. System host Plugins are loaded only from the configured exact
# deployment manifest; installed packages are never discovered ambiently.
api: db-upgrade
    uv run --exact --no-dev --package grafy-api uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the web development server.
web:
    npm --prefix apps/web run dev

# Run backend and web tests.
test:
    uv run --all-extras pytest
    npm --prefix apps/web test

# Run Python and web linters.
lint:
    uv run ruff check apps/api/src libs/client/src libs/core/src libs/persistence/src libs/storage/src plugins/*/src infra/db/migrations scripts tests
    npm --prefix apps/web run lint

# Format the web app with Prettier. See apps/web/.prettierrc.
format:
    npm --prefix apps/web exec prettier -- --write "src/**/*.{ts,tsx,css,md,json}"

# Run Python and TypeScript type checks.
typecheck:
    uv run --all-extras basedpyright
    npm --prefix apps/web run typecheck

# Verify the generated API client contract.
contract:
    npm --prefix apps/web run check:api

# Build the production web bundle.
build:
    npm --prefix apps/web run build

# Run the complete retained contract.
check: test lint typecheck contract build

# Exercise the workbench runtime without the browser.
smoke:
    uv run --extra ocr python scripts/smoke_workbench.py

# Run the disposable live HTTP/PAT multimodal graph contract.
e2e-live:
    uv run python scripts/e2e/run_live.py

# Upgrade the database to the latest migration.
db-upgrade:
    uv run --no-dev alembic upgrade head

# Downgrade the database by one migration.
db-downgrade:
    uv run --no-dev alembic downgrade -1

# Show the current database migration.
db-current:
    uv run --no-dev alembic current

# Show database migration history.
db-history:
    uv run --no-dev alembic history --verbose

# Generate a database migration with a required message.
db-revision message:
    uv run --no-dev alembic revision --autogenerate -m "{{ message }}"

# Start the local Docker stack and rebuild images.
docker-up:
    docker compose -f infra/docker/compose.yaml up --build

# Stop the local Docker stack.
docker-down:
    docker compose -f infra/docker/compose.yaml down

# Start the local Keycloak stack.
keycloak-up:
    docker compose -f infra/docker/compose.keycloak.yaml up -d --wait

# Stop the local Keycloak stack.
keycloak-down:
    docker compose -f infra/docker/compose.keycloak.yaml down

# Run Docker Compose against the production Grafy configuration.
prod *args:
    docker compose \
        --project-name grafy \
        --env-file "{{ grafy_env }}" \
        -f infra/docker/compose.yaml \
        -f "{{ grafy_override }}" \
        {{ args }}

# Pull the current branch, build, start, and wait for healthy production services.
deploy:
    git pull --ff-only
    just prod up --build --detach --wait

# Show production Grafy service status.
status:
    just prod ps

# Follow production Grafy logs, optionally narrowed to services.
logs *services:
    just prod logs --tail=200 --follow {{ services }}

# Run Docker Compose against the separately managed MinIO service.
minio *args:
    docker compose -f /opt/minio/compose.yaml {{ args }}

# Show MinIO service status.
minio-status:
    just minio ps

# Follow MinIO logs.
minio-logs:
    just minio logs --tail=200 --follow
