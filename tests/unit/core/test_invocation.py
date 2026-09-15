from collections.abc import Callable
from typing import Annotated, ClassVar, cast, override
from uuid import UUID, uuid4

import pytest

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.implementation import (
    BuiltinImplementationIdentity,
    PluginImplementationIdentity,
)
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.domain.saved_graphs import SavedGraphPluginReleasePin
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    PortShape,
    derive_input_contract,
    derive_output_contract,
)
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.invocation_cache import (
    INVOCATION_CACHE_FINGERPRINT_VERSION,
    InvocationCachePort,
    invocation_cache_key,
)
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
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriteContext,
    ArtifactWriterRegistry,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.resolvers import Resolver, ResolverRegistry


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


class IntResolver:
    source = INPUT_VALUE.key
    target = int

    def __init__(self, values: dict[UUID, int]) -> None:
        self._values = values

    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> int:
        return self._values[ref.artifact_id]


class RecordingWriter:
    artifact_type = OUTPUT_VALUE.key

    def __init__(self, completed_count: Callable[[], int] = lambda: 0) -> None:
        self._completed_count = completed_count
        self.values: list[int] = []
        self.item_indexes: list[int | None] = []
        self.completed_counts: list[int] = []
        self.refs: list[ArtifactRef] = []

    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        assert isinstance(value, int)
        self.values.append(value)
        self.item_indexes.append(context.item_index)
        self.completed_counts.append(self._completed_count())
        ref = ArtifactRef.from_key(
            artifact_id=uuid4(),
            key=self.artifact_type,
        )
        self.refs.append(ref)
        return ref


class MemoryInvocationCache(InvocationCachePort):
    def __init__(self) -> None:
        self.entries: dict[tuple[UUID, str], InvocationCacheEntry] = {}

    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> InvocationCacheEntry | None:
        return self.entries.get((workspace_id, key_sha256))

    async def put_if_absent(self, entry: InvocationCacheEntry) -> bool:
        if (entry.workspace_id, entry.key_sha256) in self.entries:
            return False
        self.entries[(entry.workspace_id, entry.key_sha256)] = entry
        return True

    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        entry = self.entries.get((workspace_id, key_sha256))
        if entry is None or entry.generation != generation:
            return False
        del self.entries[(workspace_id, key_sha256)]
        return True


class CollectionInput(NodeInput):
    items: Annotated[list[int], InPort(INPUT_VALUE)]


class MultiTypeInput(NodeInput):
    source: Annotated[
        ArtifactRef,
        InPort(INPUT_VALUE, also_accepts=(OTHER_VALUE,)),
    ]


class CollectionOutput(NodeOutput):
    total: Annotated[int, OutPort(OUTPUT_VALUE)]


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
        return CollectionOutput(total=sum(inputs.items))


class ScalarInput(NodeInput):
    item: Annotated[int, InPort(INPUT_VALUE)]
    broadcast: Annotated[int, InPort(INPUT_VALUE)]


class ScalarOutput(NodeOutput):
    value: Annotated[int, OutPort(OUTPUT_VALUE)]


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
        return ScalarOutput(value=inputs.item + inputs.broadcast)


class OptionalDriverInput(NodeInput):
    item: Annotated[int | None, InPort(INPUT_VALUE)] = None


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
        return ScalarOutput(value=0)


class VariadicDriverInput(NodeInput):
    items: Annotated[list[int], InPort(INPUT_VALUE, variadic=True)]


class MixedInstancePlugInput(NodeInput):
    items: Annotated[
        list[ArtifactRef | ArtifactRefSequence],
        InPort(INPUT_VALUE, variadic=True, instance_plugs=True),
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
        return ScalarOutput(value=0)


class ManyOutput(NodeOutput):
    values: Annotated[list[int], OutPort(OUTPUT_VALUE)]


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
        return ManyOutput(values=[inputs.item])


class ExtraOutput(NodeOutput):
    value: Annotated[int, OutPort(OUTPUT_VALUE)]
    diagnostic: str


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
        return ExtraOutput(value=inputs.item, diagnostic="unused")


class PassthroughOutput(NodeOutput):
    value: Annotated[object, OutPort(OUTPUT_VALUE)]


def runtime_with(
    resolver: IntResolver,
    writer: RecordingWriter,
    invocation_cache: InvocationCachePort | None = None,
) -> NodeRuntime:
    resolvers = ResolverRegistry()
    resolvers.register(cast(Resolver[object], resolver))
    writers = ArtifactWriterRegistry()
    writers.register(cast(ArtifactOutputWriter, writer))
    return NodeRuntime(
        materializer=InputMaterializer(resolvers),
        persister=OutputPersister(writers),
        invocation_cache=invocation_cache,
    )


@pytest.mark.asyncio
async def test_once_invokes_collection_node_once_with_the_whole_sequence() -> None:
    first_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=INPUT_VALUE.key)
    second_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=INPUT_VALUE.key)
    resolver = IntResolver({first_ref.artifact_id: 2, second_ref.artifact_id: 4})
    writer = RecordingWriter()
    runtime = runtime_with(resolver, writer)
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
    assert writer.values == [6]
    assert writer.item_indexes == [None]
    assert isinstance(result, PersistedNodeOutput)
    assert result["total"] == writer.refs[0]


def test_invocation_capabilities_and_effective_shapes() -> None:
    invocation = NodeInvocation(mode=InvocationMode.MAP, map_input="item")

    assert map_input_candidates(ScalarNode) == ("item", "broadcast")
    assert supported_invocation_modes(ScalarNode) == (
        InvocationMode.ONCE,
        InvocationMode.MAP,
    )
    assert effective_input_shape(ScalarNode, invocation, "item") is PortShape.MANY
    assert effective_input_shape(ScalarNode, invocation, "broadcast") is PortShape.ONE
    assert effective_output_shape(ScalarNode, invocation, "value") is PortShape.MANY


@pytest.mark.parametrize(
    ("node", "map_input", "message"),
    [
        (ScalarNode, "missing", "does not exist"),
        (CollectionNode, "items", "must have shape 'one'"),
        (OptionalDriverNode, "item", "must be required"),
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
            NodeInvocation(mode=InvocationMode.MAP, map_input=map_input),
        )


@pytest.mark.asyncio
async def test_materializer_rejects_wrong_key_empty_sequence() -> None:
    materializer = InputMaterializer(ResolverRegistry())

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
    materializer = InputMaterializer(ResolverRegistry())
    contract = derive_input_contract(MultiTypeInput)

    for key in (INPUT_VALUE.key, OTHER_VALUE.key):
        ref = ArtifactRef.from_key(artifact_id=uuid4(), key=key)
        inputs, _ = await materializer.materialize(
            contract,
            {"source": ref},
            TEST_WORKSPACE_ID,
        )
        assert inputs.source == ref

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

    inputs, provenance = await InputMaterializer(ResolverRegistry()).materialize(
        derive_input_contract(MixedInstancePlugInput),
        {"items": raw_items},
        TEST_WORKSPACE_ID,
    )

    assert inputs.items == raw_items
    assert isinstance(inputs.items[0], ArtifactRef)
    assert isinstance(inputs.items[1], ArtifactRefSequence)
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
        await InputMaterializer(ResolverRegistry()).materialize(
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
        await InputMaterializer(ResolverRegistry()).materialize(
            derive_input_contract(MixedInstancePlugInput),
            {"items": []},
            TEST_WORKSPACE_ID,
        )


def test_registries_reject_duplicate_contracts() -> None:
    resolver = cast(Resolver[object], IntResolver({}))
    resolvers = ResolverRegistry([resolver])
    with pytest.raises(ValueError, match="Resolver already registered"):
        resolvers.register(resolver)

    writer = cast(ArtifactOutputWriter, RecordingWriter())
    writers = ArtifactWriterRegistry([writer])
    with pytest.raises(ValueError, match="Output writer already registered"):
        writers.register(writer)


@pytest.mark.asyncio
async def test_output_persister_rejects_passthrough_key_and_shape_mismatches() -> None:
    persister = OutputPersister(ArtifactWriterRegistry())
    contract = derive_output_contract(PassthroughOutput)
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
            PassthroughOutput(value=wrong_key_ref),
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
            PassthroughOutput(
                value=ArtifactRefSequence.from_key(
                    key=OUTPUT_VALUE.key,
                    item_refs=[correct_ref],
                )
            ),
            provenance,
        )


class FingerprintConfig(NodeConfig):
    offset: int = 7


def test_invocation_cache_key_is_canonical_and_scoped_to_stable_context() -> None:
    input_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=INPUT_VALUE.key,
        content_hash="a" * 64,
    )
    node = ScalarNode()
    first_context = NodeExecutionContext(
        workspace_id=TEST_WORKSPACE_ID,
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        graph_id=uuid4(),
        graph_revision=1,
        node_id="stable-node",
        module_path=("graph.module.example@3",),
    )
    second_context = NodeExecutionContext(
        workspace_id=TEST_WORKSPACE_ID,
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        graph_id=uuid4(),
        graph_revision=99,
        node_id="stable-node",
        module_path=("graph.module.example@3",),
    )
    first = invocation_cache_key(
        node=node,
        context=first_context,
        inputs={"item": input_ref},
        config=FingerprintConfig.model_validate({}),
        artifact_type_bindings={
            "Z": OTHER_VALUE.key,
            "A": INPUT_VALUE.key,
        },
        opaque_secret_revisions={"secondary": "r2", "primary": "r1"},
    )
    second = invocation_cache_key(
        node=node,
        context=second_context,
        inputs={"item": input_ref},
        config=FingerprintConfig.model_validate({"offset": 7}),
        artifact_type_bindings={
            "A": INPUT_VALUE.key,
            "Z": OTHER_VALUE.key,
        },
        opaque_secret_revisions={"primary": "r1", "secondary": "r2"},
    )

    assert first is not None
    assert first == second
    assert first != invocation_cache_key(
        node=node,
        context=NodeExecutionContext(
            workspace_id=TEST_WORKSPACE_ID,
            node_id="other-node",
            module_path=("graph.module.example@3",),
        ),
        inputs={"item": input_ref},
        config=FingerprintConfig.model_validate({}),
        artifact_type_bindings={"A": INPUT_VALUE.key, "Z": OTHER_VALUE.key},
        opaque_secret_revisions={"primary": "r1", "secondary": "r2"},
    )
    assert first != invocation_cache_key(
        node=node,
        context=first_context,
        inputs={"item": input_ref},
        config=FingerprintConfig.model_validate({}),
        artifact_type_bindings={"A": INPUT_VALUE.key, "Z": OTHER_VALUE.key},
        opaque_secret_revisions={"primary": "changed", "secondary": "r2"},
    )
    assert first != invocation_cache_key(
        node=node,
        context=NodeExecutionContext(
            workspace_id=TEST_WORKSPACE_ID,
            node_id="stable-node",
            invocation_index=0,
            module_path=("graph.module.example@3",),
        ),
        inputs={"item": input_ref},
        config=FingerprintConfig.model_validate({}),
        artifact_type_bindings={"A": INPUT_VALUE.key, "Z": OTHER_VALUE.key},
        opaque_secret_revisions={"primary": "r1", "secondary": "r2"},
    )


def test_invocation_cache_key_requires_input_content_hashes() -> None:
    input_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=INPUT_VALUE.key,
    )

    assert (
        invocation_cache_key(
            node=ScalarNode(),
            context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="scalar",
            ),
            inputs={"item": input_ref},
            config=NoConfig(),
            artifact_type_bindings={},
            opaque_secret_revisions={},
        )
        is None
    )


@pytest.mark.asyncio
async def test_exact_once_cache_hit_skips_node_and_writer() -> None:
    first_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=INPUT_VALUE.key,
        content_hash="1" * 64,
    )
    second_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=INPUT_VALUE.key,
        content_hash="2" * 64,
    )
    source = ArtifactRefSequence.from_key(
        key=INPUT_VALUE.key,
        item_refs=[first_ref, second_ref],
    )
    resolver = IntResolver({first_ref.artifact_id: 2, second_ref.artifact_id: 4})
    writer = RecordingWriter()
    cache = MemoryInvocationCache()
    runtime = runtime_with(resolver, writer, cache)
    node = CollectionNode()

    first = await runtime.run_node(
        node,
        NodeExecutionContext(
            workspace_id=TEST_WORKSPACE_ID,
            workflow_run_id=uuid4(),
            node_run_id=uuid4(),
            graph_revision=1,
            node_id="collection",
        ),
        {"items": source},
        cache_policy=NodeCachePolicy.EXACT,
    )
    second = await runtime.run_node(
        node,
        NodeExecutionContext(
            workspace_id=TEST_WORKSPACE_ID,
            workflow_run_id=uuid4(),
            node_run_id=uuid4(),
            graph_revision=2,
            node_id="collection",
        ),
        {"items": source},
        cache_policy=NodeCachePolicy.EXACT,
    )

    assert isinstance(first, PersistedNodeOutput)
    assert isinstance(second, PersistedNodeOutput)
    assert first.cache_hits == 0
    assert first.cache_misses == 1
    assert second.cache_hits == 1
    assert second.cache_misses == 0
    assert second["total"] == first["total"]
    assert node.calls == [(None, [2, 4])]
    assert writer.values == [6]
    assert len(cache.entries) == 1


@pytest.mark.asyncio
async def test_exact_cache_bypasses_inputs_without_content_hashes() -> None:
    input_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=INPUT_VALUE.key,
    )
    resolver = IntResolver({input_ref.artifact_id: 3})
    writer = RecordingWriter()
    cache = MemoryInvocationCache()
    runtime = runtime_with(resolver, writer, cache)
    node = CollectionNode()
    source = ArtifactRefSequence.from_key(
        key=INPUT_VALUE.key,
        item_refs=[input_ref],
    )

    results = [
        await runtime.run_node(
            node,
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="collection"),
            {"items": source},
            cache_policy=NodeCachePolicy.EXACT,
        )
        for _ in range(2)
    ]

    for result in results:
        assert isinstance(result, PersistedNodeOutput)
        assert result.cache_misses == 1
    assert node.calls == [(None, [3]), (None, [3])]
    assert writer.values == [3, 3]
    assert cache.entries == {}


def _plugin_identity(revision: int) -> PluginImplementationIdentity:
    return PluginImplementationIdentity(
        plugin_release_pin=SavedGraphPluginReleasePin(
            scope=PluginReleaseScope.WORKSPACE,
            slug="notes",
            revision=revision,
        ),
        manifest_digest="d" * 64,
        image_digest="e" * 64,
    )


def _builtin_identity(digest: str) -> BuiltinImplementationIdentity:
    return BuiltinImplementationIdentity(build_digest=digest)


def test_invocation_cache_key_scopes_to_implementation_identity() -> None:
    input_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=INPUT_VALUE.key,
        content_hash="a" * 64,
    )
    context = NodeExecutionContext(
        workspace_id=TEST_WORKSPACE_ID,
        node_id="echo",
    )
    node = ScalarNode()
    inputs = {"item": input_ref}
    config = NoConfig.model_validate({})
    kwargs = {
        "node": node,
        "context": context,
        "inputs": inputs,
        "config": config,
        "artifact_type_bindings": {},
        "opaque_secret_revisions": {},
    }
    missing = invocation_cache_key(**kwargs)
    builtin_one = invocation_cache_key(
        **kwargs,
        implementation=_builtin_identity("a" * 64),
    )
    builtin_two = invocation_cache_key(
        **kwargs,
        implementation=_builtin_identity("b" * 64),
    )
    plugin_one = invocation_cache_key(
        **kwargs,
        implementation=_plugin_identity(1),
    )
    plugin_two = invocation_cache_key(
        **kwargs,
        implementation=_plugin_identity(2),
    )

    assert missing is not None
    assert builtin_one is not None
    assert builtin_two is not None
    assert plugin_one is not None
    assert plugin_two is not None
    assert missing != builtin_one
    assert builtin_one != builtin_two
    assert plugin_one != plugin_two
    assert builtin_one != plugin_one


def test_invocation_fingerprint_version_covers_implementation_identity() -> None:
    assert INVOCATION_CACHE_FINGERPRINT_VERSION >= 4
