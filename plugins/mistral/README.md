# Grafy Mistral family

Application-owned node family for the Mistral OCR API. Its stable identifier is
`external.mistral`, it is registered in-process by
`apps/api/src/grafy_api/services/families.py`, and it uses the official
`mistralai` 3.1 client.

## Using OCR

`mistral.ocr.provider@1` (Mistral OCR) provides the engine for Document OCR
(`ocr.read_document@1`). Set the provider's write-only `api_key` secret and
connect a raster image or PDF to Document OCR. Mistral sends the image or PDF as a data URL to
`https://api.mistral.ai/v1/ocr` using model `mistral-ocr-latest`.

The six settings are:

- `table_format`: `markdown`, `html`, or unset. Extracted tables are inserted into
  page Markdown in place of their table links.
- `extract_header`: move headers out of page Markdown, default false.
- `extract_footer`: move footers out of page Markdown, default false.
- `confidence_scores_granularity`: `block`, `page`, or unset. Scores populate the
  matching columns in `blocks`; unavailable scores are null.
- `timeout_ms`: request timeout, 1,000–900,000 milliseconds, default 120,000.
- `max_retries`: additional attempts, 0–5, default 0. Enabling retries can repeat
  a billable request. Retries cover connection failures, timeouts, and HTTP 408,
  429, 500, 502, 503, and 504. Redirects are disabled; cancellation propagates.

With this engine, Document OCR can produce three single-value outputs:

- `markdown`, `text.markdown@1`: page Markdown joined in order with blank lines.
  Table placeholders are replaced with table content; image links stay intact.
- `blocks`, `table.data@1`: one row per returned block. Columns are `page`,
  `index`, `kind`, `x0`, `y0`, `x1`, `y1`, `text`, `ref`, `confidence`,
  `min_confidence`, and `page_confidence`. Coordinates are page pixels, clamped
  to non-negative and ordered top-left, matching `regions`; block indexes start
  at zero within each page. Pages without blocks contribute no rows.
- `regions`, `image.regions@1`: one region set covering every page. `pages`
  declares each page's index and pixel dimensions; each box carries its `page`,
  kind, and label. Missing pixel dimensions fail the request with page context.

The request includes content blocks and sets `include_image_base64=false`.
Annotations are not supported in this release. Removed settings in older saved configs are ignored;
other unknown settings are rejected.

## Drawing boxes

For one image, connect OCR `regions` directly to Image → Draw regions and
connect the source raster to its `image` input. Set `page` for a document page;
boxes scale from that page's dimensions to the raster. No node produces PDF
page rasters yet.

For figures, connect the source raster and OCR `regions` to Image → Crop regions
with `kinds=image`. Crop regions returns a sequence and cannot itself be mapped.

## Development and compatibility

`uv sync` at the repository root installs this family into the workspace, because
it is a workspace member. Run its own suite with
`uv run --directory plugins/mistral pytest -q`.

When upgrading the SDK, verify serialized requests through its HTTP transport
and conversion of responses into the three outputs. The SDK distinguishes omitted
fields from null. Chat, embeddings, uploads, and other endpoints are outside this
release.
