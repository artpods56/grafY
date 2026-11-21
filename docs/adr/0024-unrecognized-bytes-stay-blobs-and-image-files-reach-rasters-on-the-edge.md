# ADR 0024: Unrecognized bytes stay blobs, and image files reach rasters on the edge

- **Status:** Accepted
- **Supersedes:** ADR 0008
- **Related:** `CONTEXT.md` (file format artifact, file blob artifact, extension
  claim), ADR 0013, ADR 0022, `docs/design/capability-providers/`

## Context

Two operators did what a connection already does.

`image.decode@1` ("Read images") turned `file.{png,jpeg,webp,tiff,bmp}@1` handles
into `image.raster@1` values. The same five mappings are canonical artifact
conversions with the same verification, so an edge from an image file into a
raster port produced the same value without the extra step on the canvas. The
node was a second door to one room, and it was the door people had to find.

`file.interpret@1` ("Set file type") let a person bind its output to one claimed
`file.*` format and rewrote `file.blob@1` bytes as a new artifact of that type.
It was the only node that chose its artifact type per instance, so the format
select on a port, the bindable-type resolution for declared dependencies, and the
catalog filter that hid non-format types existed for it alone. Meanwhile ingest
decides the format from the extension claim, and that is where a format belongs:
a person guessing a type at the canvas is a second, weaker claim on the same
question.

## Decision

Both operators are removed from the application registry. Nothing replaces them.

- An image file reaches a raster port through its canonical conversion. The
  stored `file.*` row is read, never retyped.
- A `file.blob@1` row has no route to a typed port. To use those bytes, the
  deployment claims their extension and the file is uploaded again.
- `Binds` stays. It binds the sequence family's `T`, and a future node may choose
  its artifact type per instance again. Resolving declared artifact type
  dependencies as bindable stays for the same reason.
- The `file` family keeps its extension claims and artifact type dependencies and
  owns no operator, the way the `image` family owns only the raster contract.

## Consequences

- ADR 0008's mechanism has no user. Its reasoning about artifact type bindings,
  and why the format is not a node config field, still describes how `Binds`
  works; only `file.interpret@1` is gone.
- A saved Graph holding either retired operator hydrates as an unsupported node
  and cannot run. There is no production data, so nothing migrates.
- An unrecognized upload is inert: its card keeps the ingest notice `Format not
  recognized, stored as a blob.` and no port accepts it. That is the intended
  reading of a blob, that nothing has claimed these bytes.
- The image plugin keeps `image.draw_regions@1` and `image.crop_regions@1`, which
  consume `image.raster@1` rather than files. `scripts/smoke_workbench.py` walks
  the surviving route: a seeded PNG file, its conversion on the edge, and a crop.
