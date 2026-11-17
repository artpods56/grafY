"""The Sequence family: ordered artifact reference containers."""

from typing import Annotated, Any

from pydantic import Field, StrictInt

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
    Binds,
    Plugs,
    Ref,
    RefSequence,
    UserFacingNodeError,
)
from grafy_core.plugins import NodeCachePolicy

import grafy_workbench.value.nodes as _value_nodes
from grafy_workbench.sequence.declaration import SEQUENCES

_ = _value_nodes.__name__  # notes int before these ports


class CollectInput(NodeInput):
    items: Annotated[
        list[Ref[Any] | RefSequence[Any]],
        Plugs(variadic=True, instance=True, spare=True),
        Binds("T"),
        Field(
            min_length=1,
            title="Documents",
            description="Pages or files, in the order you add them.",
        ),
    ]


class CollectOutput(NodeOutput):
    items: Annotated[
        RefSequence[Any],
        Binds("T"),
        Field(
            title="List",
            description="Everything above, as one list.",
        ),
    ]


@SEQUENCES.function_node(
    operator_id="sequence.collect",
    version=1,
    title="Group into a list",
    cache_policy=NodeCachePolicy.EXACT,
)
async def collect(
    _config: NoConfig,
    inputs: CollectInput,
) -> CollectOutput:
    """Keeps pages or files together, in the order you add them. Every item has to be the same kind of thing."""
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
                "Every item in the group has to be the same kind. Item "
                f"{input_index + 1} does not match the first item."
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
        items=RefSequence[Any].model_validate(
            ArtifactRefSequence(
                artifact_type=artifact_type.id,
                schema_version=artifact_type.schema_version,
                item_refs=item_refs,
                ordered=ordered,
                metadata={"collect_segments": collect_segments},
            )
        )
    )


CollectNode = SEQUENCES.nodes[-1].node_class


class CountInput(NodeInput):
    items: Annotated[
        RefSequence[Any],
        Binds("T"),
        Field(title="List", description="The list to count."),
    ]


class CountOutput(NodeOutput):
    count: Annotated[
        StrictInt,
        Field(
            title="How many",
            description="How many items are in the list.",
        ),
    ]


@SEQUENCES.function_node(
    operator_id="sequence.count",
    version=1,
    title="Count items",
    cache_policy=NodeCachePolicy.EXACT,
)
async def count(_config: NoConfig, inputs: CountInput) -> CountOutput:
    """Counts how many items are in a list."""
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
        RefSequence[Any],
        Binds("T"),
        Field(title="List", description="The list to take a range from."),
    ]


class SliceOutput(NodeOutput):
    items: Annotated[
        RefSequence[Any],
        Binds("T"),
        Field(title="List", description="The items you kept."),
    ]


@SEQUENCES.function_node(
    operator_id="sequence.slice",
    version=1,
    title="Take a range",
    cache_policy=NodeCachePolicy.EXACT,
)
async def slice_sequence(config: SliceConfig, inputs: SliceInput) -> SliceOutput:
    """Keeps a stretch of items from a list. The first item is number 0."""
    source = inputs.items
    if not source.ordered:
        raise UserFacingNodeError(
            "This list has no order, so a range cannot be taken from it."
        )

    stop = None if config.count is None else config.start + config.count
    return SliceOutput(
        items=RefSequence[Any].model_validate(
            ArtifactRefSequence(
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
        RefSequence[Any],
        Binds("T"),
        Field(title="List", description="The list to pick from."),
    ]


class ItemAtOutput(NodeOutput):
    item: Annotated[
        Ref[Any],
        Binds("T"),
        Field(
            title="Item",
            description="The one item at that position.",
        ),
    ]


@SEQUENCES.function_node(
    operator_id="sequence.item_at",
    version=1,
    title="Pick one",
    cache_policy=NodeCachePolicy.EXACT,
)
async def item_at(config: ItemAtConfig, inputs: ItemAtInput) -> ItemAtOutput:
    """Picks one item from a list. The first item is number 0."""
    source = inputs.items
    if not source.ordered:
        raise UserFacingNodeError(
            "This list has no order, so one item cannot be picked by position."
        )

    length = len(source.item_refs)
    if config.index >= length:
        raise UserFacingNodeError(
            f"There is no item at position {config.index}. This list has "
            f"{length} items, and 0 is the first."
        )
    return ItemAtOutput(item=Ref[Any].model_validate(source.item_refs[config.index]))


ItemAtNode = SEQUENCES.nodes[-1].node_class
