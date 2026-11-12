# Internal tile service (apps/tiler). Own image because it is its own uv
# project: titiler.core needs starlette>=1 while the API workspace pins <1.
#
# Both bases are pinned by digest so a rebuild of the same commit is the same
# image. Bump them deliberately: `docker pull python:3.13-slim-trixie` and
# `docker pull ghcr.io/astral-sh/uv:<version>`, then copy the printed digests.
FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv

FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS build

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Dependencies first so source edits do not rebuild the wheel layer.
COPY apps/tiler/pyproject.toml apps/tiler/uv.lock ./
RUN uv sync --locked --no-dev --no-editable --no-install-project

COPY apps/tiler/src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS tiler

# rasterio's bundled GDAL needs libexpat, which the slim base omits.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 tiler \
    && useradd --system --uid 10001 --gid tiler --no-create-home --shell /usr/sbin/nologin tiler \
    && install -d -o tiler -g tiler /cache

WORKDIR /app
COPY --from=build /app/.venv /app/.venv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH \
    TILER_CACHE_DIR=/cache

# Fail the build, not the deploy, if the native stack does not load.
RUN python -c "import rasterio, rio_tiler, titiler.core, grafy_tiler.app; print(rasterio.__gdal_version__)"

USER 10001:10001
EXPOSE 8100
VOLUME ["/cache"]

CMD ["python", "-m", "grafy_tiler"]
