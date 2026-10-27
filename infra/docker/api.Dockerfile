FROM docker:28.4.0-cli@sha256:6a73c9433f2ba4279815be1e60f5739288b939dda1e48151d8c393537802de37 AS docker-cli

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS source

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock alembic.ini ./
COPY libs/client ./libs/client
COPY libs/core ./libs/core
COPY libs/shared ./libs/shared
COPY libs/persistence ./libs/persistence
COPY libs/storage ./libs/storage
COPY libs/workbench ./libs/workbench
COPY plugins ./plugins
COPY apps/api ./apps/api
COPY apps/plugin-egress-broker ./apps/plugin-egress-broker
COPY infra/db ./infra/db

EXPOSE 8000

CMD [".venv/bin/uvicorn", "grafy_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM source AS api

# GDAL's Python tools use Debian's system interpreter and bindings. The API
# uses uv's Python 3.14 and the installed application families.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates gdal-bin python3-gdal python3-numpy python3-pil \
    && rm -rf /var/lib/apt/lists/*
RUN uv sync --locked --no-dev
RUN .venv/bin/python -c "from grafy_plugin_gis.gdal import GdalCli; c = GdalCli().capabilities(); assert c.pmtiles_write and c.cog_write and c.png_write, c"

# Retained for legacy publication tooling while it is retired. Online API and
# release targets do not inherit Docker tooling.
FROM api AS api-plugins
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx

FROM api-plugins AS publisher

# Release image for deployment. The digest identifies the exact source archive
# the built-in node implementations were built from, so it is fixed at build
# time instead of being supplied by the host. Local builds use the targets above.
FROM api AS api-release

ARG GRAFY_BUILD_DIGEST
RUN printf '%s' "$GRAFY_BUILD_DIGEST" | grep -Eq '^[0-9a-f]{64}$' \
    || { echo "GRAFY_BUILD_DIGEST build argument must be a 64-character SHA-256" >&2; exit 1; }
ENV GRAFY_BUILD_DIGEST=$GRAFY_BUILD_DIGEST
