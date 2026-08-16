FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS source

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock alembic.ini ./
COPY libs/agent ./libs/agent
COPY libs/core ./libs/core
COPY libs/persistence ./libs/persistence
COPY libs/storage ./libs/storage
COPY plugins/llm ./plugins/llm
COPY plugins/ocr ./plugins/ocr
COPY plugins/gis ./plugins/gis
COPY plugins/sql ./plugins/sql
COPY apps/api ./apps/api
COPY apps/agent-worker ./apps/agent-worker
COPY apps/mcp ./apps/mcp
COPY infra/db ./infra/db

EXPOSE 8000

CMD [".venv/bin/uvicorn", "grafy_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM source AS api-ocr

RUN uv sync --locked --no-dev --extra ocr

FROM source AS api-plugins

RUN apt-get update \
    && apt-get install --yes --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*
RUN ogrinfo --format PMTiles
RUN gdal2tiles.py --version
# User-authored SQL is executable code. Until it runs in a separate,
# least-privileged worker, the production API image must not install that
# plugin into the process that holds application data and credentials.
RUN uv sync --locked --no-dev --extra gis --extra llm --extra ocr

FROM source AS api

RUN uv sync --locked --no-dev --package grafy-api

FROM source AS agent-worker

RUN uv sync --locked --no-dev --package grafy-agent-worker

EXPOSE 8091

CMD [".venv/bin/grafy-agent-worker"]
