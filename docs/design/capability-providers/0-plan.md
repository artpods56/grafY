# Capability providers

This directory is the only spec. Do not look for an older draft, a scratchpad, or a design thread. If a sentence here conflicts with one of those, this directory wins.

Implement on a branch from local `main` at `c62e8f23` in `/Users/user/Work/grafY`. These files are uncommitted on that checkout. A worktree started from `origin/main` does not contain them. There is no production data, so saved graphs, stored results and conversion versions do not need a compatibility path. Each commit still has to leave its own tests green.

The first run implements issue G, then implements the F, B, C, D and E in sequence.

## Locked decision

One declaration per artifact type. The declaration names the stored type, the Python class, and how that class is loaded and stored. A node field's annotation is the contract. `OutPort` is deleted. `InPort` is deleted. Plug options that are not a type use `Plugs`. A port that keeps a stored identity uses `Ref` or `RefSequence`. A port whose artifact type is chosen per instance uses `Binds`.

## Order

1. G, four commits, in [G-declarations-and-inferred-ports.md](G-declarations-and-inferred-ports.md). 
2. F, in [F-in-memory-conversions.md](F-in-memory-conversions.md). Conversions stay written during G. F moves them into the materializer.
3. B, node-scoped secrets. [B-node-secrets.md](B-node-secrets.md). Independent of F. Can start after G.
4. C, service outputs. [C-service-outputs.md](C-service-outputs.md). Independent of F.
5. D, the OCR node. [D-ocr-node.md](D-ocr-node.md). After B and C. Document handles already exist when G is done, so A is not a separate blocker.
6. E, the web. [E-web.md](E-web.md). After C and D.

A is not its own issue anymore. Handles, union fields and the nodes that read image and PDF bytes land inside G. [A-handles.md](A-handles.md) only records what G absorbed, so an older draft of A is not implemented on top.

- Do not start F, B, C, D or E in the same run.
- Do not bump conversion ids or versions. Source type, target type and bytes stay the same. The docstring in `libs/core/src/grafy_core/canonical_conversions.py` claims a snapshot test forces a bump. That test does not exist. Correct the docstring in the conversion commit. Do not add the test.
- Do not delete the existing "Read with Mistral" or "Read with Reducto" nodes.
- Do not add a DI framework, a second port spelling, or a temporary registry that is still there when G's last commit lands.
- Do not change `PortResponse` in `apps/api/src/grafy_api/v1/routes/catalog/models.py`. `shape_field` stays on the wire and is always null. `artifact_type` plus `also_accepts` stay. Union member order in source is the catalog order. First member is `artifact_type`, the rest are `also_accepts` in that order. Do not sort.
- Do not keep `InPort` or `OutPort` as deprecated aliases. Tests that build them are updated in the same commit that deletes them.

## Stop

Stop and write the blocker into the bottom of the G spec when any of these happen.

- A production port is not in the G inventory.
- A resolver does more with the unit of work than load the artifact row. Table, feature collection and raster scan only do that load, then read storage. If you find another query, stop.
- Pydantic's generic metadata is not `model.__pydantic_generic_metadata__["origin"]` and `["args"]`. That shape was checked on this tree for a `BaseModel` generic. Re-check before writing the walker. `get_origin(Ref[SomeModel])` is `None` on this tree.
- A node body uses a field in a way the inventory's "body" column does not mention.
- `npm run check:api` from `apps/web` reports a diff. G does not change OpenAPI. A diff means a response model moved. Do not regenerate to hide it.

## Done, for the whole slice

G is done when its four commits are on the branch, the old resolver and writer registries are gone, every inventory row matches the code, the startup check rejects a duplicate declaration and a mismatched port class, and the finish commands in the G spec pass.

The slice, after B, C, D and E as well, is done when a Run shows all of these:

- Two identical Mistral provider nodes with different keys feed two OCR nodes. Each call uses its own key, even though the provider nodes share a fingerprint.
- Switching the connector from Mistral to Reducto makes the OCR result stale. Switching back reuses the earlier Mistral result.
- Rotating or deleting the provider's key makes its consumers stale. No credential appears in an artifact, in metadata, or in a log.
- Disconnecting the provider leaves the OCR plug unfed. The Run refuses it with the usual unfed-plug error.
- With Reducto connected, the boxes port reports "not produced by Reducto". A node downstream of it reports that as its missing input, not as an empty set.
- A scan and a PDF both reach the reader through the same `document` input, chosen by the stored artifact type.
- Saving, copying and calling the Graph keep the provider selection. It is an edge.
