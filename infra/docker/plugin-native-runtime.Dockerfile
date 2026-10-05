FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:63018e7b676ef735eee4da4f9c2e7b5f5e3851fa023745d78ce91d1a099a35fd

COPY --from=ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1 \
    /usr/local/bin/uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gdal-bin \
        python3-gdal \
        python3-numpy \
        python3-pil \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
