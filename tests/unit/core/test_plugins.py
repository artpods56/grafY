from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from uuid import UUID
from typing import Annotated, cast, override

import pytest
from pydantic import BaseModel, ConfigDict

from grafy_core.artifacts import (
    ArtifactFieldProjection,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.conversions import (
    ArtifactConversion,
    ArtifactConversionKey,
    conversion_runtime_types_are_compatible,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    MAX_NODE_PROGRESS_COUNTER,
    InPort,
    Node,
    NodeExecutionContext,
)
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
    Plugin,
    PluginRegistrationError,
    PluginRegistry,
    PluginRuntimeContext,
    UnknownOperatorError,
)
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_storage import LocalFileObjectStore


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


def _stringify_integer(value: int) -> str:
    return str(value)


def _integer_is_positive(value: int) -> bool:
    return value > 0


class ConversionBase:
    pass


class ConversionChild(ConversionBase):
    pass


@pytest.mark.parametrize(
    ("produced", "accepted", "expected"),
    [
        (bool, int, False),
        (bool, float, False),
        (bool, object, True),
        (datetime, date, False),
        (int, float, True),
        (ConversionChild, ConversionBase, False),
    ],
)
def test_conversion_runtime_type_compatibility_matches_strict_validation(
    produced: type[object],
    accepted: type[object],
    expected: bool,
) -> None:
    assert conversion_runtime_types_are_compatible(produced, accepted) is expected


class EmptyInput(NodeInput):
    pass


class EmptyOutput(NodeOutput):
    pass


class DefaultNode(Node[NoConfig, EmptyInput, EmptyOutput]):
    """Returns an empty output without runtime dependencies."""

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        return EmptyOutput()


class ContextNode(Node[NoConfig, EmptyInput, EmptyOutput]):
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        return EmptyOutput()


class SecretConfig(NodeConfig):
    base_url: str = "https://example.test/v1"


class SecretNode(Node[SecretConfig, EmptyInput, EmptyOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: SecretConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        return EmptyOutput()


UNREGISTERED_VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("example.unregistered", 1),
    title="Unregistered value",
)


class ConcretePortInput(NodeInput):
    value: Annotated[object, InPort(UNREGISTERED_VALUE)]


class ConcretePortNode(Node[NoConfig, ConcretePortInput, EmptyOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        _inputs: ConcretePortInput,
        /,
    ) -> EmptyOutput:
        return EmptyOutput()


async def empty_function_node(
    _config: NoConfig,
    _inputs: EmptyInput,
) -> EmptyOutput:
    """Returns an empty output through the function API."""
    return EmptyOutput()


_context_function_calls: list[NodeExecutionContext] = []


async def context_function_node(
    context: NodeExecutionContext,
    _config: NoConfig,
    _inputs: EmptyInput,
) -> EmptyOutput:
    _context_function_calls.append(context)
    return EmptyOutput()


class RecordingProgressReporter:
    def __init__(self) -> None:
        self.reports: list[
            tuple[NodeExecutionContext, str, int | None, int | None]
        ] = []

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        self.reports.append((context, message, current, total))


class FailingProgressReporter:
    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        del context, message, current, total
        raise RuntimeError("progress transport failed")


class ProjectionCustomer(BaseModel):
    model_config = ConfigDict(title="Customer")

    name: str
    age: int


class ProjectionPayload(BaseModel):
    customer: ProjectionCustomer
    label: str
    quantity: int
    tags: list[str]


def runtime_context(tmp_path: Path) -> PluginRuntimeContext:
    return PluginRuntimeContext(
        workspace=tmp_path,
        uploads_dir=tmp_path / "uploads",
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="test-artifacts",
    )


def test_node_decorator_records_plugin_metadata_and_docstring() -> None:
    plugin = Plugin(slug="example.tools", title="Example tools")
    decorated = plugin.node(
        operator_id="example.default",
        version=2,
        title="Default example",
    )(DefaultNode)

    registration = plugin.nodes[0]

    assert decorated is DefaultNode
    assert decorated.plugin_slug == "example.tools"
    assert decorated.title == "Default example"
    assert decorated.description == (
        "Returns an empty output without runtime dependencies."
    )
    assert registration.plugin_slug == "example.tools"
    assert registration.title == "Default example"
    assert registration.description == (
        "Returns an empty output without runtime dependencies."
    )
    assert registration.key == ("example.default", 2)
    assert registration.secret_inputs == ()
    assert registration.cache_policy is NodeCachePolicy.NEVER


def test_node_decorator_records_exact_cache_policy() -> None:
    plugin = Plugin(slug="example.cacheable", title="Cacheable examples")

    plugin.node(
        operator_id="example.cacheable",
        version=1,
        title="Cacheable example",
        cache_policy=NodeCachePolicy.EXACT,
    )(DefaultNode)

    assert plugin.nodes[0].cache_policy is NodeCachePolicy.EXACT


@pytest.mark.asyncio
async def test_function_node_registers_an_ordinary_runtime_node(tmp_path: Path) -> None:
    plugin = Plugin(slug="example.functions", title="Function examples")

    decorated = plugin.function_node(
        operator_id="example.function",
        version=1,
        title="Function example",
        cache_policy=NodeCachePolicy.EXACT,
    )(empty_function_node)
    registry = PluginRegistry()
    registry.install(plugin)
    registry.freeze()

    registration = registry.node_registration("example.function", 1)
    node = registry.build_node("example.function", 1, runtime_context(tmp_path))
    result = await node.run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID), NoConfig(), EmptyInput()
    )

    assert decorated is empty_function_node
    assert registration.node_class.config_contract.model is NoConfig
    assert registration.node_class.input_contract.model is EmptyInput
    assert registration.node_class.output_contract.model is EmptyOutput
    assert registration.description == (
        "Returns an empty output through the function API."
    )
    assert registration.cache_policy is NodeCachePolicy.EXACT
    assert result == EmptyOutput()


@pytest.mark.asyncio
async def test_function_node_can_opt_into_execution_context(tmp_path: Path) -> None:
    _context_function_calls.clear()
    plugin = Plugin(slug="example.context-functions", title="Context functions")
    decorated = plugin.function_node(
        operator_id="example.context-function",
        version=1,
        title="Context function",
    )(context_function_node)
    registry = PluginRegistry()
    registry.install(plugin)
    registry.freeze()
    context = NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="context-node")

    node = registry.build_node(
        "example.context-function",
        1,
        runtime_context(tmp_path),
    )
    result = await node.run(context, NoConfig(), EmptyInput())

    assert decorated is context_function_node
    assert result == EmptyOutput()
    assert _context_function_calls == [context]


@pytest.mark.asyncio
async def test_node_context_progress_is_validated_and_survives_replacement() -> None:
    reporter = RecordingProgressReporter()
    context = NodeExecutionContext(
        workspace_id=WORKSPACE_ID,
        node_id="mapped-node",
        node_path=("module-instance", "mapped-node"),
        progress_reporter=reporter,
    )
    mapped_context = replace(context, invocation_index=2)

    await NodeExecutionContext(workspace_id=WORKSPACE_ID).progress(
        "No reporter is a no-op"
    )
    await mapped_context.progress("  Preparing payload  ", current=2, total=4)
    await mapped_context.progress(
        "At the counter boundary",
        current=MAX_NODE_PROGRESS_COUNTER,
        total=MAX_NODE_PROGRESS_COUNTER,
    )
    await NodeExecutionContext(
        workspace_id=WORKSPACE_ID, progress_reporter=FailingProgressReporter()
    ).progress("Best effort")

    assert reporter.reports == [
        (mapped_context, "Preparing payload", 2, 4),
        (
            mapped_context,
            "At the counter boundary",
            MAX_NODE_PROGRESS_COUNTER,
            MAX_NODE_PROGRESS_COUNTER,
        ),
    ]
    with pytest.raises(ValueError, match="must not be blank"):
        await context.progress("   ")
    with pytest.raises(ValueError, match="must be at most 1000 characters"):
        await context.progress("x" * 1_001)
    with pytest.raises(ValueError, match="must not exceed total"):
        await context.progress("Invalid count", current=5, total=4)
    with pytest.raises(ValueError, match="current value must not exceed"):
        await context.progress(
            "Oversized current",
            current=MAX_NODE_PROGRESS_COUNTER + 1,
        )
    with pytest.raises(ValueError, match="total value must not exceed"):
        await context.progress(
            "Oversized total",
            total=MAX_NODE_PROGRESS_COUNTER + 1,
        )


def test_node_decorator_records_declared_secret_config_dependencies() -> None:
    plugin = Plugin(slug="example.secrets", title="Example secrets")
    declared = NodeSecretInput(
        name="api_key",
        config_dependencies=("base_url",),
        title="API key",
    )

    plugin.node(
        operator_id="example.secret",
        version=1,
        title="Secret example",
        secret_inputs=(declared,),
        required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
    )(SecretNode)

    assert plugin.nodes[0].secret_inputs == (declared,)


@pytest.mark.parametrize(
    ("name", "title", "message"),
    [
        ("ApiKey", "API key", "must start with a lowercase letter"),
        ("api-key", "API key", "must start with a lowercase letter"),
        ("api_key", "   ", "title must not be blank"),
    ],
)
def test_node_secret_input_requires_route_safe_name_and_nonblank_title(
    name: str,
    title: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        NodeSecretInput(name=name, title=title)


def test_node_decorator_rejects_missing_secret_config_dependency() -> None:
    plugin = Plugin(slug="example.secrets", title="Example secrets")

    with pytest.raises(PluginRegistrationError, match="missing config fields: model"):
        plugin.node(
            operator_id="example.secret",
            version=1,
            title="Secret example",
            secret_inputs=(
                NodeSecretInput(
                    name="api_key",
                    title="API key",
                    config_dependencies=("model",),
                ),
            ),
        )(SecretNode)


def test_http_egress_contract_requires_network_egress_capability() -> None:
    plugin = Plugin(slug="example.egress", title="Example egress")

    with pytest.raises(
        PluginRegistrationError, match="without requiring network.egress"
    ):
        plugin.node(
            operator_id="example.egress",
            version=1,
            title="Egress example",
            http_egress=NodeHttpEgressContract(
                configured_inputs=(NodeHttpEgressInput(config_field="base_url"),)
            ),
        )(SecretNode)


def test_http_egress_registration_records_the_contract() -> None:
    plugin = Plugin(slug="example.egress", title="Example egress")

    plugin.node(
        operator_id="example.egress",
        version=1,
        title="Egress example",
        required_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
        http_egress=NodeHttpEgressContract(
            configured_inputs=(NodeHttpEgressInput(config_field="base_url"),),
            dynamic_destinations=False,
        ),
    )(SecretNode)

    registration = plugin.nodes[0]
    assert registration.http_egress is not None
    assert registration.http_egress.configured_inputs == (
        NodeHttpEgressInput(config_field="base_url"),
    )


def test_http_egress_rejects_duplicate_or_missing_config_fields() -> None:
    plugin = Plugin(slug="example.egress", title="Example egress")
    capabilities = (PluginRuntimeCapability.NETWORK_EGRESS,)

    with pytest.raises(PluginRegistrationError, match="duplicate HTTP egress"):
        plugin.node(
            operator_id="example.dup",
            version=1,
            title="Duplicate",
            required_capabilities=capabilities,
            http_egress=NodeHttpEgressContract(
                configured_inputs=(
                    NodeHttpEgressInput(config_field="base_url"),
                    NodeHttpEgressInput(config_field="base_url"),
                )
            ),
        )(SecretNode)

    with pytest.raises(PluginRegistrationError, match="missing config fields: other"):
        plugin.node(
            operator_id="example.missing",
            version=1,
            title="Missing",
            required_capabilities=capabilities,
            http_egress=NodeHttpEgressContract(
                configured_inputs=(NodeHttpEgressInput(config_field="other"),)
            ),
        )(SecretNode)


def test_http_egress_rejects_more_than_eight_configured_fields() -> None:
    plugin = Plugin(slug="example.egress", title="Example egress")
    capabilities = (PluginRuntimeCapability.NETWORK_EGRESS,)

    with pytest.raises(PluginRegistrationError, match="more than 8"):
        plugin.node(
            operator_id="example.too-many",
            version=1,
            title="Too many",
            required_capabilities=capabilities,
            http_egress=NodeHttpEgressContract(
                configured_inputs=tuple(
                    NodeHttpEgressInput(config_field=f"url_{index}")
                    for index in range(9)
                )
            ),
        )(SecretNode)


@pytest.mark.asyncio
async def test_default_runtime_node_secret_resolver_fails_closed(
    tmp_path: Path,
) -> None:
    context = runtime_context(tmp_path)

    with pytest.raises(NodeSecretUnavailableError, match="unavailable"):
        await context.node_secrets.resolve_secret(
            workspace_id=WORKSPACE_ID,
            graph_id=None,
            graph_revision=None,
            node_id=None,
            name="api_key",
            dependencies={},
        )


def test_registry_reports_operator_and_artifact_collisions() -> None:
    artifact = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.value", 1),
        title="Example value",
    )
    first = Plugin(slug="example.first", title="First")
    first.node(operator_id="example.node", version=1, title="First node")(DefaultNode)
    first.register_artifact_type(artifact)

    conflicting_node = Plugin(slug="example.second", title="Second")
    conflicting_node.node(
        operator_id="example.node",
        version=1,
        title="Second node",
    )(ContextNode)

    registry = PluginRegistry()
    registry.install(first)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Plugin 'example.second' operator example.node@1 conflicts with "
            "plugin 'example.first'"
        ),
    ):
        registry.install(conflicting_node)

    conflicting_artifact = Plugin(slug="example.third", title="Third")
    conflicting_artifact.register_artifact_type(artifact)
    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Plugin 'example.third' artifact type example.value@1 is already installed"
        ),
    ):
        registry.install(conflicting_artifact)


def test_registry_freeze_requires_concrete_node_port_artifact_registration() -> None:
    artifact = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.unregistered", 1),
        title="Globally installed only",
    )
    owner = Plugin(slug="example.owner", title="Owner")
    owner.register_artifact_type(artifact)
    plugin = Plugin(slug="example.concrete-port", title="Concrete port")
    plugin.node(
        operator_id="example.concrete-port",
        version=1,
        title="Concrete port",
    )(ConcretePortNode)
    registry = PluginRegistry()
    registry.install(owner)
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "operator example.concrete-port@1 input port 'value' references "
            "artifact type example.unregistered@1, which is neither owned nor "
            "declared as an exact dependency"
        ),
    ):
        registry.freeze()


def test_registry_registers_artifact_conversions_across_plugin_boundaries() -> None:
    source = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.source", 1),
        title="Example source",
    )
    target = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.target", 1),
        title="Example target",
    )
    conversion = ArtifactConversion(
        key=ArtifactConversionKey("example.source_to_target", 1),
        source=source.key,
        target=target.key,
        source_type=int,
        target_type=str,
        title="Source to target",
        convert=_stringify_integer,
    )
    source_plugin = Plugin(slug="example.source", title="Source")
    source_plugin.register_artifact_type(source)
    target_plugin = Plugin(slug="example.target", title="Target")
    target_plugin.register_artifact_type(target)
    target_plugin.register_artifact_type_dependency(source)
    target_plugin.register_artifact_conversion(conversion)
    registry = PluginRegistry()

    registry.install(source_plugin)
    registry.install(target_plugin)
    registry.freeze()

    assert target_plugin.artifact_conversions == (conversion,)
    assert registry.artifact_conversions == (conversion,)
    assert registry.artifact_conversions[0].convert(7) == "7"


def test_artifact_conversion_requires_valid_identity_and_title() -> None:
    with pytest.raises(ValueError, match="id must not be blank"):
        ArtifactConversionKey("   ", 1)
    with pytest.raises(ValueError, match="version must be positive"):
        ArtifactConversionKey("example.invalid", 0)
    with pytest.raises(ValueError, match="title must not be blank"):
        ArtifactConversion(
            key=ArtifactConversionKey("example.invalid", 1),
            source=ArtifactTypeKey("example.source", 1),
            target=ArtifactTypeKey("example.target", 1),
            source_type=int,
            target_type=str,
            title="   ",
            convert=_stringify_integer,
        )


def test_plugin_and_registry_report_artifact_conversion_collisions() -> None:
    conversion = ArtifactConversion(
        key=ArtifactConversionKey("example.duplicate", 1),
        source=ArtifactTypeKey("example.source", 1),
        target=ArtifactTypeKey("example.target", 1),
        source_type=int,
        target_type=str,
        title="Duplicate",
        convert=_stringify_integer,
    )
    first = Plugin(slug="example.first-conversion", title="First conversion")
    first.register_artifact_conversion(conversion)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Plugin 'example.first-conversion' already declares artifact conversion "
            "example.duplicate@1"
        ),
    ):
        first.register_artifact_conversion(conversion)

    second = Plugin(slug="example.second-conversion", title="Second conversion")
    second.register_artifact_conversion(conversion)
    registry = PluginRegistry()
    registry.install(first)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Plugin 'example.second-conversion' artifact conversion "
            "example.duplicate@1 is already installed"
        ),
    ):
        registry.install(second)


@pytest.mark.parametrize(
    ("register_source", "register_target", "missing_endpoint"),
    [
        (False, True, "source"),
        (True, False, "target"),
    ],
)
def test_registry_freeze_rejects_conversion_with_missing_artifact_endpoint(
    register_source: bool,
    register_target: bool,
    missing_endpoint: str,
) -> None:
    source = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.source", 1),
        title="Example source",
    )
    target = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.target", 1),
        title="Example target",
    )
    conversion = ArtifactConversion(
        key=ArtifactConversionKey("example.incomplete", 1),
        source=source.key,
        target=target.key,
        source_type=int,
        target_type=str,
        title="Incomplete",
        convert=_stringify_integer,
    )
    plugin = Plugin(slug="example.incomplete", title="Incomplete")
    if register_source:
        plugin.register_artifact_type(source)
    if register_target:
        plugin.register_artifact_type(target)
    plugin.register_artifact_conversion(conversion)
    registry = PluginRegistry()
    registry.install(plugin)

    missing_type = source.key if missing_endpoint == "source" else target.key
    with pytest.raises(
        PluginRegistrationError,
        match=(
            f"artifact conversion example.incomplete@1 references {missing_endpoint} "
            f"artifact type {missing_type.id}@{missing_type.schema_version}, which "
            "is neither owned nor declared as an exact dependency"
        ),
    ):
        registry.freeze()


def test_plugin_artifact_dependencies_are_exact_and_disjoint_from_owned_types() -> None:
    artifact = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.shared", 1),
        title="Shared",
        payload_schema={"type": "string"},
    )
    plugin = Plugin(slug="example.consumer", title="Consumer")

    plugin.register_artifact_type_dependency(artifact)
    plugin.register_artifact_type_dependency(artifact)

    assert plugin.artifact_type_dependencies == (artifact,)

    with pytest.raises(
        PluginRegistrationError,
        match="declares different exact contracts for artifact type dependency",
    ):
        plugin.register_artifact_type_dependency(replace(artifact, title="Changed"))
    with pytest.raises(
        PluginRegistrationError,
        match="cannot both own and depend on artifact type example.shared@1",
    ):
        plugin.register_artifact_type(artifact)


def test_registry_freeze_accepts_exact_foreign_artifact_contract() -> None:
    artifact = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.shared", 1),
        title="Shared",
        payload_schema={"type": "string"},
    )
    owner = Plugin(slug="example.owner", title="Owner")
    owner.register_artifact_type(artifact)
    consumer = Plugin(slug="example.consumer", title="Consumer")
    consumer.register_artifact_type_dependency(artifact)
    registry = PluginRegistry()
    registry.install(owner)
    registry.install(consumer)

    registry.freeze()

    assert registry.artifact_types == (artifact,)
    assert registry.artifact_type_dependencies == (artifact,)


def test_registry_freeze_rejects_same_key_with_different_dependency_contracts() -> None:
    artifact = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.shared", 1),
        title="Shared",
        payload_schema={"type": "string"},
    )
    first = Plugin(slug="example.first", title="First")
    first.register_artifact_type_dependency(artifact)
    second = Plugin(slug="example.second", title="Second")
    second.register_artifact_type_dependency(replace(artifact, title="Changed"))
    registry = PluginRegistry()
    registry.install(first)
    registry.install(second)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Plugins 'example.first' and 'example.second' declare different exact "
            "contracts for artifact type example.shared@1"
        ),
    ):
        registry.freeze()


def test_registry_freeze_rejects_nominally_contiguous_runtime_type_mismatch() -> None:
    source = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.source", 1),
        title="Example source",
    )
    intermediate = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.intermediate", 1),
        title="Example intermediate",
    )
    target = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.target", 1),
        title="Example target",
    )
    source_to_intermediate = ArtifactConversion(
        key=ArtifactConversionKey("example.source_to_intermediate", 1),
        source=source.key,
        target=intermediate.key,
        source_type=int,
        target_type=bool,
        title="Source to intermediate",
        convert=_integer_is_positive,
    )
    intermediate_to_target = ArtifactConversion(
        key=ArtifactConversionKey("example.intermediate_to_target", 1),
        source=intermediate.key,
        target=target.key,
        source_type=int,
        target_type=str,
        title="Intermediate to target",
        convert=_stringify_integer,
    )
    plugin = Plugin(slug="example.non-composable", title="Non-composable")
    for artifact_type in (source, intermediate, target):
        plugin.register_artifact_type(artifact_type)
    plugin.register_artifact_conversion(source_to_intermediate)
    plugin.register_artifact_conversion(intermediate_to_target)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Artifact conversions example.source_to_intermediate@1 and "
            "example.intermediate_to_target@1 meet at example.intermediate@1 "
            "but have incompatible runtime types"
        ),
    ):
        registry.freeze()


def test_frozen_registry_rejects_late_installation() -> None:
    registry = PluginRegistry()
    registry.freeze()

    with pytest.raises(PluginRegistrationError, match="Plugin registry is frozen"):
        registry.install(Plugin(slug="example.late", title="Late"))


def test_registry_builds_default_and_context_factory_nodes(tmp_path: Path) -> None:
    plugin = Plugin(slug="example.builders", title="Builders")
    plugin.node(operator_id="example.default", version=1, title="Default")(DefaultNode)
    plugin.node(
        operator_id="example.context",
        version=1,
        title="Context",
        factory=lambda context: ContextNode(context.workspace),
    )(ContextNode)
    registry = PluginRegistry()
    registry.install(plugin)
    context = runtime_context(tmp_path)

    default_node = registry.build_node("example.default", 1, context)
    context_node = registry.build_node("example.context", 1, context)

    assert isinstance(default_node, DefaultNode)
    assert isinstance(context_node, ContextNode)
    assert context_node.workspace == tmp_path


def test_registry_looks_up_exact_node_registration() -> None:
    plugin = Plugin(slug="example.lookup", title="Lookup")
    plugin.node(
        operator_id="example.lookup",
        version=3,
        title="Lookup",
        cache_policy=NodeCachePolicy.EXACT,
    )(DefaultNode)
    registry = PluginRegistry()
    registry.install(plugin)

    registration = registry.node_registration("example.lookup", 3)

    assert registration is plugin.nodes[0]
    assert registration.cache_policy is NodeCachePolicy.EXACT
    with pytest.raises(
        UnknownOperatorError,
        match="Unknown operator 'example.lookup' at version 4",
    ):
        registry.node_registration("example.lookup", 4)


def test_missing_factory_error_preserves_plugin_and_operator_context(
    tmp_path: Path,
) -> None:
    plugin = Plugin(slug="example.builders", title="Builders")
    plugin.node(operator_id="example.context", version=1, title="Context")(ContextNode)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Plugin 'example.builders' operator example.context@1 requires an "
            "explicit node factory"
        ),
    ):
        registry.build_node("example.context", 1, runtime_context(tmp_path))


def test_registry_freeze_derives_nested_scalar_projections_from_pydantic_refs() -> None:
    text = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.text", 1),
        title="Text",
        payload_schema={
            "properties": {"value": {"title": "Value", "type": "string"}},
            "type": "object",
        },
        materialized_json_type="string",
    )
    integer = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.integer", 1),
        title="Integer",
        materialized_json_type="integer",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.payload", 1),
        title="Payload",
        payload_schema=cast(JsonObject, ProjectionPayload.model_json_schema()),
    )
    plugin = Plugin(slug="example.projections", title="Projections")
    for artifact_type in (text, integer, payload):
        plugin.register_artifact_type(artifact_type)
    registry = PluginRegistry()
    registry.install(plugin)

    registry.freeze()

    registered = {spec.key: spec for spec in registry.artifact_types}
    assert registered[text.key].field_projections == ()
    assert registered[payload.key] is not payload
    assert payload.field_projections == ()
    assert registered[payload.key].field_projections == (
        ArtifactFieldProjection(
            path=("customer", "age"),
            target=integer.key,
            title="Customer · Age",
        ),
        ArtifactFieldProjection(
            path=("customer", "name"),
            target=text.key,
            title="Customer · Name",
        ),
        ArtifactFieldProjection(
            path=("label",),
            target=text.key,
            title="Label",
        ),
        ArtifactFieldProjection(
            path=("quantity",),
            target=integer.key,
            title="Quantity",
        ),
    )


def test_registry_freeze_keeps_explicit_projection_for_derived_path() -> None:
    text = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.text", 1),
        title="Text",
        materialized_json_type="string",
    )
    integer = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.integer", 1),
        title="Integer",
        materialized_json_type="integer",
    )
    explicit = ArtifactFieldProjection(
        path=("customer", "name"),
        target=text.key,
        title="Explicit customer name",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.override", 1),
        title="Override",
        payload_schema=cast(JsonObject, ProjectionPayload.model_json_schema()),
        field_projections=(explicit,),
    )
    plugin = Plugin(slug="example.override", title="Override")
    for artifact_type in (text, integer, payload):
        plugin.register_artifact_type(artifact_type)
    registry = PluginRegistry()
    registry.install(plugin)

    registry.freeze()

    expanded = next(spec for spec in registry.artifact_types if spec.key == payload.key)
    matching = [
        projection
        for projection in expanded.field_projections
        if projection.path == explicit.path
    ]
    assert matching == [explicit]


def test_registry_freeze_allows_explicit_plugin_owned_object_semantics() -> None:
    plugin_owned_target = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.customer", 1),
        title="Customer",
    )
    explicit = ArtifactFieldProjection(
        path=("customer",),
        target=plugin_owned_target.key,
        title="Customer",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.plugin-owned-projection", 1),
        title="Plugin-owned projection",
        payload_schema=cast(JsonObject, ProjectionPayload.model_json_schema()),
        field_projections=(explicit,),
    )
    plugin = Plugin(slug="example.plugin-owned", title="Plugin-owned")
    plugin.register_artifact_type(plugin_owned_target)
    plugin.register_artifact_type(payload)
    registry = PluginRegistry()
    registry.install(plugin)

    registry.freeze()

    expanded = next(spec for spec in registry.artifact_types if spec.key == payload.key)
    assert explicit in expanded.field_projections


@pytest.mark.parametrize(
    "property_schema",
    [
        pytest.param({}, id="schema-less"),
        pytest.param({"type": "custom"}, id="unknown-type"),
    ],
)
def test_registry_freeze_allows_canonical_target_for_unknown_schema_node(
    property_schema: JsonObject,
) -> None:
    text = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.text", 1),
        title="Text",
        materialized_json_type="string",
    )
    explicit = ArtifactFieldProjection(
        path=("value",),
        target=text.key,
        title="Value",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.unknown-projection", 1),
        title="Unknown projection",
        payload_schema={
            "properties": {"value": property_schema},
            "type": "object",
        },
        field_projections=(explicit,),
    )
    plugin = Plugin(slug="example.unknown-projection", title="Unknown projection")
    plugin.register_artifact_type(text)
    plugin.register_artifact_type(payload)
    registry = PluginRegistry()
    registry.install(plugin)

    registry.freeze()

    expanded = next(spec for spec in registry.artifact_types if spec.key == payload.key)
    assert explicit in expanded.field_projections


def test_registry_freeze_rejects_empty_explicit_projection_path() -> None:
    target = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.target", 1),
        title="Target",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.empty-projection", 1),
        title="Empty projection",
        field_projections=(
            ArtifactFieldProjection(
                path=(),
                target=target.key,
                title="Empty",
            ),
        ),
    )
    plugin = Plugin(slug="example.empty-projection", title="Empty projection")
    plugin.register_artifact_type(target)
    plugin.register_artifact_type(payload)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Artifact type example.empty-projection@1 declares a field projection "
            "with an empty path"
        ),
    ):
        registry.freeze()


def test_registry_freeze_rejects_duplicate_explicit_projection_path() -> None:
    target = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.target", 1),
        title="Target",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.duplicate-projection", 1),
        title="Duplicate projection",
        field_projections=(
            ArtifactFieldProjection(
                path=("value",),
                target=target.key,
                title="First",
            ),
            ArtifactFieldProjection(
                path=("value",),
                target=target.key,
                title="Second",
            ),
        ),
    )
    plugin = Plugin(
        slug="example.duplicate-projection",
        title="Duplicate projection",
    )
    plugin.register_artifact_type(target)
    plugin.register_artifact_type(payload)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Artifact type example.duplicate-projection@1 declares duplicate field "
            "projection path 'value'"
        ),
    ):
        registry.freeze()


def test_registry_freeze_rejects_explicit_projection_to_missing_target() -> None:
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.missing-projection-target", 1),
        title="Missing projection target",
        field_projections=(
            ArtifactFieldProjection(
                path=("value",),
                target=ArtifactTypeKey("example.missing", 1),
                title="Missing",
            ),
        ),
    )
    plugin = Plugin(
        slug="example.missing-projection-target",
        title="Missing projection target",
    )
    plugin.register_artifact_type(payload)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "artifact type example.missing-projection-target@1 field projection "
            "'value' targets artifact type example.missing@1, which is neither "
            "owned nor declared as an exact dependency"
        ),
    ):
        registry.freeze()


def test_registry_freeze_rejects_explicit_canonical_scalar_type_mismatch() -> None:
    text = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.text", 1),
        title="Text",
        materialized_json_type="string",
    )
    integer = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.integer", 1),
        title="Integer",
        materialized_json_type="integer",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.mismatched-projection", 1),
        title="Mismatched projection",
        payload_schema=cast(JsonObject, ProjectionPayload.model_json_schema()),
        field_projections=(
            ArtifactFieldProjection(
                path=("customer", "name"),
                target=integer.key,
                title="Customer name",
            ),
        ),
    )
    plugin = Plugin(
        slug="example.mismatched-projection",
        title="Mismatched projection",
    )
    for artifact_type in (text, integer, payload):
        plugin.register_artifact_type(artifact_type)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Artifact type example.mismatched-projection@1 field projection "
            "'customer.name' targets scalar.integer@1, which materializes JSON "
            "Schema 'integer', but the projected field is 'string'"
        ),
    ):
        registry.freeze()


@pytest.mark.parametrize(
    "schema_type",
    ["array", "boolean", "null", "number", "object"],
)
def test_registry_freeze_rejects_canonical_scalar_for_known_schema_node(
    schema_type: str,
) -> None:
    text = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.text", 1),
        title="Text",
        materialized_json_type="string",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.non-scalar-projection", 1),
        title="Non-scalar projection",
        payload_schema={
            "properties": {"value": {"type": schema_type}},
            "type": "object",
        },
        field_projections=(
            ArtifactFieldProjection(
                path=("value",),
                target=text.key,
                title="Value",
            ),
        ),
    )
    plugin = Plugin(
        slug="example.non-scalar-projection",
        title="Non-scalar projection",
    )
    plugin.register_artifact_type(text)
    plugin.register_artifact_type(payload)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Artifact type example.non-scalar-projection@1 field projection 'value' "
            "targets scalar.text@1, which materializes JSON Schema 'string', but "
            f"the projected field is {schema_type!r}"
        ),
    ):
        registry.freeze()


def test_registry_freeze_rejects_duplicate_canonical_scalar_targets() -> None:
    first = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.first-text", 1),
        title="First text",
        materialized_json_type="string",
    )
    second = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.second-text", 1),
        title="Second text",
        materialized_json_type="string",
    )
    plugin = Plugin(slug="example.duplicate-scalars", title="Duplicate scalars")
    plugin.register_artifact_type(first)
    plugin.register_artifact_type(second)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Artifact types scalar.first-text@1 and scalar.second-text@1 both "
            "declare the canonical JSON Schema 'string' scalar target"
        ),
    ):
        registry.freeze()


def test_registry_freeze_rejects_cyclic_local_schema_ref() -> None:
    text = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.text", 1),
        title="Text",
        materialized_json_type="string",
    )
    recursive = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.recursive", 1),
        title="Recursive",
        payload_schema={
            "$defs": {
                "Branch": {
                    "properties": {
                        "child": {"$ref": "#/$defs/Branch"},
                        "name": {"title": "Name", "type": "string"},
                    },
                    "title": "Branch",
                    "type": "object",
                }
            },
            "properties": {"branch": {"$ref": "#/$defs/Branch"}},
            "type": "object",
        },
    )
    plugin = Plugin(slug="example.recursive", title="Recursive")
    plugin.register_artifact_type(text)
    plugin.register_artifact_type(recursive)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Artifact type example.recursive@1 payload schema contains cyclic "
            "local reference '#/\\$defs/Branch' at path 'branch.child'"
        ),
    ):
        registry.freeze()


def test_registry_freeze_bounds_derived_projection_count() -> None:
    text = ArtifactTypeSpec(
        key=ArtifactTypeKey("scalar.text", 1),
        title="Text",
        materialized_json_type="string",
    )
    payload = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.too-many-fields", 1),
        title="Too many fields",
        payload_schema={
            "properties": {
                f"value_{index:04d}": {"type": "string"} for index in range(1025)
            },
            "type": "object",
        },
    )
    plugin = Plugin(slug="example.too-many-fields", title="Too many fields")
    plugin.register_artifact_type(text)
    plugin.register_artifact_type(payload)
    registry = PluginRegistry()
    registry.install(plugin)

    with pytest.raises(
        PluginRegistrationError,
        match=(
            "Artifact type example.too-many-fields@1 payload schema expands beyond "
            "the maximum of 1024 field projections"
        ),
    ):
        registry.freeze()
