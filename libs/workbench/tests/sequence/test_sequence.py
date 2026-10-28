from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    NoConfig,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    NodeContractResolutionError,
    NodeExecutionContext,
    PortShape,
)
from grafy_core.artifact_contracts import INTEGER_VALUE
from grafy_workbench.sequence.nodes import (
    SEQUENCES,
    CollectNode,
    CountInput,
    CountNode,
    ItemAtConfig,
    ItemAtNode,
    SliceConfig,
    SliceNode,
)
from grafy_core.plugins import PluginRegistry
from grafy_core.runtime.execution import NodeRunError, NodeRuntime
from grafy_core.runtime.materialization import (
    InputMaterializer,
    MaterializationError,
)
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.resolvers import ResolverRegistry


TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


VALUE_TYPE = ArtifactTypeKey("example.value", 1)
OTHER_TYPE = ArtifactTypeKey("example.other", 1)


def _runtime() -> NodeRuntime:
    return NodeRuntime(
        materializer=InputMaterializer(ResolverRegistry()),
        persister=OutputPersister(ArtifactWriterRegistry()),
    )


def test_collect_declares_one_homogeneous_generic_contract() -> None:
    input_port = CollectNode.input_contract.ports["items"]
    output_port = CollectNode.output_contract.ports["items"]

    assert isinstance(input_port.accepts, ArtifactTypeVariable)
    assert input_port.accepts.name == "T"
    assert output_port.produces is input_port.accepts
    assert input_port.accepted_shapes == (PortShape.ONE, PortShape.MANY)
    assert input_port.variadic is True
    assert input_port.instance_plugs is True
    assert output_port.shape is PortShape.MANY


def test_sequence_nodes_declare_generic_ref_container_contracts() -> None:
    collected_type = CollectNode.input_contract.ports["items"].accepts
    count_input = CountNode.input_contract.ports["items"]
    count_output = CountNode.output_contract.ports["count"]
    slice_input = SliceNode.input_contract.ports["items"]
    slice_output = SliceNode.output_contract.ports["items"]
    item_at_input = ItemAtNode.input_contract.ports["items"]
    item_at_output = ItemAtNode.output_contract.ports["item"]

    assert count_input.accepts is collected_type
    assert count_input.shape is PortShape.MANY
    assert count_output.produces == INTEGER_VALUE.key
    assert count_output.shape is PortShape.ONE
    assert slice_input.accepts is collected_type
    assert slice_input.shape is PortShape.MANY
    assert slice_output.produces is collected_type
    assert slice_output.shape is PortShape.MANY
    assert item_at_input.accepts is collected_type
    assert item_at_input.shape is PortShape.MANY
    assert item_at_output.produces is collected_type
    assert item_at_output.shape is PortShape.ONE


def test_sequence_plugin_registers_all_nodes_without_artifact_types() -> None:
    registry = PluginRegistry()
    registry.install(SEQUENCES)

    registry.freeze()

    assert SEQUENCES.slug == "sequence"
    assert SEQUENCES.title == "Sequence"
    assert SEQUENCES.artifact_types == ()
    sequence_registrations = [
        registration
        for registration in registry.nodes
        if registration.plugin_slug == SEQUENCES.slug
    ]
    assert [registration.key for registration in sequence_registrations] == [
        ("sequence.collect", 1),
        ("sequence.count", 1),
        ("sequence.slice", 1),
        ("sequence.item_at", 1),
    ]
    assert [registration.title for registration in sequence_registrations] == [
        "Collect",
        "Count",
        "Slice",
        "Pick item",
    ]


@pytest.mark.asyncio
async def test_collect_flattens_one_level_in_plug_order_and_preserves_refs() -> None:
    first_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)
    second_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)
    third_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)
    sequence = ArtifactRefSequence(
        artifact_type=VALUE_TYPE.id,
        schema_version=VALUE_TYPE.schema_version,
        item_refs=[second_ref, third_ref],
        ordered=False,
        index_key="source_index",
    )
    empty_sequence = ArtifactRefSequence.from_key(
        key=VALUE_TYPE,
        item_refs=[],
    )

    result = await _runtime().run_node(
        CollectNode(),
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="collect"),
        {"items": [first_ref, sequence, empty_sequence]},
        artifact_type_bindings={"T": VALUE_TYPE},
    )

    assert isinstance(result, PersistedNodeOutput)
    output = result["items"]
    assert isinstance(output, ArtifactRefSequence)
    assert output.artifact_type == VALUE_TYPE.id
    assert output.schema_version == VALUE_TYPE.schema_version
    assert output.item_refs == [first_ref, second_ref, third_ref]
    assert output.ordered is False
    assert output.metadata == {
        "collect_segments": [
            {
                "input_index": 0,
                "start_index": 0,
                "item_count": 1,
                "source_kind": "single",
            },
            {
                "input_index": 1,
                "start_index": 1,
                "item_count": 2,
                "source_kind": "sequence",
            },
            {
                "input_index": 2,
                "start_index": 3,
                "item_count": 0,
                "source_kind": "sequence",
            },
        ]
    }


@pytest.mark.asyncio
async def test_collect_derives_type_from_empty_sequence_container() -> None:
    result = await _runtime().run_node(
        CollectNode(),
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="collect"),
        {
            "items": [
                ArtifactRefSequence.from_key(
                    key=VALUE_TYPE,
                    item_refs=[],
                )
            ]
        },
        artifact_type_bindings={"T": VALUE_TYPE},
    )

    assert isinstance(result, PersistedNodeOutput)
    output = result["items"]
    assert isinstance(output, ArtifactRefSequence)
    assert output.item_refs == []
    assert output.artifact_type == VALUE_TYPE.id
    assert output.schema_version == VALUE_TYPE.schema_version
    assert output.metadata["collect_segments"] == [
        {
            "input_index": 0,
            "start_index": 0,
            "item_count": 0,
            "source_kind": "sequence",
        }
    ]


@pytest.mark.asyncio
async def test_collect_requires_binding_and_validates_input_against_it() -> None:
    ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)
    runtime = _runtime()

    with pytest.raises(
        NodeContractResolutionError,
        match="missing artifact type bindings: T",
    ):
        await runtime.run_node(
            CollectNode(),
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="collect"),
            {"items": [ref]},
        )

    with pytest.raises(
        MaterializationError,
        match="expected example.other@1, got example.value@1",
    ):
        await runtime.run_node(
            CollectNode(),
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="collect"),
            {"items": [ref]},
            artifact_type_bindings={"T": OTHER_TYPE},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ordered", "item_count"),
    [(True, 0), (False, 2)],
)
async def test_count_supports_empty_and_unordered_sequences(
    ordered: bool,
    item_count: int,
) -> None:
    refs = [
        ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)
        for _ in range(item_count)
    ]
    sequence = ArtifactRefSequence(
        artifact_type=VALUE_TYPE.id,
        schema_version=VALUE_TYPE.schema_version,
        item_refs=refs,
        ordered=ordered,
    )

    output = await CountNode().run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="count"),
        NoConfig(),
        CountInput(items=sequence),
    )

    assert output.count == item_count


@pytest.mark.asyncio
async def test_slice_selects_refs_and_builds_truthful_sequence_metadata() -> None:
    refs = [ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE) for _ in range(4)]
    source = ArtifactRefSequence(
        artifact_type=VALUE_TYPE.id,
        schema_version=VALUE_TYPE.schema_version,
        item_refs=refs,
        index_key="source_position",
        metadata={
            "source_sequence_id": "stale-source",
            "start": 99,
            "unrelated": "stale",
        },
    )

    result = await _runtime().run_node(
        SliceNode(),
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="slice"),
        {"items": source},
        {"start": 1, "count": 2},
        artifact_type_bindings={"T": VALUE_TYPE},
    )

    assert isinstance(result, PersistedNodeOutput)
    output = result["items"]
    assert isinstance(output, ArtifactRefSequence)
    assert output.sequence_id != source.sequence_id
    assert output.item_refs == refs[1:3]
    assert output.ordered is True
    assert output.index_key == "source_position"
    assert output.metadata == {
        "source_sequence_id": str(source.sequence_id),
        "start": 1,
        "count": 2,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "expected_indices", "expected_count"),
    [
        ({"start": 2}, [2, 3], None),
        ({"start": 10, "count": 3}, [], 3),
        ({"start": 1, "count": 0}, [], 0),
    ],
)
async def test_slice_handles_open_ended_empty_and_beyond_end_ranges(
    config: dict[str, object],
    expected_indices: list[int],
    expected_count: int | None,
) -> None:
    refs = [ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE) for _ in range(4)]
    source = ArtifactRefSequence.from_key(key=VALUE_TYPE, item_refs=refs)

    result = await _runtime().run_node(
        SliceNode(),
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="slice"),
        {"items": source},
        config,
        artifact_type_bindings={"T": VALUE_TYPE},
    )

    assert isinstance(result, PersistedNodeOutput)
    output = result["items"]
    assert isinstance(output, ArtifactRefSequence)
    assert output.item_refs == [refs[index] for index in expected_indices]
    assert output.metadata["count"] == expected_count


@pytest.mark.asyncio
async def test_slice_rejects_unordered_sequence_with_its_id() -> None:
    source = ArtifactRefSequence(
        artifact_type=VALUE_TYPE.id,
        schema_version=VALUE_TYPE.schema_version,
        item_refs=[],
        ordered=False,
    )

    with pytest.raises(NodeRunError, match=str(source.sequence_id)):
        await _runtime().run_node(
            SliceNode(),
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="slice"),
            {"items": source},
            artifact_type_bindings={"T": VALUE_TYPE},
        )


@pytest.mark.asyncio
async def test_item_at_returns_the_existing_ref() -> None:
    refs = [ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE) for _ in range(3)]
    source = ArtifactRefSequence.from_key(key=VALUE_TYPE, item_refs=refs)

    result = await _runtime().run_node(
        ItemAtNode(),
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="pick"),
        {"items": source},
        {"index": 1},
        artifact_type_bindings={"T": VALUE_TYPE},
    )

    assert isinstance(result, PersistedNodeOutput)
    assert result["item"] == refs[1]


@pytest.mark.asyncio
async def test_item_at_rejects_unordered_sequence_with_its_id() -> None:
    source = ArtifactRefSequence(
        artifact_type=VALUE_TYPE.id,
        schema_version=VALUE_TYPE.schema_version,
        item_refs=[],
        ordered=False,
    )

    with pytest.raises(NodeRunError, match=str(source.sequence_id)):
        await _runtime().run_node(
            ItemAtNode(),
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="pick"),
            {"items": source},
            artifact_type_bindings={"T": VALUE_TYPE},
        )


@pytest.mark.asyncio
async def test_item_at_out_of_range_error_has_sequence_context() -> None:
    ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)
    source = ArtifactRefSequence.from_key(key=VALUE_TYPE, item_refs=[ref])

    with pytest.raises(NodeRunError) as error:
        await _runtime().run_node(
            ItemAtNode(),
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="pick"),
            {"items": source},
            {"index": 3},
            artifact_type_bindings={"T": VALUE_TYPE},
        )

    message = str(error.value)
    assert str(source.sequence_id) in message
    assert "index 3" in message
    assert "length 1" in message


@pytest.mark.parametrize(
    ("config_model", "payload"),
    [
        (SliceConfig, {"start": -1}),
        (SliceConfig, {"start": True}),
        (SliceConfig, {"count": -1}),
        (SliceConfig, {"count": True}),
        (ItemAtConfig, {"index": -1}),
        (ItemAtConfig, {"index": True}),
    ],
)
def test_positional_configs_require_non_negative_strict_integers(
    config_model: type[SliceConfig] | type[ItemAtConfig],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        config_model.model_validate(payload)
