FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS source

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock alembic.ini ./
COPY libs/client ./libs/client
COPY libs/crypto ./libs/crypto
COPY libs/core ./libs/core
COPY libs/shared ./libs/shared
COPY libs/persistence ./libs/persistence
COPY libs/storage ./libs/storage
COPY libs/workbench ./libs/workbench
COPY plugins ./plugins
COPY apps/api ./apps/api
COPY infra/db ./infra/db

EXPOSE 8000

CMD [".venv/bin/uvicorn", "grafy_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM source AS api

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN uv sync --locked --no-dev

# Release image for deployment. The digest identifies the exact source archive
# the built-in node implementations were built from, so it is fixed at build
# time instead of being supplied by the host. Local builds use the targets above.
FROM api AS api-release

ARG GRAFY_BUILD_DIGEST
RUN printf '%s' "$GRAFY_BUILD_DIGEST" | grep -Eq '^[0-9a-f]{64}$' \
    || { echo "GRAFY_BUILD_DIGEST build argument must be a 64-character SHA-256" >&2; exit 1; }
ENV GRAFY_BUILD_DIGEST=$GRAFY_BUILD_DIGEST
