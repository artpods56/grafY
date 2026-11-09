set dotenv-load
set shell := ["bash", "-euo", "pipefail", "-c"]

grafy_env := env_var_or_default("GRAFY_ENV_FILE", "/etc/grafy/grafy.env")
grafy_override := env_var_or_default("GRAFY_COMPOSE_OVERRIDE", "/etc/grafy/storage.override.yaml")

# List available recipes.
default:
    @just --list

# Install the default Python and web workspaces and the Git commit hook.
install:
    uv sync
    npm --prefix apps/web ci
    uv run prek install

# Start the API with installed application families and native GIS tools.
api: db-upgrade
    uv run --exact --no-dev uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the API with installed families and reload edits under apps, libs and plugins.
api-dev: db-upgrade
    uv run --no-dev uvicorn grafy_api.main:app --reload --reload-dir apps --reload-dir libs --reload-dir plugins --host 0.0.0.0 --port 8000

# Start the web development server.
web port="":
    npm --prefix apps/web run dev {{ if port != "" {"--port=" + port} else {""} }}

# Run backend and web tests.
test:
    uv run pytest
    npm --prefix apps/web test

# Prove presigned S3 uploads through the gateway's /storage/ location.
test-storage-gateway:
    #!/usr/bin/env bash
    set -euo pipefail
    stack=(docker compose --file infra/docker/compose.storage-gateway-test.yaml)
    trap '"${stack[@]}" down --volumes' EXIT
    "${stack[@]}" up --detach --wait
    GRAFY_TEST_S3_GATEWAY_URL=http://127.0.0.1:${GRAFY_TEST_GATEWAY_PORT:-18080}/storage \
    GRAFY_TEST_S3_ENDPOINT_URL=http://127.0.0.1:${GRAFY_TEST_MINIO_PORT:-19000} \
        uv run pytest -q -o log_cli=false tests/integration/uploads/test_storage_gateway.py

# Run Python and web linters.
lint:
    uv run ruff check apps/api/src libs/client/src libs/core/src libs/persistence/src libs/shared/src libs/storage/src plugins/*/src infra/db/migrations scripts tests
    npm --prefix apps/web run lint

# Format the web app with Prettier. See apps/web/.prettierrc.
format:
    cd apps/web && npm exec prettier -- --write "src/**/*.{ts,tsx,css,md,json}" "e2e*/**/*.{ts,tsx}" "playwright*.config.ts"

# Fail when the web app is not formatted. CI runs this.
format-check:
    cd apps/web && npm exec prettier -- --check "src/**/*.{ts,tsx,css,md,json}" "e2e*/**/*.{ts,tsx}" "playwright*.config.ts"

# Validate the hook configuration and run every hook against tracked files.
hooks-check:
    uv run prek validate-config .pre-commit-config.yaml
    uv run prek run --all-files

# Run Python and TypeScript type checks.
typecheck:
    uv run basedpyright
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
    uv run python scripts/smoke_workbench.py

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

# Deploy a CI-published commit from its pre-built images; no checkout or host build.
deploy sha:
    GRAFY_ENV_FILE="{{ grafy_env }}" GRAFY_STORAGE_COMPOSE_OVERRIDE="{{ grafy_override }}" scripts/deploy-production.sh {{ sha }}

# Run Docker Compose against the separately managed MinIO service.
minio *args:
    docker compose -f /opt/minio/compose.yaml {{ args }}
