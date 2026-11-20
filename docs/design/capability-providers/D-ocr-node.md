# OCR node, OcrReader contract, Mistral and Reducto provider nodes

Part of the capability-provider plan. After B and C. Handles already exist from G.

## Contract

Lives in core, next to the artifact contracts.

```python
class OcrFeature(StrEnum):
    BLOCKS = "blocks"
    REGIONS = "regions"


class OcrResult(BaseModel):
    markdown: MarkdownValue
    blocks: Table | None
    regions: ImageRegionSet | None


@service_contract("ocr.reader", version=1, title="OCR service")
class OcrReader(Protocol):
    features: ClassVar[frozenset[OcrFeature]]
    async def read(self, document: RasterImage | PdfFile) -> OcrResult: ...
```

`blocks` or `regions` is `None` when the provider does not produce that feature. `features` is a class attribute so the catalog can report it without running anything.

A reader that returns a value for a feature it did not declare, or `None` for one it did, fails the computation. The message names the provider.

## OCR node

Builtin family in `libs/workbench`. No `OutPort`. Field classes are the ports.

```python
class OcrInput(NodeInput):
    document: RasterImage | PdfFile
    reader: OcrReader


class OcrOutput(NodeOutput):
    markdown: MarkdownValue = Field(title="Transcription")
    blocks: Table | None = Field(default=None, title="Text blocks")
    regions: ImageRegionSet | None = Field(default=None, title="Boxes on the page")
```

`run` calls `inputs.reader.read(inputs.document)` and copies the result. It names no vendor.

`OcrConfig` is empty in v1. No task option exists yet that both providers honor. Add one when it does.

An optional output that is `None` because the provider lacks the feature is recorded on the computation as `unsupported_outputs: {"regions": "<provider title>"}`. A node fed by that port fails with "Boxes are not produced by Reducto", not with an empty set.

## Provider nodes

Mistral, in `plugins/mistral`:

- Operator `mistral.ocr.provider@1`, title "Mistral OCR", `secret_inputs=(API_KEY,)`, `http_egress` fixed to `https://api.mistral.ai`.
- Config is the current `MistralOcrConfig` fields.
- Output field `reader: MistralReader`. `features = {BLOCKS, REGIONS}`.
- `MistralReader.read` reuses `ocr_sdk.py` and `build_ocr_output`. The document argument is the handle from G.
- The document-link input of "Read with Mistral" is not on the OCR node in v1.

Reducto, in `plugins/reducto`:

- Operator `reducto.ocr.provider@1`, title "Reducto", current `ReductoOcrConfig` fields.
- `features = {BLOCKS}`.

Both:

- Add the new operator ids next to the existing OCR ids in `apps/api/src/grafy_api/node_secrets.py` `_deployment_default`, so a deployment key still works.
- The existing "Read with Mistral" and "Read with Reducto" nodes stay and keep their tests. Shared code moves into the reader. The old nodes call the reader.

## Tests

The end-to-end list in `0-plan.md`, run through the Run service with recorded HTTP fixtures. No live calls.

Also:

- A contract violation, `features` says `REGIONS` and the result has `None`, fails and names the provider.
- The old and new Mistral nodes produce the same transcription for the same fixture.

## Surfaces

`features` appears on the provider's service output in the catalog. E reads it.

The contract and the OCR node are app-owned. Providers stay in their plugins.

`CONTEXT.md` entries "OCR node" and "provider node".

## ASSUMPTIONS

- Each reader implementation declares `title: ClassVar[str]` matching its provider
  node title. `unsupported_outputs` records that string.
- A downstream missing-input message uses the **target** port title:
  `"{title} are not produced by {provider}"` (for example "Boxes are not produced
  by Reducto" when the consumer input is titled "Boxes").
- `features` on a service output port is exposed on `PortResponse` so E can mute
  ports without running the provider.
- `unsupported_outputs` is written into the computation's artifact metadata. The
  binder loads it from a sibling artifact when a connected port is absent from
  the stored result.
