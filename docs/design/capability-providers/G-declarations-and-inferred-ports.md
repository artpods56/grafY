# One declaration per artifact type, ports inferred from the field

Part of the capability-provider plan. This is the night run. Read `0-plan.md` before editing.

## What is wrong today

Three registries restate the same fact. A resolver says which class a stored type loads as. A writer says which class it stores. `InPort` and `OutPort` say it again on every field. Nothing checks that the three agree, and two of the mechanisms are dead or unordered.

Measured on this tree:

- `Plugin.register_artifact_conversion` stores a conversion on the plugin. `apps/api/src/grafy_api/catalog.py` and `apps/api/src/grafy_api/runs/contract.py` read only `CANONICAL_ARTIFACT_CONVERSIONS`. A plugin conversion is ignored.
- The file family registers `FileBytesResolver` for six file types so those conversions can run. A conversion whose source has no resolver is a startup hole, not a type error.
- `Resolver.target` is `type[object]`. `ArtifactOutputWriter.write` takes `object`. A node that returns the wrong model fails when the writer runs.
- Every storage-backed resolver repeats the same opening. Load the row, check the workspace, check the ref, then decode. `InlineModelResolver`, `load_file_artifact`, `TableArtifactResolver.resolve` and `FeatureCollectionResolver.resolve` each have their own copy. The table and feature-collection copies do no further unit-of-work work after that load.
- Writer registration is first-one-wins. Mistral registers writers for `text.markdown@1` and `image.regions@1`, types the text family and the image plugin own. Reducto registers a writer for markdown. The builtin image family owns `image.raster@1` (`libs/workbench/src/grafy_workbench/image/plugin.py` calls `register_artifact_type` and nothing else). The external image plugin registers the only raster writer.
- `str` is the runtime value of both `scalar.text@1` and `json.schema@1`. The port's `InPort` is the only thing that tells them apart. `callable_nodes.py` hard-codes `str` to text and `int` to integer.
- `shape_field` is accepted by `InPort` and `OutPort`, copied onto port specs, and returned by `PortResponse`. No production node sets it.
- Provenance metadata is built in `InlineModelOutputWriter.write` and again in `TableArtifactWriter.write`. The shapes match. The merge order does not. Inline applies `context.metadata` last. The table writer applies its own keys last.

`Artifact` in `libs/core/src/grafy_core/artifacts.py` is already the registration object, with a spec plus resolver and writer factories. This issue replaces those factories with one class and two functions. Keep the name `Artifact`. `ArtifactValues` is a code name. It is not `CONTEXT.md` vocabulary.

## The declaration

New module `libs/core/src/grafy_core/runtime/artifact_values.py`.

```python
@dataclass(frozen=True, slots=True)
class StoredArtifact:
    row: ArtifactObject
    storage: FileStoragePort


@dataclass(frozen=True, slots=True)
class ArtifactFiles:
    storage: FileStoragePort
    bucket: str
    workspace_id: UUID

    async def save(
        self,
        spec: ArtifactTypeSpec,
        content: bytes,
        *,
        content_type: str,
        suffix: str,
    ) -> StoredFile:
        digest = sha256(content).hexdigest()
        return await self.storage.save(
            SaveFileCommand(
                bucket=self.bucket,
                path=(
                    f"workspaces/{self.workspace_id}/{spec.key.id}/"
                    f"v{spec.key.schema_version}/{digest}{suffix}"
                ),
                stream=BytesIO(content),
                content_type=content_type,
                metadata={"artifact_kind": spec.key.id, "sha256": digest},
                allow_overwrite=True,
            )
        )


@dataclass(frozen=True, slots=True)
class EncodedArtifact:
    content_type: str
    byte_size: int
    sha256: str
    inline_payload: JsonObject | None = None
    stored: StoredFile | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Artifact[T]:
    spec: ArtifactTypeSpec
    value_type: type[T]
    resolve: Callable[[StoredArtifact], Awaitable[T]]
    write: Callable[[T, ArtifactFiles], Awaitable[EncodedArtifact]]
```

`inline_model_artifact(spec, model)` covers a pydantic model stored as inline JSON. `resolve` raises `ArtifactContractError` when `inline_payload` is missing, then `model.model_validate`. `write` dumps with `mode="json"`, `by_alias=True`, hashes the canonical JSON (`sort_keys=True`, `separators=(",", ":")`, UTF-8) and returns an `EncodedArtifact` with `stored=None` and content type `application/json`. Use it for markdown, HTML page, image regions, prompt message, completion, map layer and map document.

Scalars do not use that helper. Their stored envelope is `{"value": ...}` and the Python value is the unwrapped scalar. Copy the wrap and unwrap from `libs/workbench/src/grafy_workbench/scalar_persistence.py`. `write` of `scalar.text@1` stores `TextValuePayload`. `resolve` returns `payload.value` as `str`. Integer does the same with `IntegerValuePayload` and `int`. JSON Schema does the same with `JsonSchemaPayload`, then runs the existing canonicalization in `libs/workbench/src/grafy_workbench/schema/nodes.py` (`parse_json_schema` plus the compact `json.dumps`). That function moves next to the declaration. The node stops owning it.

## One class, one type

`ArtifactValues.__init__` fails if two declarations share a key or a `value_type`. The check is on the exact class.

`str` and `int` stay the value classes of text and integer. `StrictStr` and `StrictInt` are annotations, not runtime classes. Derivation maps `StrictStr` to `str` and `StrictInt` to `int` before the lookup. JSON Schema cannot be a `str` subclass, because that map would collapse it back to text. Its class is a model:

```python
class JsonSchemaText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: StrictStr
```

The stored payload stays `JsonSchemaPayload`. `resolve` returns `JsonSchemaText(value=payload.value)`. `write` reads `.value`, canonicalizes, and stores the payload model. Nodes that today receive a bare `str` for this type use `.value`. Those nodes are the schema builder and the OpenAI-compatible completion input.

Write-time check is exact: `type(value) is artifact.value_type`. A subclass is a different type and fails. The error names the artifact key and both class names, and it is raised before any storage call.

## ArtifactValues

Constructed once in `apps/api/src/grafy_api/services/composition.py`, from core file declarations plus `plugin_registry.artifacts`, the unit of work, storage, bucket and storage backend. `PluginRuntimeContext` gains `values: ArtifactValues` so a node factory can take it. Build `values` before the context.

`open(ref, workspace_id)` loads the row, raises `NotFoundError` when it is missing, and raises `ArtifactContractError` when `row.ref() != ref`. That is the only copy of this sequence.

`resolve(ref, workspace_id)` calls `open`, then `declaration.resolve`. Lookup is by `ref.key()` alone. The class is the result of the lookup.

`write(key, value, context)` checks the exact class, calls `declaration.write` with `ArtifactFiles`, then inserts one `ArtifactObject` and commits. Metadata order, unified on purpose:

1. Start from `context.metadata`.
2. Set `producer_node_id` from `context.node_context.node_id`.
3. Set `provenance` from `context.provenance.refs_by_input`, in the shape both writers use today, when that map is non-empty.
4. Overlay `encoded.metadata`. Type-owned keys win. Table keys that must survive are `storage_format`, `row_count`, `column_count`, `chunk_count`, `logical_byte_size`, `storage_byte_size`, `manifest_byte_size`, `manifest_sha256`. Raster and file keys include `original_filename` when the handle has one.

Inline writers today let step 1 win over producer and provenance. No caller puts those keys in `context.metadata`. The new order is the table writer's order. If a test asserts the old inline order, change the test and name the new order in the assertion message.

Storage backend on the row is `"inline"` when `encoded.stored is None`, otherwise the deployment backend. Bucket and object key come from `encoded.stored`.

## Who registers

Only the owner registers the declaration. A second registration of the same key already fails in `PluginRegistry.install`. Keep that. Also fail inside `ArtifactValues` so a core tuple and a plugin cannot both declare a key.

| Stored type | Value class | Owner today | Declaration lands |
| --- | --- | --- | --- |
| `scalar.text@1` | `str` | text family, via `TextValueResolver` | `grafy_workbench.text` |
| `scalar.integer@1` | `int` | value family, via `ScalarResolver` | `grafy_workbench.value` |
| `json.schema@1` | `JsonSchemaText` | schema family | `grafy_workbench.schema` |
| `text.markdown@1` | `MarkdownValue` | text family | `grafy_workbench.text`, `inline_model_artifact` |
| `html.page@1` | `HtmlPage` | text family | `grafy_workbench.text`, `inline_model_artifact` |
| `image.regions@1` | `ImageRegionSet` | image plugin, `plugins/image/.../plugin.py` | that plugin, `inline_model_artifact` |
| `prompt.message@2` | `PromptMessage` | llm plugin | that plugin |
| completion, see `plugins/llm/.../artifacts.py` | `CompletionPayload` | llm plugin | that plugin |
| `geo.map_layer@1` | `GeoMapLayer` | gis plugin | that plugin |
| `geo.map_document@1` | `GeoMapDocument` | gis plugin | that plugin |
| `table.data@1` | `Table` | table plugin | that plugin. Move `TableArtifactWriter.write` and `load_table_artifact` into the declaration. The resolver's row load is deleted. |
| `geo.feature_collection@1` | `GeoFeatureCollection` | gis plugin | that plugin. Move the body of `FeatureCollectionResolver` after the row load, and `FeatureCollectionOutputWriter.write`. `GdalCli` is an argument of `feature_collection_artifact(gdal=None)`, defaulting to `GdalCli()`. Tests pass the fake there. |
| `geo.raster_scan@1` | `GeoRasterScan` | gis plugin | same treatment as the feature collection. `RasterScanResolver.resolve` loads the row, checks the ref, then `storage.load`. It does not issue another query. Keep the missing-bucket check, the `source_name` and `original_filename` checks, and `verify_spatial_artifact_content`. The value stays eager. It holds the bytes. |
| `image.raster@1` | `RasterImage` | workbench image family owns the type and has no writer. External image plugin registers the writer. | workbench image family registers the declaration. `resolve` and `write` live in `grafy_core/documents.py`. Delete `plugins/image/.../persistence.py`'s `register_writer`. |
| each `file.*` in `BUILTIN_FILE_FORMATS` | its own subclass, below | no plugin owns them. `grafy_workbench.file.declaration` only registers resolvers and dependencies. | core tuple `FILE_ARTIFACTS`, passed straight into `ArtifactValues` beside the plugin list. |

Delete Mistral's and Reducto's `register_writer` calls. They do not own those types.

File subclasses, all of `File`, and `File` itself is not registered. `PngFile`, `JpegFile`, `TiffFile`, `WebpFile`, `BmpFile`, `PdfFile`, `XlsxFile`, `GeoJsonFile`, `JsonFile`, `CsvFile`, `TxtFile`, `BlobFile`. A port annotated `File` fails startup, because `File` is not a declared class.

`RasterImage` and `File` share the handle behavior in `grafy_core/documents.py`:

- `content_type`, `byte_size`, `filename`.
- `async read(self, *, max_bytes: int) -> bytes`. Refuse when `byte_size` is known and greater than `max_bytes`, before reading. Refuse a stream that passes `max_bytes` when `byte_size` is missing.
- `from_stored(stored) -> Self` for the declaration's `resolve`.
- `from_content(content, *, content_type, filename) -> Self` for conversions and for nodes that create an image in memory.
- No public artifact ref on the handle.

Raster write reads the handle with `max_bytes` of `256 * 1024 * 1024`, saves through `ArtifactFiles.save`, suffix from the content type (`.png`, `.jpg`, `.webp`, `.tiff`, `.bmp`). Unknown content type is a `ValueError` naming the type. Metadata `original_filename` when `filename` is not `None`.

A file write is the same shape, with that format's content type and suffix. Read `plugins/image/.../persistence.py` for the current raster path and hash rules and keep them. Do not invent a new layout.

Table stays eager. Both of its reading nodes need every row. A node that wants a bounded read of a table types the port `Ref[Table]` and opens the row itself. One type does not offer two classes.

## Refs

Some ports must keep a stored identity because the value they produce embeds the ref.

`Ref` is a generic pydantic model subclassing `ArtifactRef`, so existing fields typed `ArtifactRef` still accept it and `.artifact_id` still works.

```python
class Ref(ArtifactRef, Generic[T]):
    pass

class RefSequence(ArtifactRefSequence, Generic[T]):
    pass
```

Checked on this tree, 17 Nov 2026, with the project venv. `get_origin(Ref[Geo])` is `None`. The argument is `Ref[Geo].__pydantic_generic_metadata__["args"][0]` and the origin is `["origin"]`. Derivation must use that metadata. Re-check it in the first commit. If the keys differ, stop.

`ArtifactTypeVariable` is a dataclass instance, not a type. `Ref[SEQUENCE_ARTIFACT_TYPE]` does not work. Generic ports use a marker:

```python
@dataclass(frozen=True, slots=True)
class Binds:
    variable: str

@dataclass(frozen=True, slots=True)
class Plugs:
    variadic: bool = False
    instance: bool = False
    spare: bool = False
    agent_default: Literal["fill", "hidden"] = "fill"
```

`spare` requires `instance`. `instance` requires `variadic`. Same errors `InPort.__post_init__` raises today, with the word `Plugs`.

A generic port is `Annotated[Ref[Any], Binds("T")]` or the `RefSequence` form. The field contains `Ref` or `RefSequence` and no concrete value class. Startup fails otherwise.

Collect's input is the one mixed case: `Annotated[list[Ref[Any] | RefSequence[Any]], Plugs(instance=True, spare=True), Binds("T")]`.

## Derivation

`derive_input_contract` and `derive_output_contract` in `libs/core/src/grafy_core/node_derivation.py` stop looking for `InPort` and `OutPort`.

A field is a port when, after unwrapping `Annotated` and `X | None`, the remaining type is one of:

- a declared value class, or `StrictStr` or `StrictInt`
- a union of declared value classes
- `Ref[...]` or `RefSequence[...]`
- `list` of one of those, which is shape `MANY`
- `list[Ref[Any] | RefSequence[Any]]` together with `Plugs(instance=True)`, which preserves the ref container and accepts shapes `ONE` and `MANY`

Anything else is config-shaped data on the model and is not a port. A union that mixes a value class with `Ref` fails registration. A union that includes `ArtifactRef` or `ArtifactRefSequence` directly, rather than `Ref` or `RefSequence`, fails registration with a message that names `Ref`.

`Plugs` may sit on any of these. Missing `Plugs` means not variadic, not instance plugs, no spare plugs, `agent_default="fill"`. `Binds` may sit on a `Ref` or `RefSequence` port and sets `accepts` to `ArtifactTypeVariable`. A concrete port with `Binds`, or a generic port without it, fails registration.

Union order is catalog order. The first member's key is `InputPortSpec.accepts`. The rest are `also_accepts`, in source order. Do not sort. A test snapshots every production port in the inventory, so reordering `RasterImage | PdfFile` to `PdfFile | RasterImage` fails.

`OutputPortSpec` records `value_type`. For a ref output it is `None` and `produces` is the variable or the concrete key. For a value output `produces` comes from the class and `value_type` is that class.

`_concrete_type` today rejects a union. It grows one branch: a union of declared classes returns the tuple, and `InputPortSpec.target_type` becomes `value_types: tuple[type, ...]`. Materialization of a union does not try members. It resolves by the ref's key, and the declaration's class must be one of `value_types`.

`callable_nodes.py` lines 64-76 map `str` and `int` by hand, and lines 214 and 256 wrap `InPort` and `OutPort`. Delete the wraps. A signature parameter becomes a port through the same derivation. `str` still means text, because that is the declaration. `JsonSchemaText` means JSON Schema. An annotation that resolves to nothing raises `NodeContractError` naming the parameter.

`shape_field` is removed from the markers. `InputPortSpec.shape_field` and `OutputPortSpec.shape_field` remain and are always `None`, so `PortResponse` stays valid. Delete the derivation branch that required `ArtifactRef | ArtifactRefSequence` for a config-chosen shape. No node uses it. Tests that set `shape_field` are deleted.

## Startup check

After `values` is built and nodes are registered, one pass over every node:

- For a value input, every accepted key is declared, and that declaration's `value_type` is in the port's `value_types`.
- For a value output, `produces` is declared and `value_type` is that declaration's class.
- Ref ports are skipped here. Their class is `Ref` or `RefSequence`, and the variable is bound later per instance.
- Service ports do not exist yet. When C adds them, this pass skips a port whose class is a service contract.

Failure is `PluginRegistrationError` naming the operator id, the port name, and the key.

## Port inventory

Every production port. "Body" says what the third commit changes inside `run`. "Drop marker" means the annotation already is the value class. Delete `InPort` or `OutPort` and leave the class.

Sequence family, `libs/workbench/src/grafy_workbench/sequence/nodes.py`. The variable name stays `"T"`.

| Node | Field | Today | After | Body |
| --- | --- | --- | --- | --- |
| `sequence.collect` | `items` in | `list[ArtifactRef \| ArtifactRefSequence]`, plugs, variable T | `list[Ref[Any] \| RefSequence[Any]]`, `Plugs(instance=True, spare=True)`, `Binds("T")` | still reads `.key()` and `.item_refs` |
| `sequence.collect` | `items` out | `ArtifactRefSequence`, variable T | `RefSequence[Any]`, `Binds("T")` | still builds `ArtifactRefSequence(...)`. Return `RefSequence` validated from that payload |
| `sequence.count` | `items` | `ArtifactRefSequence`, variable T | `RefSequence[Any]`, `Binds("T")` | `len(inputs.items.item_refs)` stays |
| `sequence.count` | `count` | `StrictInt` | `StrictInt` | drop marker |
| `sequence.slice` | `items` in and out | `ArtifactRefSequence`, variable T | `RefSequence[Any]`, `Binds("T")` | still reads `ordered`, `item_refs`, `sequence_id` |
| `sequence.item_at` | `items` | `ArtifactRefSequence`, variable T | `RefSequence[Any]`, `Binds("T")` | unchanged |
| `sequence.item_at` | `item` | `ArtifactRef`, variable T | `Ref[Any]`, `Binds("T")` | still returns one ref |

Schema family, `libs/workbench/src/grafy_workbench/schema/nodes.py`.

| Node | Field | After | Body |
| --- | --- | --- | --- |
| `schema.builder` | `schemas` | `list[JsonSchemaText]`, `Plugs(instance=True)` | read `.value`. Variadic stays on, because instance plugs require it |
| `schema.builder` | `json_schema` | `JsonSchemaText` | return the model, not a bare str |

Text and integer.

| Node | Field | After | Body |
| --- | --- | --- | --- |
| `text.input` | `text` | `StrictStr` | drop marker |
| `value.integer` | `value` | `StrictInt` | drop marker |

Table plugin, `plugins/table/.../nodes.py`.

| Field | After | Body |
| --- | --- | --- |
| `file` | `CsvFile \| XlsxFile` | read the handle. Catalog order is CSV then XLSX, matching `also_accepts` today |
| `table` | `Table` | drop marker |

LLM prompt, `plugins/llm/.../prompt.py`.

| Field | After | Body |
| --- | --- | --- |
| `text` | `StrictStr` | drop marker |
| `images` | `RefSequence[RasterImage] \| None` | still requires `.ordered` and copies `.item_refs` into `PromptMessage`. This port keeps refs |
| `message` | `PromptMessage` | drop marker |

OpenAI-compatible, `plugins/llm/.../openai_compatible.py`.

| Field | After | Body |
| --- | --- | --- |
| `messages` | `list[PromptMessage]` | drop marker |
| `json_schema` | `JsonSchemaText \| None` | pass `.value` where the code reads the string |
| `completion` | `CompletionPayload` | drop marker |

Mistral OCR, `plugins/mistral/.../ocr.py`. The old node stays.

| Field | After | Body |
| --- | --- | --- |
| `document_url` | `str \| None`, `Plugs(agent_default="hidden")` | still a text port. Hidden stays, so an agent tool does not fill the URL |
| `image` | `RasterImage \| PdfFile \| None` | replace `_image_data_url`'s artifact load with `read`. Branch on `isinstance(..., PdfFile)`, not on `ref.key()` |
| `markdown`, `blocks`, `regions` | `MarkdownValue`, `Table`, `ImageRegionSet` | drop markers |

Reducto, `plugins/reducto/.../ocr.py`. Same image and output rows. `document_url` is `str \| None` with no `Plugs`. Reducto does not hide that input today. Do not add `hidden`.

GIS, `plugins/gis/.../nodes.py`.

| Node | Field | After | Body |
| --- | --- | --- | --- |
| features to table | `features` | `GeoFeatureCollection` | drop marker. The class is already the value |
| features to table | `table` | `Table` | drop marker |
| table to features | `table` | `Table` | drop marker |
| table to features | `features` | `GeoFeatureCollection` | drop marker |
| parse GeoJSON | `file` | `GeoJsonFile \| JsonFile` | read the handle. Order is GeoJSON then JSON |
| parse GeoJSON | `features` | `GeoFeatureCollection` | drop marker |
| raster import | `file` | `TiffFile` | `GeoRasterScanImportInput.file` is `ArtifactRef` with `InPort(TIFF_FILE)` today. `read` the handle |
| raster import | scan output | `GeoRasterScan` | drop marker |
| vector layer | `features` | `Ref[GeoFeatureCollection]` | still stored on `GeoFeatureArtifactSource.artifact` |
| vector layer | `layer` | `GeoMapLayer` | drop marker |
| raster layer | `raster` | `Ref[GeoRasterScan]` | still stored on `GeoRasterArtifactSource.artifact` |
| compose map | `layers` | `RefSequence[GeoMapLayer]` | still reads `.ordered` and `.item_refs` |
| compose map | `map` | `GeoMapDocument` | drop marker |
| wfs import | `features` | `GeoFeatureCollection` | drop marker. The body still returns the fetched collection |

Image plugin, `plugins/image/.../nodes.py`. Output class becomes `RasterImage`. Delete `RasterImageContent`.

| Node | Field | After | Body |
| --- | --- | --- | --- |
| draw | `image` | `RasterImage` | `read` instead of `load_file_artifact` |
| draw | `regions` | `ImageRegionSet` | drop marker |
| draw | `image` out | `RasterImage` | `from_content` |
| crop | `image` | `RasterImage` | `read` |
| crop | `regions` | `ImageRegionSet` | drop marker |
| crop | `crops` | `list[RasterImage]` | `from_content` |

If a node not in this table has an `InPort` or `OutPort`, stop. Tests and `tests/support/scenarios/` are updated with the production code, not treated as extra product nodes.

## Conversions in this issue

They still write an artifact. F removes that.

`Conversion` replaces `ArtifactConversion` for the canonical tuple.

```python
@dataclass(frozen=True, slots=True)
class Conversion[S, T]:
    id: str
    version: int
    title: str
    source: Artifact[S]
    target: Artifact[T]
    convert: Callable[[S], Awaitable[T]]
```

The seven canonical conversions keep their ids and version 1. Image ones take the file subclass, verify with PIL the way `canonical_conversions.py` does now, and return `RasterImage.from_content`. Text file to text reads the handle and decodes as the current function does. Integer to text stays a pure function of `int` and returns `str`.

`convert` is async because a handle read is async. Update `CONTEXT.md` where it calls conversions pure callables.

Delete `source_type`, `target_type`, and `conversion_runtime_types_are_compatible`. The two `Artifact` objects are the compatibility proof. Delete `Plugin.register_artifact_conversion` and the list it stores. Nothing reads it. Catalog and the binder keep reading the canonical tuple. `ArtifactConversionSpecResponse.from_conversion` reads `conversion.source.spec.key` and `conversion.target.spec.key`.

Correct the module docstring that claims a snapshot test forces a version bump.

## Deletes, in the last commit

Do not leave the fallback in place.

- `Resolver`, `ResolverRegistry`, `InlineModelResolver`
- `ArtifactOutputWriter`, `ArtifactWriterRegistry`, `InlineModelOutputWriter`
- `grafy_workbench/scalar_persistence.py`
- `register_resolver`, `register_writer`, `register_artifact_conversion`, `build_resolvers`, `build_writers`
- the first-one-wins writer loops
- `FileBytesResolver` and its six registrations
- Mistral and Reducto foreign writers
- `RasterImageContent`
- `InPort`, `OutPort`
- `_validated_conversion_value` in `apps/api/src/grafy_api/runs/edge_values.py` once `Conversion` returns the value class directly

`Plugin.register(Artifact)` stays, and it stores the declaration rather than two factories.

## Commits

Each commit is green on the commands at the bottom before the next one starts.

1. `feat(core): declare inline artifact values once`. Add `ArtifactValues`, `inline_model_artifact`, and the scalar helper. Register the inline and scalar rows, including `JsonSchemaText`. Materializer and persister use `values` when the key is declared and the old registry otherwise. Delete the Mistral and Reducto writers. A duplicate declaration raises. Tests that construct those foreign writers are updated.

2. `feat(core): declare file, raster, table and gis values`. Add `documents.py`, the file subclasses, `RasterImage`, and move the table and GIS bodies. Delete `FileBytesResolver` and the external raster writer registration. Inject `GdalCli` through the factory. Image, table and GIS tests that built a writer by hand build a declaration instead.

3. `feat(core): infer node ports from value classes`. Derivation change, inventory migration, `callable_nodes.py`, startup check, delete `InPort` and `OutPort`. Update `tests/unit/core/test_node_contracts.py` and `tests/unit/core/test_invocation.py` in this commit. Node bodies listed above change here, because the field types change here.

4. `feat(core): type canonical conversions by declaration`. `Conversion`, catalog adapter, docstring, delete the dead plugin conversion API and the old registries' remaining branch. After this commit the fallback is gone.

## Tests

- Write then resolve, through the in-memory unit of work, for each moved type. Inline JSON round-trips. A scalar round-trips as the unwrapped Python value and stores `{"value": ...}`. A raster round-trips bytes, content type and filename. A table round-trip still reads chunks.
- A second declaration of `text.markdown@1` raises at startup.
- Writing a `MarkdownValue` to `scalar.text@1` raises `TypeError` before storage is called.
- `schema.builder` input derives JSON Schema, with instance plugs, and does not derive text.
- `MistralOcrInput.image` derives `image.raster@1` then `file.pdf@1`. Swapping the union members fails the snapshot.
- `document_url` derives text and `agent_default="hidden"`. Reducto's URL derives text and the default fill.
- Collect derives variable `T`, instance plugs, spare plugs, and preserved ref containers.
- A `BlobFile` port whose declaration was swapped to `PngFile` fails the startup pass.
- `read(max_bytes=n)` does not call storage when `byte_size > n`.
- Existing `tests/unit/runs/test_node_runner.py` passes. MAP still receives refs.

## Surfaces

OpenAPI does not change. `npm --prefix apps/web run check:api` is clean. Node `input_schema` JSON does change where a field class changes, and the Python client compares that schema with the catalog built from the same class, so the two sides move together. Update snapshot tests of those schemas. Do not add a JSON schema hook that pretends a handle is an `ArtifactRef`.

`docs/design/plugin-development.md` and the Plugin entry in `CONTEXT.md` describe resolver and writer factories. Rewrite those paragraphs in commit 4.

Web code reads port keys from the catalog, not the pydantic property schema. It does not need an edit in G. If a web test snapshots a node input schema, update the snapshot.

## Finish commands

```sh
uv run ruff check libs apps plugins tests
uv run ruff format --check libs apps plugins tests
uv run pyright
uv run pytest -q tests/unit/core tests/unit/runs tests/unit/plugins tests/unit/client tests/unit/api/services/test_composition.py libs/workbench/tests plugins/gis/tests plugins/image/tests plugins/llm/tests plugins/mistral/tests plugins/table/tests plugins/reducto/tests
npm --prefix apps/web run check:api
```

`uv run pyright` is the repo typechecker (`pyright` is a root dependency). The web check is part of done. G does not regenerate the client.

## Assumption

ASSUMPTION: gis.wfs.import output `features` is a value port of GeoFeatureCollection, same as table-to-features `features`. Drop the OutPort marker. The body stays `return WfsImportOutput(features=features)` where features is the fetched GeoFeatureCollection. It is not Ref[GeoFeatureCollection], because the node returns the collection itself and does not store an artifact ref on the output. Alternative rejected: treating it as a stored Ref, which would change the body and does not match the current return.

`gis.map.wms_layer` returns the shared `MapLayerOutput.layer` port. The vector-layer and raster-layer rows already name that field. It is not a second gap.
