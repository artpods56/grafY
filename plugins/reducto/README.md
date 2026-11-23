# Grafy Reducto family

Application-owned node family for the Reducto Parse API. Its stable identifier is
`external.reducto`, it is registered in-process by
`apps/api/src/grafy_api/services/families.py`, and it uses the official `reductoai`
0.26 async client.

## Using OCR

`reducto.ocr.provider@1` (Reducto) provides the engine for Document OCR
(`ocr.read_document@1`). Set the provider's write-only `api_key` secret and
connect a raster image or PDF to Document OCR. Reducto uploads the file and calls `POST /parse`. It accepts PDF, BMP, JPEG,
PNG, TIFF, and WebP files up to 50,000,000 bytes.

Settings: `model` (`r-1` or `r-1-mini`), `page_start`, `page_end`, `table_format`
(`md` or `html`), and `timeout_s` (10–900, default 300). Requests are never retried,
because a retry can bill a document twice.

With this engine, Document OCR can produce:

- `markdown`, `text.markdown@1`: chunk content joined with a blank line.
- `blocks`, `table.data@1`: one row per block, with columns `index`, `page`,
  `original_page`, `kind`, `text`, `confidence`, `parse_confidence`, `left`, `top`,
  `width`, `height`. Coordinates are Reducto's page-normalized values, unclamped.

Reducto provides Markdown and blocks. Its result has no page pixel dimensions for region boxes.

## What the provider keeps

This node does not delete uploads or jobs. Reducto removes them under its retention
policy: its documentation states 12 hours, with one page stating 24 hours for
Growth tier and above. Confirm the window for your account before sending documents
that must not stay there.

## Egress

Every request this node makes goes through the pinned egress guard with redirects
off. Large results arrive as a presigned URL on Reducto's storage, so the node
declares dynamic destinations and downloads them over HTTPS, without the API key,
up to 64,000,000 bytes.

Tests live in `tests/unit/plugins/test_reducto_ocr.py`.
