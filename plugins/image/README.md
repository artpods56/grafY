# Grafy Image Plugin

Independent publication input for `external.image`. The project vendors the
Grafy SDK wheel pinned by `uv.lock`. It has no Workbench dependency.

## Draw regions

`image.draw_regions@1` takes a raster image and an `image.regions@1` region set.
Boxes are scaled from the selected page's `width` × `height` to the image size.

- `page`: page index to draw, default 0. A single image is page 0.
- `kinds`: optional comma-separated region kinds, such as `table,title`. Unset
  draws every kind. Names are free-form; blank entries are rejected.
- `line_width`: outline width in output pixels, 1–50, default 3.
- `fill_opacity`: translucent fill opacity, 0–1, default 0.15. Zero draws outlines only.
- `label_text`: `kind`, `label`, or `none`, default `kind`.

Output is always PNG. Images with an alpha channel retain it.

## Crop regions

`image.crop_regions@1` takes a raster image and an `image.regions@1` region set.
It returns `crops`, one PNG per matching box in region order. Boxes scale from
page pixels to the raster, then padding is applied and bounds are clamped.
Boxes with no area after clamping are skipped.

- `page`: page index to crop, default 0. A single image is page 0.
- `kinds`: comma-separated kinds, default `image`. Unset crops every kind.
- `padding`: extra pixels around each box in output pixels, 0–500, default 0.

RGB and RGBA modes are preserved. Other modes become RGB, or RGBA when they
carry transparency. Filenames are `<source stem>-<kind>-<output index>.png`;
without a source filename the stem is `region`.

This node cannot be a map target because `crops` is a MANY output. Nested
sequences and implicit flattening are not supported.
