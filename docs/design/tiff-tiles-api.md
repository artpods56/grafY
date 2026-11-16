# TIFF image API and canvas

Resolved from `docs/tiff-tiles-api-spec` (`76ba8107`), checked against the
implementation merged in `c1a61d3c` and this branch's base `ab7ca28b`.
The source artifact remains immutable; the tiler owns disposable derived pixels.

## Decisions

1. Accept TIFF content GDAL can render, including 8/16-bit RGB, grayscale,
   CMYK converted to RGB, and alpha. Artifact type is not an additional gate:
   TIFF-backed Plugin outputs and builtin file artifacts use the same API.
   Unsupported content returns 415 with a readable message; corrupt TIFFs return
   422. Main already rejects non-TIFF content with 415 and unreadable sources
   with 422. Distinguishing unsupported GDAL codecs from corrupt TIFFs remains a
   follow-up; both currently reach the unreadable-source 422 path.
2. All three routes take zero-based `page`, default 0. Info exposes `width`,
   `height`, `page_count`, `min_level`, `max_level`, `tile_size`, `has_alpha`,
   and `tile_format` (palette images also require PNG). No storage paths, raw
   GDAL tags, palette tables, value ranges, CRS, or renderer internals are public.
   Main already supported pages; this change narrows its metadata response.
3. Successful responses and 304s use `Cache-Control: private, max-age=300` and
   ETag. Revoked access may remain visible in browser caches for five minutes.
   Main used `private, no-cache`. Authorization and Workspace-scoped lookup
   precede conditional handling on every network request.
4. ETag hashes source SHA-256, source byte size, page, operation (including tile
   coordinates and format), thumbnail edge, and renderer version. Main already
   implements this. Manually bump `RENDERER_VERSION` and the API's matching
   `GRAFY_TILER_RENDERER_VERSION` for output changes, including tile size or JPEG
   quality. Retire derived caches when changing those settings.
5. Accept current and previous signing keys during manual rotation. API signs
   with the first trimmed entry; tiler verifies either. Main's tiler supported
   rotation but its API signed with the entire comma-separated string. This is
   corrected; the deploy guide describes restart order.
6. Whole proxy deadlines are 10 seconds for tiles/thumbnails and 30 for info,
   with no API retries. Tiler down, busy, or timed out returns 503 with
   `Retry-After` (default 2 seconds, bounded to 1–30). Main used one 35-second
   inactivity timeout. Concurrency and queue limits belong to the tiler and
   Compose, not a second API admission queue.
7. Old artifacts should lazily acquire missing source metadata on first request,
   persisted by the API. Unopenable files should return 422 and persist a
   not-displayable flag. No batch migration. **Deferred:** this requires storage
   reads, repository updates, a displayability model and concurrency tests.
   Current behavior is 422 for missing source metadata, with no persistent flag.
8. Structured logs only: render duration, cache hit and errors, collected by the
   same deployment log sink as the API. No metrics exporter. **Deferred:** the
   tiler currently has access/error logs but lacks structured cache-hit/render
   events; instrumentation and sink verification need a separate change.

## Routes and ownership

`/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/image` owns `info`,
`thumbnail?edge=128|256|512|1024`, and `tiles/{z}/{x}/{y}.jpg|png`.
Each authorizes `VIEW_ARTIFACTS`, including PAT scope, and conceals artifacts
outside that Workspace with 404. Browser requests use the same-origin session;
only the API mints short-lived internal grants. Unsetting `GRAFY_TILER_URL`
disables rendering with 501; re-enabling it requires no artifact migration.
The raw content/download routes remain available for the original TIFF.

The API does no rendering. Its generated web schema owns the public descriptor.
Builtin families and Plugins need no independent renderer or ingestion changes.
Membership revoke and artifact deletion affect subsequent network reads, subject
to the explicit five-minute browser-cache allowance.

## Canvas

The direct image card hosts OpenSeadragon in pixel space. The existing MapLibre
renderer is geographic and is unsuitable for scans; React Flow zoom transforms
the workbench, not image pixels. OpenSeadragon supplies mature image-pyramid
selection, mouse/touch pan and zoom, edge-tile handling and bounded tile caching.
The card first shows a thumbnail, then opens the selected page's pyramid.
Page switches destroy the old viewer and its pending work. Controls use the
shared UI kit. Header/ports remain canvas drag and wiring surfaces; image gestures
stay inside the image. Legacy saved artifact viewers share this card body.

Reference: https://openseadragon.github.io/docs/OpenSeadragon.TileSource.html
