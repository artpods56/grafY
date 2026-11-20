# Apply connection conversions in memory

Blocked by G. During G a conversion still writes an artifact, then the materializer reads it back. This issue removes that round trip for ports that take a value.

## Where it runs

MAP splits an `ArtifactRefSequence` into one ref per item after inputs are assembled. The split is in `apps/api/src/grafy_api/runs/node_execution.py`, in the block that builds per-item refs before `run_node`. If `EdgeValueResolver` returned converted values, a mapped input with a conversion would no longer be a sequence of refs, and that split would fail.

So the edge resolver keeps returning refs. For each incoming edge it also returns an `EdgeTransform`: the projection path, the conversion chain, the artifact type the chain delivers, and the connection label used in errors. The materializer, per ref, loads the value through `ArtifactValues`, runs the transform, and hands the result to the node.

The type check in `libs/core/src/grafy_core/runtime/materialization.py` today compares the ref's own type with the port's accepted types. With a transform it compares the transform's delivered type. The binder has already checked that delivered type against the port.

## When a write still happens

A port typed `Ref[...]` or `RefSequence[...]` needs a stored artifact. For those ports the converted value is written with `ArtifactValues.write` before the ref is passed through. The same write stays for an edge that crosses a Graph boundary. The boundary check already lives in `apps/api/src/grafy_api/runs/node_runner.py`.

Image conversions feed `RefSequence[RasterImage]` on the prompt node, and feed `RasterImage` on draw, crop, Mistral and Reducto. The prompt port still writes. The handle ports do not.

`RasterImage.from_content` is how a PNG file becomes a raster value without a new row. The filename on the file handle is copied onto the raster handle.

## Provenance

`MaterializationProvenance` records the upstream ref plus the projection path or conversion keys. `ArtifactValues.write` already stores that on the output. It must record the upstream ref, not the intermediate copy this issue stops creating.

Fingerprints do not change. The projection and the conversion path are already part of the connection.

Failure text stays "Failed conversion step 2/3 ... on <connection>".

## Tests

- A `.txt` file into a text input yields the decoded string. No new artifact row.
- A field projection into a typed input yields the field value. No new artifact row.
- A PNG file into a `RasterImage` input yields a handle whose `read` returns the original bytes. No new artifact row and no new storage object.
- The same PNG into a `RefSequence[RasterImage]` port still writes one converted artifact.
- A sequence through a conversion yields one value per item, in order.
- A MAP node whose mapped input has a conversion runs each item on that item's converted value.
- The consumer's output provenance names the upstream ref and the conversion key.
- A failing step reports the same message as today.

## Surfaces

`PortResponse` does not change. `npm run check:api` in `apps/web` stays clean. If `docs/design/` says a conversion produces an artifact, change that sentence in this issue.

## Assumptions

Provenance keeps the three fields on each upstream ref. An edge that projects adds `projection_path`, a list of field names. An edge that converts adds `conversion_keys`, a list of `{id, version}`. A ref port or a graph boundary that still writes stores that provenance on the written artifact under the input port name. The written artifact uses the consuming node's execution context.

The MAP type check reads the transform's delivered type. The sequence object keeps the source artifact type, so the per-item split still walks refs.

A failed projection or conversion raises `EdgeTransformError` with the resolver's old sentence. A MAP item re-raises that sentence as `NodeComputationError`, so the task group leaves the sentence intact. The materializer adds no `Input` prefix.

A sequence edge numbers its items from zero, including a sequence of one. A single ref uses the invocation index. That index is set for a MAP item and empty for a direct input.

Projection walks `model_dump()` of a loaded model, then the path. The `value` field of a JSON schema is the text a text port receives.

No canonical conversion has three steps. The failure-text test builds a three-step transform and runs it through the materializer. `docs/design/` has no sentence that says a conversion produces an artifact.
