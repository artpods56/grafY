from typing import Annotated

from pydantic import Field, StrictInt

from grafy_core.artifact_contracts import INTEGER_VALUE
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InPort,
    OutPort,
    UserFacingNodeError,
)
from grafy_core.plugins import NodeCachePolicy

from grafy_core.plugins import Plugin


SEQUENCES = Plugin(slug="test.sequence", title="Sequence fixtures")
SEQUENCES.register_artifact_type_dependency(INTEGER_VALUE)


SEQUENCE_ARTIFACT_TYPE = ArtifactTypeVariable("T")


class CollectInput(NodeInput):
    items: Annotated[
        list[ArtifactRef | ArtifactRefSequence],
        InPort(
            SEQUENCE_ARTIFACT_TYPE,
            variadic=True,
            instance_plugs=True,
        ),
        Field(
            min_length=1,
            description="Artifacts and sequences in connection order.",
        ),
    ]


class CollectOutput(NodeOutput):
    items: Annotated[
        ArtifactRefSequence,
        OutPort(SEQUENCE_ARTIFACT_TYPE),
        Field(description="One sequence containing every input artifact."),
    ]


@SEQUENCES.function_node(
    operator_id="test.sequence.collect",
    version=1,
    title="Collect",
    cache_policy=NodeCachePolicy.EXACT,
)
async def collect(
    _config: NoConfig,
    inputs: CollectInput,
) -> CollectOutput:
    """Collects homogeneous artifact refs without rewriting their payloads."""
    first = inputs.items[0]
    if isinstance(first, ArtifactRef):
        artifact_type = first.key()
    else:
        artifact_type = ArtifactTypeKey(
            first.artifact_type,
            first.schema_version,
        )

    item_refs: list[ArtifactRef] = []
    collect_segments: list[JsonObject] = []
    ordered = True
    for input_index, source in enumerate(inputs.items):
        if isinstance(source, ArtifactRef):
            source_type = source.key()
        else:
            source_type = ArtifactTypeKey(
                source.artifact_type,
                source.schema_version,
            )
        if source_type != artifact_type:
            raise UserFacingNodeError(
                "Collect inputs must share one artifact type; expected "
                f"{artifact_type.id}@{artifact_type.schema_version}, got "
                f"{source_type.id}@{source_type.schema_version} at input "
                f"{input_index}"
            )

        start_index = len(item_refs)
        if isinstance(source, ArtifactRef):
            item_refs.append(source)
            item_count = 1
            source_kind = "single"
        else:
            item_refs.extend(source.item_refs)
            item_count = len(source.item_refs)
            source_kind = "sequence"
            if not source.ordered:
                ordered = False
        collect_segments.append(
            {
                "input_index": input_index,
                "start_index": start_index,
                "item_count": item_count,
                "source_kind": source_kind,
            }
        )

    return CollectOutput(
        items=ArtifactRefSequence(
            artifact_type=artifact_type.id,
            schema_version=artifact_type.schema_version,
            item_refs=item_refs,
            ordered=ordered,
            metadata={"collect_segments": collect_segments},
        )
    )


CollectNode = SEQUENCES.nodes[-1].node_class


class CountInput(NodeInput):
    items: Annotated[
        ArtifactRefSequence,
        InPort(SEQUENCE_ARTIFACT_TYPE),
        Field(description="Sequence whose items are counted."),
    ]


class CountOutput(NodeOutput):
    count: Annotated[
        StrictInt,
        OutPort(INTEGER_VALUE),
        Field(description="Number of items in the sequence."),
    ]


@SEQUENCES.function_node(
    operator_id="test.sequence.count",
    version=1,
    title="Count",
    cache_policy=NodeCachePolicy.EXACT,
)
async def count(_config: NoConfig, inputs: CountInput) -> CountOutput:
    """Counts the refs in an artifact sequence."""
    return CountOutput(count=len(inputs.items.item_refs))


CountNode = SEQUENCES.nodes[-1].node_class


class SliceConfig(NodeConfig):
    start: StrictInt = Field(
        default=0,
        ge=0,
        description="Zero-based index of the first item to include.",
    )
    count: StrictInt | None = Field(
        default=None,
        ge=0,
        description="Maximum number of items to include.",
    )


class SliceInput(NodeInput):
    items: Annotated[
        ArtifactRefSequence,
        InPort(SEQUENCE_ARTIFACT_TYPE),
        Field(description="Ordered sequence to slice."),
    ]


class SliceOutput(NodeOutput):
    items: Annotated[
        ArtifactRefSequence,
        OutPort(SEQUENCE_ARTIFACT_TYPE),
        Field(description="Selected contiguous items."),
    ]


@SEQUENCES.function_node(
    operator_id="test.sequence.slice",
    version=1,
    title="Slice",
    cache_policy=NodeCachePolicy.EXACT,
)
async def slice_sequence(config: SliceConfig, inputs: SliceInput) -> SliceOutput:
    """Selects a contiguous range from an ordered artifact sequence."""
    source = inputs.items
    if not source.ordered:
        raise UserFacingNodeError(
            f"Cannot slice unordered sequence {source.sequence_id}"
        )

    stop = None if config.count is None else config.start + config.count
    return SliceOutput(
        items=ArtifactRefSequence(
            artifact_type=source.artifact_type,
            schema_version=source.schema_version,
            item_refs=source.item_refs[config.start : stop],
            ordered=True,
            index_key=source.index_key,
            metadata={
                "source_sequence_id": str(source.sequence_id),
                "start": config.start,
                "count": config.count,
            },
        )
    )


SliceNode = SEQUENCES.nodes[-1].node_class


class ItemAtConfig(NodeConfig):
    index: StrictInt = Field(
        default=0,
        ge=0,
        description="Zero-based index of the item to pick.",
    )


class ItemAtInput(NodeInput):
    items: Annotated[
        ArtifactRefSequence,
        InPort(SEQUENCE_ARTIFACT_TYPE),
        Field(description="Ordered sequence containing the item."),
    ]


class ItemAtOutput(NodeOutput):
    item: Annotated[
        ArtifactRef,
        OutPort(SEQUENCE_ARTIFACT_TYPE),
        Field(description="Artifact ref at the configured index."),
    ]


@SEQUENCES.function_node(
    operator_id="test.sequence.item_at",
    version=1,
    title="Pick item",
    cache_policy=NodeCachePolicy.EXACT,
)
async def item_at(config: ItemAtConfig, inputs: ItemAtInput) -> ItemAtOutput:
    """Picks one artifact ref from an ordered artifact sequence."""
    source = inputs.items
    if not source.ordered:
        raise UserFacingNodeError(
            f"Cannot pick an item from unordered sequence {source.sequence_id}"
        )

    length = len(source.item_refs)
    if config.index >= length:
        raise UserFacingNodeError(
            f"Cannot pick index {config.index} from sequence "
            f"{source.sequence_id} with length {length}"
        )
    return ItemAtOutput(item=source.item_refs[config.index])


ItemAtNode = SEQUENCES.nodes[-1].node_class
