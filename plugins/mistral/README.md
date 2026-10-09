# Grafy Mistral Plugin

Independent publication input for `external.mistral`. The project vendors the
Grafy SDK wheel pinned by `uv.lock` and uses the official `mistralai` 3.1 client.

## Using OCR

Publish and promote this directory using the [Plugin publication workflow](../../docs/how-to-publish-plugins.md).
The System inventory selects isolated execution with the configured-public
network profile. `mistral.ocr.process@1`, titled Mistral OCR, calls
`https://api.mistral.ai/v1/ocr` with model `mistral-ocr-latest`. The API key is a
write-only node secret named `api_key`.

Connect exactly one input:

- `document_url`, `scalar.text@1`: an HTTPS document URL for a PDF, presentation,
  or another document container Mistral can fetch. Query parameters are supported.
- `image`, `image.raster@1`: one raster image. The node verifies its workspace,
  size, and available SHA-256 metadata before sending a data URL.

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

The three outputs are single values, so the node can run under a map edge:

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

For a batch, put Mistral OCR → Draw regions inside a Module and map the image
sequence into the Module. A target node has only one map driver, so a top-level
Draw regions cannot pair each image with its own regions.

For figures, connect the source raster and OCR `regions` to Image → Crop regions
with `kinds=image`. Crop regions returns a sequence and cannot itself be mapped.

## Development and compatibility

From this directory, run `uv sync --locked --no-sources --find-links wheels` to
install against the vendored SDK. The root workspace uses editable source.
`just api-dev external.image external.mistral` loads both plugins in process.

When upgrading the SDK, verify serialized requests through its HTTP transport
and conversion of responses into the three outputs. The SDK distinguishes omitted
fields from null. Chat, embeddings, uploads, and other endpoints are outside this
release. Document input uses URLs; there is no PDF upload lifecycle.
