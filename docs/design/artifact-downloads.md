# Artifact downloads: format-aware export

- **Status:** Proposal (open for review)
- **Date:** 2026-08-13
- **Audience:** Engineers changing artifact persistence, the `/v1` artifacts API,
  or the workbench artifact viewer
- **Related:** [backend architecture](backend-architecture.md),
  [product vocabulary](../../CONTEXT.md)

## Summary

This design introduces a small, explicit **download contract**: every artifact
declares the *export formats* it can be rendered into, a single endpoint turns
an artifact into a chosen format, and the frontend offers a **Download** action
on the **Artifact Viewer node** (under its "..." menu) with a format picker. It
does **not** change how artifacts are stored, resolved, or previewed.

### What this proposal does and does not change

**Does:**
- Add an `ArtifactExportFormat` / per-type format table to the artifact-type
  declaration layer.
- Add one new endpoint `GET /workspaces/{workspace_id}/artifacts/{artifact_id}/download?format=...`
  that renders the artifact into the requested format and returns it as a
  proper attachment.
- Add a **Download** item + format picker to the Artifact Viewer node's
  "..." overflow menu (replacing the table-only "Download JSON" link).
- Keep the existing `/content` endpoint as the *raw stored bytes* stream.

**Does not:**
- Change artifact storage, payload schemas, resolvers, or conversions.
- Change preview endpoints (`/table/page`, `/geo/...`).
- Add a new artifact type. Format export is presentation, not data.

---

## 1. The core idea: format is a property of *types*, not *instances*

An artifact is an instance of an `ArtifactTypeSpec`. The set of formats it can
be downloaded as is naturally a property of the **type** (every
`table.data@1` artifact can become CSV), not of each artifact instance.
So we attach the format table to the type declaration, right beside `title`
and `payload_schema`:

```python
ArtifactTypeSpec(
    key=ArtifactTypeKey("table.data", 1),
    title="Table",
    payload_schema=...,
    export_formats=(
        ArtifactExportFormat(
            format="json",
            content_type="application/json",
            filename="table.json",
        ),
        ArtifactExportFormat(
            format="csv",
            content_type="text/csv",
            filename="table.csv",
        ),
        ArtifactExportFormat(
            format="xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="table.xlsx",
        ),
    ),
)
```

### Format taxonomy

| Format | Meaning | Typical artifact types |
|---|---|---|
| `json` | The **whole artifact** as one JSON document (its canonical payload) | every type with a payload |
| `txt` | A **text scalar** as bare text (no envelope) | `scalar.text@1`, `text.markdown@1`, `llm.completion` content |
| `csv` | A **table** streamed as delimited rows (full artifact, not a page) | `table.data@1` |
| `xlsx` | A table as a workbook | `table.data@1` |
| `png` / `webp` | Raster / image bytes | `image/*`, `geo.raster_scan` tiles |
| `geojson` | Feature collection as GeoJSON | `geo.feature_collection@1` |
| `pmtiles` | Vector archive | `geo.feature_collection@1` projection |

Not every format applies to every type. The type's `export_formats` tuple is
the **allow-list**; anything outside it is rejected with a clear error. This is
the key safety property — we never guess what a type can export.

---

## 2. Default format per artifact kind

To make "just download it" work without a picker, each type also declares a
**default** format (first entry in `export_formats`). The convention:

| Artifact kind | Default format | Why |
|---|---|---|
| JSON payloads (`llm.*`) | `json` | whole-document is the faithful representation |
| Text scalars (`scalar.text`, `text.markdown`) | `txt` | users want the bare value, not `{"value": ...}` |
| Tables (`table.data`) | `csv` | spreadsheet-friendly, most common human use |
| Geo feature collections | `geojson` | interoperable, drop into GIS tools |
| Raster / images | `png` | original bytes |

The default is what the plain "Download" button does; the picker lets a user
override it.

---

## 3. Endpoint design

One endpoint, one query parameter, one attachment:

```
GET /v1/workspaces/{workspace_id}/artifacts/{artifact_id}/download?format=csv
```

- **Auth:** `require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS)`
  — same as every existing artifact view endpoint. Download is read-only.
- **Validation:** `format` must be in the type's `export_formats` allow-list.
  Unknown or unsupported → `400` with a message listing supported formats.
- **Success:** returns the rendered bytes as `Content-Disposition: attachment`,
  with `filename` derived from the format entry (plus the artifact id so
  filenames are unique and safe, e.g. `table-<id>.csv`).
- **Errors:** `404` (missing artifact), `400` (bad format / bad request),
  `500` (content unavailable) — mirroring the existing artifacts routes.

### Why a new endpoint instead of overloading `/content`

The existing `/content` is defined as *raw stored bytes* and is already used by
the frontend to fetch JSON for previews (with `Accept: application/json`).
Overloading it with a `format` parameter would conflate two very different
semantics:

- Raw bytes is a **read-back of storage** (returns exactly what the writer
  wrote, including envelopes like `{"value": "..."}`).
- Format export is a **rendering** (produces `value` as bare text, or a table
  as CSV).

Keeping them separate means `/content` stays a faithful storage read while
`/download` is the presentation layer. This matches the existing split between
`/content` and the preview endpoints (`/table/page`, `/geo/...`).

---

## 4. Rendering rules per format

Export is a **renderer** in the API service layer — it reads the artifact the
same way previews already do, then serializes. It never mutates storage.

### `json` — whole artifact
Reuse the existing `load_content` reconstruction path (table dump, geo
reconstruction) and return it as `application/json`. For inline payloads, this
is the canonical payload document. For chunked tables, the reconstructed
`Table` model dump. This is the only format that can be large; apply the
existing byte-budget discipline where relevant.

### `txt` — text scalar
For `scalar.text@1` and `text.markdown@1`, return the **value field** directly
(`TextValuePayload.value` / `MarkdownValue.markdown`) as `text/plain; charset=utf-8`,
not the JSON envelope. This is the single most valuable download for text
artifacts and the clearest gap today: `/content` currently returns the whole
`{"value": "..."}` envelope, which is useless for "give me the text."

### `csv` — table
Load the full `Table` via `load_table_artifact` (the same reader previews use)
and serialize columns + rows to RFC-4180 CSV:

- Column headers from `TableColumn.id` (fall back to `title` when id is an
  opaque slug).
- Cell values: strings quoted as needed; numbers/booleans as literals; nested
  JSON values as compact JSON text.
### `xlsx` — table workbook
Same full-`Table` reader, then stream to an `.xlsx` workbook. This adds a
dependency; mark as a later-phase format (see Phase 4).

### `geojson` / `pmtiles` — geo
Reuse the existing geo reconstruction (`GeoFeatureCollectionPayload` →
GeoJSON) and the existing PMTiles archive loader. `pmtiles` returns the stored
archive bytes as `application/vnd.pmtiles` — identical to the vector projection
served by `/geo/vector.pmtiles`, just framed as an attachment.

### `png` — raster / image
Return the stored bytes as `image/png`. For `geo.raster_scan`, the stored
source raster is the sensible whole-artifact download (not an individual tile).

### Formatting a filename
`{slug}-{artifact_id_short}.{extension}` where `slug` comes from the format
entry, e.g. `table-2f3a9c.csv`. Never trust `metadata["download_name"]` as the
filename — it's user-supplied metadata and could contain path separators. The
artifact id guarantees uniqueness and safety.

---

## 6. What we get for free (and what we avoid)

### Wins
- **One mental model**: "artifact type → formats" is a single declaration site,
  visible next to `title` and `payload_schema`.
- **Safe by construction**: an unknown type has no `export_formats`, so it
  simply has no download — we never guess. Adding a format is a one-line
  declaration, not a switch-case scattered across routes.
- **Text and tables get real downloads** — the two cases users actually reach
  for — instead of raw envelopes.
- **The action is where the user already is**: download appears in the viewer's
  "..." menu next to Delete, only when the viewer holds a renderable artifact.

### Avoided
- No new artifact types, no storage change, no resolver/conversion change.
- `/content` stays a faithful raw read; preview endpoints untouched.
- No per-instance format bookkeeping — formats live on the type, so an
  artifact never has to remember "I can be CSV."
- No download affordance on workflow/producing nodes — the viewer is the only
  place a download makes sense.

---

## 7. Edge cases and guards

| Case | Behavior |
|---|---|
| Format not in type allow-list | `400` listing supported formats |
| Missing artifact | `404` (existing pattern) |
| Content unavailable (deleted storage) | `500` `ArtifactContentUnavailableError` |
| Text artifact via `json` | Whole envelope `{"value": "..."}` (allowed; `json` is universal) |
| Table too large for CSV | Streams chunk-by-chunk (no memory bound); JSON still buffered at 64 MB |
| Filename collision / unsafe chars | id-suffixed slug, never raw `download_name` |
| Sequence download | Only focused artifact (first release) |
| No formats declared | Download control hidden; type is not exportable |

---

## 8. Implementation plan (phases)

**Phase 3 — Geo**
- Declare `geojson` on `geo.feature_collection@1`; `pmtiles` where a vector
  projection exists; `png` for raster sources. Reuse existing loaders.

**Phase 4 — XLSX (optional)**
- Add workbook writer dependency; declare `xlsx` on `table.data@1`.

---

## 9. Open decisions

1. **Sequence download** — bundle a whole sequence (zip? single JSON array?)
   or keep focused-artifact only? First release: focused only (consistent with
   "download what you're looking at").
2. **`xlsx` dependency** — worth a new workbook dependency now, or defer?
   CSV covers the spreadsheet use case in Phase 2.
3. **Filename source** — id-suffixed slug is safe but not friendly; do we want
   `metadata["source_name"]`/node titles sanitized into filenames later?
---
