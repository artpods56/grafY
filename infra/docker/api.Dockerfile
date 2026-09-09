FROM docker:28.4.0-cli@sha256:6a73c9433f2ba4279815be1e60f5739288b939dda1e48151d8c393537802de37 AS docker-cli

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS source

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock alembic.ini ./
COPY libs/client ./libs/client
COPY libs/core ./libs/core
COPY libs/persistence ./libs/persistence
COPY libs/storage ./libs/storage
COPY libs/workbench ./libs/workbench
COPY plugins ./plugins
COPY apps/api ./apps/api
COPY apps/plugin-egress-broker ./apps/plugin-egress-broker
COPY infra/db ./infra/db

EXPOSE 8000

CMD [".venv/bin/uvicorn", "grafy_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM source AS api-plugins

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
# Isolated-only families and their native tools live solely in their retained
# OCI images. The online API installs only its declared bundled dependencies.
RUN uv sync --locked --no-dev --package grafy-api

FROM source AS api

RUN uv sync --locked --no-dev --package grafy-api
