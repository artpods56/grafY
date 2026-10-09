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

The four outputs are:

- `markdown`, `text.markdown@1`: page Markdown joined in order with blank lines.
  Table placeholders are replaced with table content; image links stay intact.
- `blocks`, `table.data@1`: one row per returned block. Columns are `page`,
  `index`, `kind`, `x0`, `y0`, `x1`, `y1`, `text`, `ref`, `confidence`,
  `min_confidence`, and `page_confidence`. Coordinates are page pixels, clamped
  to non-negative and ordered top-left, matching `regions`; block indexes start
  at zero within each page. Pages without blocks contribute no rows.
- `regions`, a list of `image.regions@1`: one region set per page, with its pixel
  dimensions, page index, kinds, and labels. A page that reports no pixel
  dimensions contributes no region set and is logged; its other outputs remain.
- `figures`, a list of `image.raster@1`: decoded extracted figures in page order,
  with the provider image id as filename. Unknown image formats are skipped with
  a warning; invalid base64 fails the request.

The request always includes image bytes and content blocks. Annotations are not
supported in this release. Removed settings in older saved configs are ignored;
other unknown settings are rejected.

## Drawing boxes

Connect `regions` to the Image plugin's `image.draw_regions@1` through a `map`
edge, giving one invocation per page. Connect each page's raster to `image` and
optionally set `kinds`, such as `table,title`. For an OCR `image` input there is
one page, and the same input image supplies the raster. Boxes scale from the OCR
page dimensions to the raster dimensions. No node produces PDF page rasters yet.

## Development and compatibility

From this directory, run `uv sync --locked --no-sources --find-links wheels` to
install against the vendored SDK. The root workspace uses editable source.
`just api-dev external.image external.mistral` loads both plugins in process.

When upgrading the SDK, verify serialized requests through its HTTP transport
and conversion of responses into the four outputs. The SDK distinguishes omitted
fields from null. Chat, embeddings, uploads, and other endpoints are outside this
release. Document input uses URLs; there is no PDF upload lifecycle.
