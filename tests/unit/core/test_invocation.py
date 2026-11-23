from typing import Annotated, Any, ClassVar, cast, override
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
    NoConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import (
    Node,
    NodeExecutionContext,
    OutputContract,
    OutputPortSpec,
    Plugs,
    PortShape,
    Ref,
    RefSequence,
    derive_input_contract,
    derive_output_contract,
)
from grafy_core.declared_values import note_declaration
from grafy_core.runtime.artifact_values import (
    Artifact,
    ArtifactFiles,
    ArtifactValues,
    EncodedArtifact,
    StoredArtifact,
    encode_inline_model,
)
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.invocation import (
    InvocationError,
    InvocationMode,
    NodeInvocation,
    effective_input_shape,
    effective_output_shape,
    map_input_candidates,
    supported_invocation_modes,
    validate_invocation,
)
from grafy_core.runtime.materialization import (
    InputMaterializer,
    MaterializationError,
    MaterializationProvenance,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.persistence import (
    ArtifactWriteContext,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.resolvers import ArtifactContractError


INPUT_VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("test.input_value", 1),
    title="Test input value",
)
OUTPUT_VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("test.output_value", 1),
    title="Test output value",
)
OTHER_VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("test.other_value", 1),
    title="Other test value",
)


TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


class SampleIn(int):
    pass


class SampleOut(int):
    pass


class SampleOther(int):
    pass


class DiagnosticNote:
    pass


note_declaration(SampleIn, INPUT_VALUE.key)
note_declaration(SampleOut, OUTPUT_VALUE.key)
note_declaration(SampleOther, OTHER_VALUE.key)


class _SamplePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _sample_artifact[T](
    spec: ArtifactTypeSpec,
    value_type: type[T],
) -> Artifact[T]:
    async def resolve(stored: StoredArtifact) -> T:
        payload = stored.row.inline_payload
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), int):
            raise ArtifactContractError(
                f"Artifact {stored.row.id} does not store an integer value"
            )
        return cast(T, cast(Any, value_type)(payload["value"]))

    async def write(value: T, _files: ArtifactFiles) -> EncodedArtifact:
        return encode_inline_model(_SamplePayload(value=int(cast(Any, value))))

    return Artifact(
        spec=spec,
        value_type=value_type,
        resolve=resolve,
        write=write,
    )


def _values(*declarations: Artifact[Any]) -> ArtifactValues:
    return ArtifactValues(
        declarations,
        uow=InMemoryUnitOfWork(),
        storage=cast(FileStoragePort, object()),
        bucket="artifacts",
        storage_backend="local",
    )


def _write_context() -> ArtifactWriteContext:
    return ArtifactWriteContext(
        node_context=NodeExecutionContext(
            workspace_id=TEST_WORKSPACE_ID,
            node_id="seed",
        ),
        provenance=MaterializationProvenance(refs_by_input={}),
    )


class CollectionInput(NodeInput):
    items: list[SampleIn]


class MultiTypeInput(NodeInput):
    source: Ref[SampleIn] | Ref[SampleOther]


class CollectionOutput(NodeOutput):
    total: SampleOut


class CollectionNode(Node[NoConfig, CollectionInput, CollectionOutput]):
    operator_id: ClassVar[str] = "test.collection"
    operator_version: ClassVar[int] = 1

    def __init__(self) -> None:
        self.calls: list[tuple[int | None, list[int]]] = []

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: CollectionInput,
        /,
    ) -> CollectionOutput:
        self.calls.append((context.invocation_index, list(inputs.items)))
        return CollectionOutput(total=SampleOut(sum(inputs.items)))


class ScalarInput(NodeInput):
    item: SampleIn
    broadcast: SampleIn


class ScalarOutput(NodeOutput):
    value: SampleOut


class ScalarNode(Node[NoConfig, ScalarInput, ScalarOutput]):
    operator_id: ClassVar[str] = "test.scalar"
    operator_version: ClassVar[int] = 1

    def __init__(self) -> None:
        self.calls: list[tuple[int | None, int, int]] = []

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: ScalarInput,
        /,
    ) -> ScalarOutput:
        self.calls.append((context.invocation_index, inputs.item, inputs.broadcast))
        return ScalarOutput(value=SampleOut(inputs.item + inputs.broadcast))


class OptionalDriverInput(NodeInput):
    item: SampleIn | None = None


class OptionalDriverNode(Node[NoConfig, OptionalDriverInput, ScalarOutput]):
    operator_id: ClassVar[str] = "test.optional_driver"
    operator_version: ClassVar[int] = 1

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        _inputs: OptionalDriverInput,
        /,
    ) -> ScalarOutput:
        return ScalarOutput(value=SampleOut(0))


class VariadicDriverInput(NodeInput):
    items: Annotated[list[SampleIn], Plugs(variadic=True)]


class MixedInstancePlugInput(NodeInput):
    items: Annotated[
        list[Ref[SampleIn] | RefSequence[SampleIn]],
        Plugs(variadic=True, instance=True),
    ]


class VariadicDriverNode(Node[NoConfig, VariadicDriverInput, ScalarOutput]):
    operator_id: ClassVar[str] = "test.variadic_driver"
    operator_version: ClassVar[int] = 1

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        _inputs: VariadicDriverInput,
        /,
    ) -> ScalarOutput:
        return ScalarOutput(value=SampleOut(0))


class ManyOutput(NodeOutput):
    values: list[SampleOut]


class ManyOutputNode(Node[NoConfig, ScalarInput, ManyOutput]):
    operator_id: ClassVar[str] = "test.many_output"
    operator_version: ClassVar[int] = 1

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        inputs: ScalarInput,
        /,
    ) -> ManyOutput:
        return ManyOutput(values=[SampleOut(inputs.item)])


class ExtraOutput(NodeOutput):
    value: SampleOut
    diagnostic: DiagnosticNote


class ExtraOutputNode(Node[NoConfig, ScalarInput, ExtraOutput]):
    operator_id: ClassVar[str] = "test.extra_output"
    operator_version: ClassVar[int] = 1

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        inputs: ScalarInput,
        /,
    ) -> ExtraOutput:
        return ExtraOutput(value=SampleOut(inputs.item), diagnostic=DiagnosticNote())


class LooseOutput(NodeOutput):
    value: object


def _passthrough_contract() -> OutputContract[LooseOutput]:
    return OutputContract(
        model=LooseOutput,
        ports={
            "value": OutputPortSpec(
                name="value",
                produces=OUTPUT_VALUE.key,
            )
        },
    )


@pytest.mark.asyncio
async def test_once_invokes_collection_node_once_with_the_whole_sequence() -> None:
    values = _values(
        _sample_artifact(INPUT_VALUE, SampleIn),
        _sample_artifact(OUTPUT_VALUE, SampleOut),
    )
    context = _write_context()
    first_ref = await values.write(INPUT_VALUE.key, SampleIn(2), context)
    second_ref = await values.write(INPUT_VALUE.key, SampleIn(4), context)
    runtime = NodeRuntime(
        materializer=InputMaterializer(values),
        persister=OutputPersister(values),
    )
    node = CollectionNode()

    result = await runtime.run_node(
        node,
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="collection"),
        {
            "items": ArtifactRefSequence.from_key(
                key=INPUT_VALUE.key,
                item_refs=[first_ref, second_ref],
            )
        },
    )

    assert node.calls == [(None, [2, 4])]
    assert isinstance(result, PersistedNodeOutput)
    total = result["total"]
    assert isinstance(total, ArtifactRef)
    assert await values.resolve(total, TEST_WORKSPACE_ID) == SampleOut(6)


def test_invocation_capabilities_and_effective_shapes() -> None:
    invocation = NodeInvocation(mode=InvocationMode.MAP, map_inputs=("item",))

    assert map_input_candidates(ScalarNode) == ("item", "broadcast")
    assert supported_invocation_modes(ScalarNode) == (
        InvocationMode.ONCE,
        InvocationMode.MAP,
    )
    assert effective_input_shape(ScalarNode, invocation, "item") is PortShape.MANY
    assert effective_input_shape(ScalarNode, invocation, "broadcast") is PortShape.ONE
    assert effective_output_shape(ScalarNode, invocation, "value") is PortShape.MANY


def test_optional_single_value_input_can_drive_map() -> None:
    invocation = NodeInvocation(mode=InvocationMode.MAP, map_inputs=("item",))

    assert map_input_candidates(OptionalDriverNode) == ("item",)
    assert supported_invocation_modes(OptionalDriverNode) == (
        InvocationMode.ONCE,
        InvocationMode.MAP,
    )
    validate_invocation(OptionalDriverNode, invocation)
    assert (
        effective_input_shape(OptionalDriverNode, invocation, "item") is PortShape.MANY
    )
    assert (
        effective_output_shape(OptionalDriverNode, invocation, "value")
        is PortShape.MANY
    )


def test_sequence_input_can_drive_map() -> None:
    invocation = NodeInvocation(mode=InvocationMode.MAP, map_inputs=("items",))

    assert map_input_candidates(CollectionNode) == ("items",)
    validate_invocation(CollectionNode, invocation)
    assert effective_input_shape(CollectionNode, invocation, "items") is PortShape.MANY
    assert effective_output_shape(CollectionNode, invocation, "total") is PortShape.MANY


@pytest.mark.parametrize(
    ("node", "map_input", "message"),
    [
        (ScalarNode, "missing", "does not exist"),
        (VariadicDriverNode, "items", "cannot be variadic"),
        (ManyOutputNode, "item", "MAP output 'values' must have shape 'one'"),
        (ExtraOutputNode, "item", "non-port fields: diagnostic"),
    ],
)
def test_invalid_map_drivers_and_output_contracts_are_rejected(
    node: object,
    map_input: str,
    message: str,
) -> None:
    with pytest.raises(InvocationError, match=message):
        validate_invocation(
            cast(type[ScalarNode], node),
            NodeInvocation(mode=InvocationMode.MAP, map_inputs=(map_input,)),
        )


@pytest.mark.asyncio
async def test_materializer_rejects_wrong_key_empty_sequence() -> None:
    materializer = InputMaterializer()

    with pytest.raises(
        MaterializationError,
        match="expected test.input_value@1, got test.other_value@1",
    ):
        await materializer.materialize(
            CollectionNode.input_contract,
            {
                "items": ArtifactRefSequence.from_key(
                    key=OTHER_VALUE.key,
                    item_refs=[],
                )
            },
            TEST_WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_materializer_accepts_every_declared_artifact_type() -> None:
    materializer = InputMaterializer()
    contract = derive_input_contract(MultiTypeInput)

    for key in (INPUT_VALUE.key, OTHER_VALUE.key):
        ref = ArtifactRef.from_key(artifact_id=uuid4(), key=key)
        inputs, _ = await materializer.materialize(
            contract,
            {"source": ref},
            TEST_WORKSPACE_ID,
        )
        assert inputs.source.artifact_id == ref.artifact_id
        assert inputs.source.key() == ref.key()

    third = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=ArtifactTypeKey("test.third_value", 1),
    )
    with pytest.raises(
        MaterializationError,
        match="expected test.input_value@1, test.other_value@1, got test.third_value@1",
    ):
        await materializer.materialize(
            contract,
            {"source": third},
            TEST_WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_materializer_preserves_mixed_plugs_and_flattens_provenance() -> None:
    first_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=INPUT_VALUE.key)
    second_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=INPUT_VALUE.key)
    third_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=INPUT_VALUE.key)
    sequence = ArtifactRefSequence.from_key(
        key=INPUT_VALUE.key,
        item_refs=[second_ref, third_ref],
    )
    raw_items: list[ArtifactRef | ArtifactRefSequence] = [first_ref, sequence]

    inputs, provenance = await InputMaterializer().materialize(
        derive_input_contract(MixedInstancePlugInput),
        {"items": raw_items},
        TEST_WORKSPACE_ID,
    )

    assert isinstance(inputs.items[0], ArtifactRef)
    assert inputs.items[0].artifact_id == first_ref.artifact_id
    assert inputs.items[0].key() == first_ref.key()
    assert isinstance(inputs.items[1], ArtifactRefSequence)
    assert inputs.items[1].sequence_id == sequence.sequence_id
    assert [item.artifact_id for item in inputs.items[1].item_refs] == [
        second_ref.artifact_id,
        third_ref.artifact_id,
    ]
    assert provenance.refs_for("items") == (first_ref, second_ref, third_ref)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        [ArtifactRef.from_key(artifact_id=uuid4(), key=OTHER_VALUE.key)],
        [ArtifactRefSequence.from_key(key=OTHER_VALUE.key, item_refs=[])],
    ],
)
async def test_materializer_rejects_wrong_instance_plug_keys(
    value: list[ArtifactRef | ArtifactRefSequence],
) -> None:
    with pytest.raises(
        MaterializationError,
        match="expected test.input_value@1, got test.other_value@1",
    ):
        await InputMaterializer().materialize(
            derive_input_contract(MixedInstancePlugInput),
            {"items": value},
            TEST_WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_materializer_rejects_empty_required_instance_plugs() -> None:
    with pytest.raises(
        MaterializationError,
        match="expected at least one incoming edge",
    ):
        await InputMaterializer().materialize(
            derive_input_contract(MixedInstancePlugInput),
            {"items": []},
            TEST_WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_output_persister_rejects_passthrough_key_and_shape_mismatches() -> None:
    persister = OutputPersister()
    contract = _passthrough_contract()
    context = NodeExecutionContext(
        workspace_id=TEST_WORKSPACE_ID,
        node_id="passthrough",
    )
    provenance = MaterializationProvenance(refs_by_input={})
    wrong_key_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=OTHER_VALUE.key,
    )

    with pytest.raises(
        RuntimeError,
        match="expected test.output_value@1, got test.other_value@1",
    ):
        await persister.persist(
            contract,
            context,
            LooseOutput(value=wrong_key_ref),
            provenance,
        )

    correct_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=OUTPUT_VALUE.key,
    )
    with pytest.raises(
        RuntimeError,
        match="expected an ArtifactRef, got ArtifactRefSequence",
    ):
        await persister.persist(
            contract,
            context,
            LooseOutput(
                value=ArtifactRefSequence.from_key(
                    key=OUTPUT_VALUE.key,
                    item_refs=[correct_ref],
                )
            ),
            provenance,
        )


@pytest.mark.asyncio
async def test_sequence_items_carry_the_metadata_of_their_port() -> None:
    """Every item of a sequence port carries what was recorded for its port.

    The persister copies a node's metadata onto each artifact it writes, and the keys
    are the writer's business, so the fixture uses an ordinary pair. Recording metadata
    reached a single-value output
    and was dropped from each item written for a MANY port, so every sequence output —
    a decoded image, a scanned raster — lost what its run had recorded about it,
    and the card that follows it fell back to waiting.
    """

    values = _values(_sample_artifact(OUTPUT_VALUE, SampleOut))
    recorded: JsonObject = {"origin": "port", "attempt": 2}

    result = await OutputPersister(values).persist(
        derive_output_contract(ManyOutput),
        NodeExecutionContext(
            workspace_id=TEST_WORKSPACE_ID,
            node_id="many",
        ),
        ManyOutput(values=[SampleOut(1), SampleOut(2), SampleOut(3)]),
        MaterializationProvenance(refs_by_input={}),
        metadata=recorded,
    )

    assert isinstance(result, PersistedNodeOutput)
    sequence = result["values"]
    assert isinstance(sequence, ArtifactRefSequence)
    stored = [await values.open(ref, TEST_WORKSPACE_ID) for ref in sequence.item_refs]
    assert [row.row.inline_payload for row in stored] == [
        {"value": 1},
        {"value": 2},
        {"value": 3},
    ]
    assert [row.row.metadata["origin"] for row in stored] == ["port", "port", "port"]
    assert [row.row.metadata["attempt"] for row in stored] == [2, 2, 2]


def test_multiple_map_inputs_validate_and_have_many_shape() -> None:
    invocation = NodeInvocation(
        mode=InvocationMode.MAP, map_inputs=("item", "broadcast")
    )
    validate_invocation(ScalarNode, invocation)
    assert effective_input_shape(ScalarNode, invocation, "item") is PortShape.MANY
    assert effective_input_shape(ScalarNode, invocation, "broadcast") is PortShape.MANY
    with pytest.raises(InvocationError, match="MAP input 'missing' does not exist"):
        validate_invocation(
            ScalarNode,
            NodeInvocation(mode=InvocationMode.MAP, map_inputs=("item", "missing")),
        )


@pytest.mark.parametrize(
    ("mode", "names", "message"),
    [
        (InvocationMode.MAP, (), "requires at least one"),
        (InvocationMode.MAP, ("item", "item"), "must be unique"),
        (InvocationMode.MAP, ("item", " "), "must not be blank"),
        (InvocationMode.MAP, ("",), "must not be blank"),
        (InvocationMode.ONCE, ("item",), "does not accept"),
    ],
)
def test_invocation_rejects_invalid_map_inputs(
    mode: InvocationMode, names: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _ = NodeInvocation(mode=mode, map_inputs=names)
