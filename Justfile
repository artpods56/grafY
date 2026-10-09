set dotenv-load
set shell := ["bash", "-euo", "pipefail", "-c"]

grafy_env := env_var_or_default("GRAFY_ENV_FILE", "/etc/grafy/grafy.env")
grafy_override := env_var_or_default("GRAFY_COMPOSE_OVERRIDE", "/etc/grafy/storage.override.yaml")
plugin_native_base_image := env_var_or_default("GRAFY_PLUGIN_RUNTIME_NATIVE_BASE_IMAGE", "127.0.0.1:5000/grafy-plugin-base")
plugin_native_base_tag := env_var_or_default("GRAFY_PLUGIN_NATIVE_BASE_TAG", "gdal-tesseract")
plugin_native_platform := env_var_or_default("GRAFY_PLUGIN_NATIVE_BUILD_PLATFORM", "linux/amd64")

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

# Start the API with builtin families and Module boundaries. Published Plugins
# execute in isolated workers.
api: db-upgrade
    uv run --exact --no-dev --package grafy-api uvicorn grafy_api.main:app --reload --host 0.0.0.0 --port 8000

# Start the API with local Plugin projects loaded in-process, unsandboxed, for
# development. Pass System Plugin slugs: just api-dev external.image external.mistral
# Edits under plugins/ reload the server. Never use this in a deployment.
api-dev +slugs: db-upgrade
    #!/usr/bin/env bash
    set -euo pipefail
    export GRAFY_DEV_PLUGINS="$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' {{slugs}})"
    exec uv run --all-extras uvicorn grafy_api.main:app --reload --reload-dir apps --reload-dir libs --reload-dir plugins --host 0.0.0.0 --port 8000

# Start the web development server.
web port="":
    npm --prefix apps/web run dev {{ if port != "" {"--port=" + port} else {""} }}

# Rebuild the vendored Grafy Plugin SDK wheel from libs/core into every Plugin
# project. Plugins resolve grafy_core from these committed wheels, never from the
# monorepo, so run this whenever libs/core changes a module a Plugin imports and
# commit the rebuilt wheel with that change. tests/unit/architecture pins the
# resulting digest; update it when this recipe prints a new one.
sdk-wheel:
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    # setuptools stamps the wheel with the build clock, so an unpinned epoch
    # rewrites every tracked wheel with new bytes on every run. This makes the
    # vendored wheel a pure function of libs/core source content.
    export SOURCE_DATE_EPOCH=0
    output="$(mktemp -d)"
    trap 'rm -rf "$output"' EXIT
    uv build --wheel --package grafy-core --out-dir "$output"
    wheels=( "$output"/grafy_core-*.whl )
    if (( ${#wheels[@]} != 1 )); then
        printf 'expected one grafy-core wheel, found %d\n' "${#wheels[@]}" >&2
        exit 1
    fi
    for directory in plugins/*/wheels; do
        cp "${wheels[0]}" "$directory/"
        printf 'vendored %s\n' "$directory/$(basename "${wheels[0]}")"
    done
    (sha256sum "${wheels[0]}" 2>/dev/null || shasum -a 256 "${wheels[0]}")

# Run backend and web tests.
test:
    uv run --all-extras pytest
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
    cd apps/web && npm exec prettier -- --write "src/**/*.{ts,tsx,css,md,json}" "e2e/**/*.{ts,tsx}"

# Fail when the web app is not formatted. CI runs this.
format-check:
    cd apps/web && npm exec prettier -- --check "src/**/*.{ts,tsx,css,md,json}" "e2e/**/*.{ts,tsx}"

# Install the repository-owned Git commit hook for this clone.
hooks-install:
    uv run prek install

# Validate the hook configuration and run every hook against tracked files.
hooks-check:
    uv run prek validate-config .pre-commit-config.yaml
    uv run prek run --all-files

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

# Rebuild the SDK wheel vendored by guest plugin projects and refresh its pins.
rebuild-plugin-sdk:
    #!/usr/bin/env bash
    set -euo pipefail
    wheel_dir="$(mktemp -d)"
    trap 'rm -rf "$wheel_dir"' EXIT
    export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct -- libs/core)"
    uv build libs/core --wheel --out-dir "$wheel_dir" --clear
    wheel="$wheel_dir/grafy_core-0.1.0-py3-none-any.whl"
    cp "$wheel" plugins/image/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/table/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/gis/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/llm/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/mistral/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/ocr/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/python/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/sql/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/typesafe/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" plugins/notarius/wheels/grafy_core-0.1.0-py3-none-any.whl
    cp "$wheel" examples/plugin-notes/wheels/grafy_core-0.1.0-py3-none-any.whl
    uv lock --directory examples/plugin-notes --refresh-package grafy-core
    uv run python -c 'from hashlib import sha256; from pathlib import Path; import re, sys; p=Path(sys.argv[1]); t=Path("tests/unit/architecture/test_import_boundaries.py"); digest=sha256(p.read_bytes()).hexdigest(); s=t.read_text(); s, count=re.subn(r"(sha256\(core_wheel\.read_bytes\(\)\)\.hexdigest\(\) == \(\n\s*\")[0-9a-f]+", rf"\g<1>{digest}", s, count=1); assert count == 1, "architecture wheel pin not found"; t.write_text(s)' "$wheel"

# Run the complete retained contract.
check: test lint typecheck contract build

# Exercise the workbench runtime without the browser.
smoke:
    uv run --extra image --extra ocr python scripts/smoke_workbench.py

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

# Start the opt-in loopback registry used by the native Plugin runtime.
plugin-native-registry-up:
    docker compose -f infra/docker/compose.plugin-registry.yaml up -d registry

# Build and push the native runtime image, then print its registry manifest digest.
plugin-native-base-publish:
    #!/usr/bin/env bash
    set -euo pipefail
    metadata="$(mktemp)"
    trap 'rm -f "$metadata"' EXIT
    docker buildx build \
        --platform "{{ plugin_native_platform }}" \
        --tag "{{ plugin_native_base_image }}:{{ plugin_native_base_tag }}" \
        --push \
        --metadata-file "$metadata" \
        --file infra/docker/plugin-native-runtime.Dockerfile \
        .
    digest="$(python -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["containerimage.digest"])' "$metadata")"
    printf 'GRAFY_PLUGIN_RUNTIME_NATIVE_BASE_IMAGE=%s\n' "{{ plugin_native_base_image }}"
    printf 'GRAFY_PLUGIN_RUNTIME_NATIVE_BASE_IMAGE_DIGEST=%s\n' "${digest#sha256:}"

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
