# Grafy Mistral Plugin

Self-contained System publication input for the Mistral AI Python SDK.
The project vendors the exact Grafy SDK wheel referenced by `uv.lock`; it does
not resolve dependencies through the monorepo Workspace.

The published Plugin identity is `external.mistral`.

The OCR node calls `client.ocr.process_async` from `mistralai` 3.1. It accepts
either an HTTPS document URL (PDF, PPTX, DOCX, and the other document containers
Mistral OCR fetches itself) or one raster image artifact, which is sent as an
image data URL. Page selection, extracted images, tables, headers and footers,
content blocks, confidence scores, and JSON Schema annotations for the document
and for each extracted image are part of the same request. The API key is a
node secret bound to the configured API base URL.

## Using OCR

Publish and promote this directory using the [Plugin publication workflow](../../docs/how-to-publish-plugins.md), with slug `external.mistral`. Publication is required before the node appears in the workbench. The checked-in System inventory selects isolated execution and the configured-public egress profile.

Add `mistral.ocr.process@1` to a graph and set its write-only `api_key` secret. Connect exactly one source:

- `document_url`: a text artifact containing an HTTPS document URL. Query parameters are supported for temporary download links. The source URL is sent to Mistral and is not copied into the result artifact.
- `image`: an `image.raster@1` artifact. The node verifies its workspace, size, and available SHA-256 metadata before sending its bytes as a data URL.

The optional `document_annotation_schema` and `bbox_annotation_schema` ports accept `json.schema@1` artifacts. Annotation schemas must describe JSON objects. Returned annotations are parsed and validated before persistence. A document annotation prompt requires a document annotation schema.

The `document` output is `mistral.ocr.document@1`. It contains joined Markdown, ordered pages, dimensions, images, tables, hyperlinks, headers, footers, discriminated content blocks, confidence scores, and annotations. Image bytes are retained only when `include_image_base64` is enabled. The configured model and API origin are recorded with usage information.

`pages` uses zero-based indexes and ranges, such as `0,2-4`. Leave it unset to process all pages. `max_retries` defaults to zero; enabling it can repeat a billable request. Retries cover connection failures, timeouts, and HTTP 408, 429, 500, 502, 503, and 504. Redirects are disabled and cancellation propagates to the caller.

## Drawing OCR boxes

Connect the OCR `document` output to `mistral.ocr.regions@1`. Set `page_index` to the OCR page index and optionally filter `kinds` with a comma-separated list such as `table,title`. Connect its `regions` output and the page's raster to the Image plugin's `image.draw_regions@1`.

Boxes use the OCR page's pixel space; the draw node rescales them to the raster it receives. For OCR `image` input, use the same image. No node produces PDF page rasters yet.

## Development and compatibility

The implementation uses the official `mistralai` 3.1 client and requires `>=3.1.0,<4`. From this directory, run `uv sync --locked --no-sources --find-links wheels` to install against the vendored Grafy SDK. The root workspace uses the editable source for integration checks.

When upgrading the SDK, verify actual serialized requests through its HTTP transport and response conversion into the persisted artifact models. SDK fields may be omitted instead of serialized as null, and Python field names may differ from provider aliases.

This release implements the [OCR process endpoint](https://docs.mistral.ai/api/endpoint/ocr). Chat, embeddings, file management, batch jobs, and other Mistral endpoints are outside this release. Document input currently uses URLs; there is no PDF upload node or file-management lifecycle.
