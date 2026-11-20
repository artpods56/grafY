# Handles are part of G

An older draft of this issue added `RasterImage` and `PdfFile` as a side path, kept `InPort`, and left the image plugin's nodes on `ArtifactRef`. That draft is withdrawn.

G's value classes are the handles. `image.raster@1` resolves to `RasterImage`. Each `file.*` type resolves to its own subclass of `File`. A union field `RasterImage | PdfFile` accepts those two stored types, in that source order. Nodes that today take `ArtifactRef` and then call `load_file_artifact` change in G's third commit, listed in the inventory there.

What stays vendor-specific, and is not a core change:

- Mistral still builds a data URL inside the Mistral plugin, from `await document.read(max_bytes=MISTRAL_OCR_MAX_SOURCE_BYTES)`.
- Reducto still uploads from the same `read` call.
- Content-type allowlists stay in the plugin that has them.

`read(max_bytes=n)` raises when the stored `byte_size` is already over `n`, before any storage read, and raises again if a stream with no `byte_size` exceeds `n`. A handle built from memory, `RasterImage.from_content(content, content_type=..., filename=...)`, honors the same limit against `len(content)`.

The handle has no public `ref`. After an in-memory conversion the bytes may have come from `file.png@1` while the value is a `RasterImage`. Callers branch on the class. Code that today branches on `ref.key()` in `plugins/mistral/.../ocr_sdk.py` moves to `isinstance(document, PdfFile)`.

Prompt images do not become handles. `PromptMessage.image_refs` stores artifact refs, so that port is `RefSequence[RasterImage]`. See the inventory.
