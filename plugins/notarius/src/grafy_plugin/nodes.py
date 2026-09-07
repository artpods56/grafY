from ipaddress import ip_address
from typing import Annotated, cast, final, override

from pydantic import (
    AnyHttpUrl,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactRefSequence,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
)
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.schema_contracts import JSON_SCHEMA, parse_json_schema
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableColumn,
    TableValue,
    TableValueType,
)

from grafy_plugin.artifacts import (
    STRUCTURED_EXTRACTION_DATASET,
    StructuredExtractionDataset,
)
from grafy_plugin.declaration import PLUGIN
from grafy_plugin.processing import (
    ContextStrategySelection,
    DatasetProcessor,
    FullHistoryStrategy,
    IndependentStrategy,
    ItemProcessingError,
    ItemProcessor,
    MessageBuilder,
    PredictionDataItem,
    ProviderSettings,
    SlidingWindowStrategy,
    StructuredCompletionProvider,
    extraction_items,
)
from grafy_plugin.provider import (
    ImageSourceReader,
    OpenAICompatibleStructuredProvider,
    RasterArtifactReader,
    StructuredExtractionProviderError,
)


class StructuredDatasetExtractionConfig(NodeConfig):
    model_config = ConfigDict(extra="forbid")

    base_url: StrictStr = Field(
        default="https://api.openai.com/v1",
        min_length=1,
        description="OpenAI-compatible API base URL including the version path.",
    )
    model: StrictStr = Field(
        default="gpt-4.1-mini",
        min_length=1,
        description="Provider model identifier.",
    )
    context_strategy: ContextStrategySelection = Field(
        default=ContextStrategySelection.SLIDING_WINDOW,
        description="Conversation history policy across ordered images.",
    )
    window_size: StrictInt = Field(
        default=5,
        ge=1,
        le=100,
        description="Recent user/assistant exchanges retained by sliding window.",
    )
    max_concurrent: StrictInt = Field(
        default=5,
        ge=1,
        le=100,
        description="Concurrent requests used only for independent extraction.",
    )
    lookahead_images: StrictBool = Field(
        default=True,
        description="Attach the next image as read-only continuation lookahead.",
    )
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_completion_tokens: StrictInt = Field(default=8_192, ge=1, le=1_000_000)
    timeout_ms: StrictInt = Field(default=120_000, ge=1_000, le=900_000)
    max_retries: StrictInt = Field(
        default=0,
        ge=0,
        le=5,
        description=(
            "Extra provider attempts after a failure, including invalid JSON. "
            "A page that still fails is recorded and the dataset continues."
        ),
    )
    schema_name: StrictStr = Field(
        default="structured_extraction",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    strict: StrictBool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("base_url must not have surrounding whitespace")
        url = TypeAdapter(AnyHttpUrl).validate_python(value)
        if url.username is not None or url.password is not None:
            raise ValueError("base_url must not include user information")
        if url.query is not None or url.fragment is not None:
            raise ValueError("base_url must not include a query or fragment")
        host = url.host
        if host is None:
            raise ValueError("base_url must include a host")
        if url.scheme == "http":
            normalized_host = host[1:-1] if host.startswith("[") else host
            is_loopback = normalized_host == "localhost"
            if not is_loopback:
                try:
                    is_loopback = ip_address(normalized_host).is_loopback
                except ValueError:
                    is_loopback = False
            if not is_loopback:
                raise ValueError("base_url must use HTTPS unless it targets loopback")
        return str(url).rstrip("/")


class StructuredDatasetExtractionInput(NodeInput):
    model_config = ConfigDict(extra="forbid")

    images: Annotated[
        ArtifactRefSequence,
        InPort(RASTER_IMAGE),
        Field(description="Non-empty ordered raster image sequence."),
    ]
    system_prompt: Annotated[
        StrictStr,
        InPort(TEXT_VALUE),
        Field(min_length=1, description="System-level extraction rules."),
    ]
    instruction: Annotated[
        StrictStr,
        InPort(TEXT_VALUE),
        Field(min_length=1, description="Task instruction repeated for each image."),
    ]
    json_schema: Annotated[
        StrictStr,
        InPort(JSON_SCHEMA),
        Field(min_length=1, description="Runtime structured-output JSON Schema."),
    ]

    @model_validator(mode="after")
    def validate_images(self) -> "StructuredDatasetExtractionInput":
        if not self.images.ordered:
            raise ValueError("Structured extraction requires an ordered image sequence")
        if not self.images.item_refs:
            raise ValueError("Structured extraction requires at least one image")
        return self


class StructuredDatasetExtractionOutput(NodeOutput):
    model_config = ConfigDict(extra="forbid")

    dataset: Annotated[
        StructuredExtractionDataset,
        OutPort(STRUCTURED_EXTRACTION_DATASET),
        Field(description="Validated structured output for every source image."),
    ]


def build_structured_dataset_extraction_node(
    context: PluginRuntimeContext,
) -> "StructuredDatasetExtractionNode":
    image_reader = RasterArtifactReader(uow=context.uow, storage=context.storage)
    return StructuredDatasetExtractionNode(
        provider=OpenAICompatibleStructuredProvider(image_reader=image_reader),
        image_reader=image_reader,
        node_secrets=context.node_secrets,
    )


@PLUGIN.node(
    operator_id="notarius.dataset.extract_structured",
    version=1,
    title="Extract structured image dataset",
    factory=build_structured_dataset_extraction_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            title="API key",
            description="Write-only bearer credential for the configured endpoint.",
            config_dependencies=("base_url",),
        ),
    ),
    http_egress=NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="base_url"),),
    ),
    cache_policy=NodeCachePolicy.NEVER,
)
@final
class StructuredDatasetExtractionNode(
    Node[
        StructuredDatasetExtractionConfig,
        StructuredDatasetExtractionInput,
        StructuredDatasetExtractionOutput,
    ]
):
    """Extracts ordered images with managed history and next-image lookahead."""

    def __init__(
        self,
        *,
        provider: StructuredCompletionProvider,
        image_reader: ImageSourceReader,
        node_secrets: NodeSecretResolverPort,
    ) -> None:
        self._provider = provider
        self._image_reader = image_reader
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: StructuredDatasetExtractionConfig,
        inputs: StructuredDatasetExtractionInput,
        /,
    ) -> StructuredDatasetExtractionOutput:
        parse_json_schema(inputs.json_schema, context="structured extraction input")
        try:
            api_key = await self._node_secrets.resolve_secret(
                workspace_id=context.workspace_id,
                graph_id=context.secret_graph_id,
                graph_revision=context.secret_graph_revision,
                node_id=context.node_id,
                name="api_key",
                dependencies={"base_url": config.base_url},
            )
        except Exception as exc:
            raise UserFacingNodeError(
                "Structured extraction could not resolve its API key for "
                f"node {context.node_id!r} and base URL {config.base_url!r}"
            ) from exc

        items: list[PredictionDataItem] = []
        for index, image_ref in enumerate(inputs.images.item_refs):
            try:
                filename = await self._image_reader.filename(
                    image_ref,
                    workspace_id=context.workspace_id,
                )
            except StructuredExtractionProviderError as exc:
                raise UserFacingNodeError(str(exc)) from exc
            items.append(
                PredictionDataItem(
                    index=index,
                    image_ref=image_ref,
                    filename=filename,
                )
            )

        if config.context_strategy is ContextStrategySelection.INDEPENDENT:
            strategy = IndependentStrategy()
        elif config.context_strategy is ContextStrategySelection.FULL_HISTORY:
            strategy = FullHistoryStrategy()
        else:
            strategy = SlidingWindowStrategy(window_size=config.window_size)

        processor = DatasetProcessor(
            item_processor=ItemProcessor(
                provider=self._provider,
                json_schema=inputs.json_schema,
                settings=ProviderSettings(
                    base_url=config.base_url,
                    model=config.model,
                    temperature=config.temperature,
                    max_completion_tokens=config.max_completion_tokens,
                    timeout_ms=config.timeout_ms,
                    max_retries=config.max_retries,
                    schema_name=config.schema_name,
                    strict=config.strict,
                ),
                api_key=api_key,
                workspace_id=context.workspace_id,
            ),
            message_builder=MessageBuilder(
                system_prompt=inputs.system_prompt,
                instruction=inputs.instruction,
            ),
            context_strategy=strategy,
            include_lookahead=config.lookahead_images,
            progress=context.progress,
        )
        try:
            if config.context_strategy is ContextStrategySelection.INDEPENDENT:
                processed_items = await processor.process_parallel_async(
                    items,
                    max_concurrent=config.max_concurrent,
                )
            else:
                processed_items = await processor.process_sequence_async(items)
        except ItemProcessingError as exc:
            raise UserFacingNodeError(str(exc)) from exc
        except Exception as exc:
            raise UserFacingNodeError(
                "Structured dataset extraction failed; inspect the active item "
                "progress and provider configuration"
            ) from exc

        return StructuredDatasetExtractionOutput(
            dataset=StructuredExtractionDataset(
                json_schema=inputs.json_schema,
                context_strategy=config.context_strategy.value,
                lookahead_images=config.lookahead_images,
                items=extraction_items(processed_items),
            )
        )


class ExtractionToTableConfig(NodeConfig):
    model_config = ConfigDict(extra="forbid")

    rows_field: StrictStr | None = Field(
        default=None,
        min_length=1,
        description=(
            "Optional top-level array-of-objects field. When omitted, the node "
            "uses the schema's only such field or emits one row per image."
        ),
    )


class ExtractionToTableInput(NodeInput):
    model_config = ConfigDict(extra="forbid")

    dataset: Annotated[
        StructuredExtractionDataset,
        InPort(STRUCTURED_EXTRACTION_DATASET),
    ]


class ExtractionToTableOutput(NodeOutput):
    model_config = ConfigDict(extra="forbid")

    table: Annotated[Table, OutPort(TABLE_DATA)]


def _array_object_fields(schema: dict[str, object]) -> list[str]:
    raw_properties = schema.get("properties")
    if not isinstance(raw_properties, dict):
        return []
    properties = cast(dict[object, object], raw_properties)
    fields: list[str] = []
    for name, raw_definition in properties.items():
        if not isinstance(name, str) or not isinstance(raw_definition, dict):
            continue
        definition = cast(dict[object, object], raw_definition)
        items = definition.get("items")
        if definition.get("type") == "array" and isinstance(items, dict):
            item_definition = cast(dict[object, object], items)
            if item_definition.get("type") == "object":
                fields.append(name)
    return fields


def _value_type(values: list[TableValue]) -> TableValueType:
    observed: set[TableValueType] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            observed.add(TableValueType.BOOLEAN)
        elif isinstance(value, int):
            observed.add(TableValueType.INTEGER)
        elif isinstance(value, float):
            observed.add(TableValueType.NUMBER)
        elif isinstance(value, str):
            observed.add(TableValueType.TEXT)
        else:
            observed.add(TableValueType.JSON)
    if not observed:
        return TableValueType.UNKNOWN
    if observed <= {TableValueType.INTEGER, TableValueType.NUMBER}:
        return (
            TableValueType.INTEGER
            if observed == {TableValueType.INTEGER}
            else TableValueType.NUMBER
        )
    return next(iter(observed)) if len(observed) == 1 else TableValueType.MIXED


@PLUGIN.function_node(
    operator_id="notarius.dataset.to_table",
    version=1,
    title="Extraction dataset to table",
    cache_policy=NodeCachePolicy.EXACT,
)
async def extraction_to_table(
    config: ExtractionToTableConfig,
    inputs: ExtractionToTableInput,
) -> ExtractionToTableOutput:
    """Flattens validated extraction objects into a downloadable table."""
    schema = parse_json_schema(
        inputs.dataset.json_schema,
        context="extraction dataset",
    )
    candidate_fields = _array_object_fields(schema)
    rows_field = config.rows_field
    if rows_field is None and len(candidate_fields) == 1:
        rows_field = candidate_fields[0]
    elif rows_field is None and len(candidate_fields) > 1:
        candidates = ", ".join(repr(field) for field in candidate_fields)
        raise UserFacingNodeError(
            "Extraction schema contains multiple arrays of objects; select "
            f"rows_field from: {candidates}"
        )
    if rows_field is not None and rows_field not in candidate_fields:
        candidates = ", ".join(repr(field) for field in candidate_fields) or "none"
        raise UserFacingNodeError(
            f"rows_field {rows_field!r} is not an array of objects in the "
            f"extraction schema; available fields: {candidates}"
        )

    metadata_columns = [
        "source_index",
        "source_filename",
        "source_image_id",
    ]
    extracted_rows: list[dict[str, TableValue]] = []
    value_column_order: list[str] = []
    for item in inputs.dataset.items:
        if rows_field is None:
            source_rows: list[JsonObject] = [item.structured_value]
        else:
            raw_rows = item.structured_value.get(rows_field)
            if not isinstance(raw_rows, list):
                raise UserFacingNodeError(
                    f"Item {item.source_index} field {rows_field!r} is not a list"
                )
            source_rows = []
            for row_index, raw_row in enumerate(cast(list[object], raw_rows)):
                if not isinstance(raw_row, dict):
                    raise UserFacingNodeError(
                        f"Item {item.source_index} field {rows_field!r} row "
                        f"{row_index} is not an object"
                    )
                source_rows.append(cast(JsonObject, raw_row))

        for source_row in source_rows:
            collisions = set(metadata_columns) & set(source_row)
            if collisions:
                rendered = ", ".join(sorted(collisions))
                raise UserFacingNodeError(
                    f"Extracted row uses reserved source columns: {rendered}"
                )
            for key in source_row:
                if key not in value_column_order:
                    value_column_order.append(key)
            extracted_rows.append(
                {
                    "source_index": item.source_index,
                    "source_filename": item.source_filename,
                    "source_image_id": str(item.source_image_id),
                    **cast(dict[str, TableValue], source_row),
                }
            )

    column_ids = [*metadata_columns, *value_column_order]
    normalized_rows = [
        {column_id: row.get(column_id) for column_id in column_ids}
        for row in extracted_rows
    ]
    columns = [
        TableColumn(
            id=column_id,
            title=column_id.replace("_", " ").title(),
            value_type=_value_type([row[column_id] for row in normalized_rows]),
        )
        for column_id in column_ids
    ]
    return ExtractionToTableOutput(
        table=Table(columns=columns, rows=normalized_rows)
    )


ExtractionToTableNode = PLUGIN.nodes[-1].node_class


__all__ = [
    "ExtractionToTableConfig",
    "ExtractionToTableInput",
    "ExtractionToTableNode",
    "ExtractionToTableOutput",
    "StructuredDatasetExtractionConfig",
    "StructuredDatasetExtractionInput",
    "StructuredDatasetExtractionNode",
    "StructuredDatasetExtractionOutput",
]
