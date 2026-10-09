# Grafy Image Plugin

Independent publication input for `external.image`. The project vendors the
Grafy SDK wheel pinned by `uv.lock`. It has no Workbench dependency.

## Draw regions

`image.draw_regions@1` takes a raster image and an `image.regions@1` region set.
Boxes are scaled from the region set's `width` × `height` to the image size.

- `kinds`: optional comma-separated region kinds, such as `table,title`. Unset
  draws every kind. Names are free-form; blank entries are rejected.
- `line_width`: outline width in output pixels, 1–50, default 3.
- `fill_opacity`: translucent fill opacity, 0–1, default 0.15. Zero draws outlines only.
- `label_text`: `kind`, `label`, or `none`, default `kind`.

Output is always PNG. Images with an alpha channel retain it.
