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
    uv sync --extra gis --extra llm --extra ocr --extra sql
    npm --prefix apps/web ci

# Install the OCR plugin and the web workspace.
install-ocr:
    uv sync --extra ocr
    npm --prefix apps/web ci

# Install the GIS plugin and the web workspace.
install-gis:
    uv sync --extra gis
    npm --prefix apps/web ci

# Install the LLM plugin and the web workspace.
install-llm:
    uv sync --extra llm
    npm --prefix apps/web ci

# Install the SQL plugin and the web workspace.
install-sql:
    uv sync --extra sql
    npm --prefix apps/web ci

# Start the API with the default plugin set.
api: db-upgrade
    uv run --exact --no-dev --package grafy-api uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the API with the OCR plugin.
api-ocr: db-upgrade
    uv run --exact --no-dev --extra ocr uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the API with the GIS plugin.
api-gis: db-upgrade
    uv run --exact --no-dev --extra gis uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the API with the LLM plugin.
api-llm: db-upgrade
    uv run --exact --no-dev --extra llm uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the API with the SQL plugin.
api-sql: db-upgrade
    uv run --exact --no-dev --extra sql uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the API with every optional plugin.
api-all: db-upgrade
    uv run --exact --no-dev --extra llm --extra gis --extra ocr --extra sql uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the durable coding-agent worker and private generated-node executor.
agent-worker: db-upgrade
    uv run --no-dev --package grafy-agent-worker grafy-agent-worker

# Explain how to connect an MCP client to the API.
mcp:
    @echo "MCP is mounted on the API at /mcp (stateless Streamable HTTP)."
    @echo "Start the API (just api), create a workspace-bound PAT, then connect"
    @echo "an MCP client to http://127.0.0.1:8000/mcp with Authorization: Bearer <token>."
    @exit 1

# Start the local Prefect server.
prefect:
    .venv/bin/prefect server start

# Start the web development server.
web:
    npm --prefix apps/web run dev

# Run backend and web tests.
test:
    uv run --extra gis --extra llm --extra ocr --extra sql pytest
    npm --prefix apps/web test

# Run Python and web linters.
lint:
    uv run ruff check apps/agent-worker/src apps/api/src apps/mcp/src libs/agent/src libs/core/src libs/persistence/src libs/storage/src plugins/gis/src plugins/llm/src plugins/ocr/src plugins/sql/src infra/db/migrations scripts tests
    npm --prefix apps/web run lint

# Run Python and TypeScript type checks.
typecheck:
    uv run --extra gis --extra llm --extra ocr --extra sql basedpyright
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

# Exercise the trusted-development Docker sandbox and generated-node runtime.
test-agent-worker-docker:
    GRAFY_RUN_DOCKER_AGENT_TESTS=true uv run --package grafy-agent-worker pytest -q tests/unit/agent_worker/test_docker_runtime_integration.py

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

# Bootstrap the configured OIDC owner.
bootstrap-oidc-owner:
    uv run --no-dev grafy-admin bootstrap-oidc-owner \
        --issuer "${GRAFY_OIDC_ISSUER:?set GRAFY_OIDC_ISSUER}" \
        --subject "${GRAFY_OIDC_BOOTSTRAP_SUBJECT:?set GRAFY_OIDC_BOOTSTRAP_SUBJECT}"

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
