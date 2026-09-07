import asyncio
from collections.abc import Mapping
from pathlib import Path
from threading import get_ident
from typing import Annotated, AsyncIterator, Callable, Generator, cast
from uuid import UUID

import pytest
from pydantic import BaseModel, Field, ValidationError

from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactTypeKey,
    ArtifactTypeSpec,
    InMemoryUnitOfWork,
    NodeOutput,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.nodes import InPort, NodeExecutionContext, OutPort, PortShape
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    Plugin,
    PluginRegistrationError,
    PluginRegistry,
    PluginRuntimeContext,
)
from grafy_storage import LocalFileObjectStore


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000941")
CUSTOM_VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("example.custom", 1),
    title="Custom value",
)


class CustomValue(BaseModel):
    label: str


class RecordingProgressReporter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        del context, current, total
        self.messages.append(message)


def runtime_context(tmp_path: Path) -> PluginRuntimeContext:
    return PluginRuntimeContext(
        workspace=tmp_path,
        uploads_dir=tmp_path / "uploads",
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="test-artifacts",
    )


@pytest.mark.asyncio
async def test_callable_node_registers_and_executes_a_typed_python_function(
    tmp_path: Path,
) -> None:
    plugin = Plugin(slug="example.callables", title="Callable examples")
    plugin.register_artifact_type_dependency(TEXT_VALUE)

    async def greet(name: str, *, prefix: str = "Hello") -> str:
        return f"{prefix}, {name}"

    decorated = plugin.callable_node(
        operator_id="example.greet",
        version=1,
        title="Greet",
    )(greet)
    registry = PluginRegistry()
    registry.install(plugin)
    registry.freeze()
    registration = registry.node_registration("example.greet", 1)
    node = registry.build_node("example.greet", 1, runtime_context(tmp_path))

    config = registration.node_class.config_contract.model(prefix="Welcome")
    inputs = registration.node_class.input_contract.model(name="Ada")
    output = await node.run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID),
        config,
        inputs,
    )

    assert decorated is greet
    assert output.model_dump() == {"result": "Welcome, Ada"}


@pytest.mark.asyncio
async def test_callable_node_maps_positional_parameters_to_inputs_and_keyword_only_parameters_to_config(
    tmp_path: Path,
) -> None:
    plugin = Plugin(slug="example.signatures", title="Signature examples")
    plugin.register_artifact_type_dependency(TEXT_VALUE)
    plugin.register_artifact_type_dependency(INTEGER_VALUE)

    async def render(left: str, /, count: int, *, suffix: str = "!") -> str:
        return f"{left}:{count}{suffix}"

    plugin.callable_node(
        operator_id="example.render",
        version=1,
        title="Render",
    )(render)
    registration = plugin.nodes[0]
    node = registration.node_class()
    config_model = registration.node_class.config_contract.model
    input_model = registration.node_class.input_contract.model

    output = await node.run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID),
        config_model(suffix="?"),
        input_model(left="items", count=3),
    )

    assert set(registration.node_class.input_contract.ports) == {"left", "count"}
    assert (
        registration.node_class.input_contract.ports["left"].accepts == TEXT_VALUE.key
    )
    assert (
        registration.node_class.input_contract.ports["count"].accepts
        == INTEGER_VALUE.key
    )
    assert config_model.model_fields["suffix"].default == "!"
    assert output.model_dump() == {"result": "items:3?"}


def test_callable_node_preserves_config_defaults_and_annotated_constraints() -> None:
    plugin = Plugin(slug="example.config", title="Config examples")
    plugin.register_artifact_type_dependency(TEXT_VALUE)

    async def truncate(
        text: str,
        *,
        limit: Annotated[int, Field(gt=0, le=100)] = 10,
    ) -> str:
        return text[:limit]

    plugin.callable_node(
        operator_id="example.truncate",
        version=2,
        title="Truncate",
    )(truncate)
    config_model = plugin.nodes[0].node_class.config_contract.model

    assert config_model().limit == 10
    assert config_model(limit="5").limit == 5
    with pytest.raises(ValidationError):
        config_model(limit=0)
    schema = config_model.model_json_schema()["properties"]["limit"]
    assert schema["exclusiveMinimum"] == 0
    assert schema["maximum"] == 100


def test_callable_node_rejects_config_that_cannot_publish_a_json_schema() -> None:
    plugin = Plugin(slug="example.schema", title="Schema examples")

    async def transform(
        value: str,
        *,
        callback: Callable[[str], str],
    ) -> str:
        return callback(value)

    with pytest.raises(PluginRegistrationError, match="example.transform"):
        plugin.callable_node(
            operator_id="example.transform",
            version=1,
            title="Transform",
        )(transform)

    assert plugin.nodes == ()


@pytest.mark.parametrize(
    ("annotation", "expected_artifact", "expected_shape", "allows_none"),
    [
        (str, TEXT_VALUE.key, PortShape.ONE, False),
        (int, INTEGER_VALUE.key, PortShape.ONE, False),
        (list[str], TEXT_VALUE.key, PortShape.MANY, False),
        (list[int], INTEGER_VALUE.key, PortShape.MANY, False),
        (str | None, TEXT_VALUE.key, PortShape.ONE, True),
        (int | None, INTEGER_VALUE.key, PortShape.ONE, True),
        (list[str] | None, TEXT_VALUE.key, PortShape.MANY, True),
        (list[int] | None, INTEGER_VALUE.key, PortShape.MANY, True),
    ],
)
def test_callable_node_infers_scalar_and_collection_input_ports(
    annotation: object,
    expected_artifact: ArtifactTypeKey,
    expected_shape: PortShape,
    allows_none: bool,
) -> None:
    plugin = Plugin(slug="example.inference", title="Inference examples")

    async def identity(value: str) -> str:
        return value

    identity.__annotations__["value"] = annotation
    plugin.callable_node(
        operator_id="example.identity",
        version=1,
        title="Identity",
    )(identity)
    port = plugin.nodes[0].node_class.input_contract.ports["value"]

    assert port.accepts == expected_artifact
    assert port.shape is expected_shape
    assert port.allows_none is allows_none


def test_callable_node_accepts_nullable_input_only_with_a_none_default() -> None:
    plugin = Plugin(slug="example.nullable", title="Nullable examples")

    async def describe(value: str | None = None) -> str:
        return value or "missing"

    plugin.callable_node(
        operator_id="example.describe",
        version=1,
        title="Describe",
    )(describe)
    registration = plugin.nodes[0]
    input_model = registration.node_class.input_contract.model
    port = registration.node_class.input_contract.ports["value"]

    assert input_model().value is None
    assert port.required is False
    assert port.allows_none is True


def test_callable_node_uses_explicit_ports_for_custom_python_types() -> None:
    plugin = Plugin(slug="example.custom", title="Custom examples")
    plugin.register_artifact_type_dependency(CUSTOM_VALUE)

    async def rename(
        value: Annotated[CustomValue, InPort(CUSTOM_VALUE)],
        *,
        label: str,
    ) -> Annotated[CustomValue, OutPort(CUSTOM_VALUE)]:
        return CustomValue(label=f"{label}: {value.label}")

    plugin.callable_node(
        operator_id="example.rename",
        version=1,
        title="Rename",
        output_name="renamed",
    )(rename)
    registration = plugin.nodes[0]

    assert registration.node_class.input_contract.ports["value"].accepts == (
        CUSTOM_VALUE.key
    )
    assert registration.node_class.output_contract.ports["renamed"].produces == (
        CUSTOM_VALUE.key
    )


def test_callable_node_forwards_runtime_policy_without_registering_artifacts() -> None:
    plugin = Plugin(slug="example.policy", title="Policy examples")
    egress = NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="base_url"),)
    )

    async def fetch(name: str, *, base_url: str) -> str:
        return f"{base_url}/{name}"

    plugin.callable_node(
        operator_id="example.fetch",
        version=1,
        title="Fetch",
        http_egress=egress,
        required_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
        cache_policy=NodeCachePolicy.EXACT,
    )(fetch)
    registration = plugin.nodes[0]

    assert registration.http_egress is egress
    assert registration.required_capabilities == (
        PluginRuntimeCapability.NETWORK_EGRESS,
    )
    assert registration.cache_policy is NodeCachePolicy.EXACT
    assert plugin.artifact_types == ()
    assert plugin.artifact_type_dependencies == ()


def test_callable_node_requires_explicit_artifact_dependencies_for_catalogs() -> None:
    plugin = Plugin(slug="example.dependencies", title="Dependency examples")

    async def echo(value: str) -> str:
        return value

    plugin.callable_node(
        operator_id="example.echo",
        version=1,
        title="Echo",
    )(echo)

    with pytest.raises(ValidationError, match="scalar.text@1"):
        PluginCatalogManifest.from_plugin(plugin)

    assert plugin.artifact_type_dependencies == ()


def test_callable_node_catalog_is_stable_when_the_python_function_is_renamed() -> None:
    first = Plugin(slug="example.stable", title="Stable examples")
    second = Plugin(slug="example.stable", title="Stable examples")
    for plugin in (first, second):
        plugin.register_artifact_type_dependency(TEXT_VALUE)

    async def old_name(value: str) -> str:
        return value

    async def new_name(value: str) -> str:
        return value

    for plugin, function in ((first, old_name), (second, new_name)):
        plugin.callable_node(
            operator_id="example.stable.echo",
            version=3,
            title="Echo",
        )(function)

    first_node = first.nodes[0].node_class
    second_node = second.nodes[0].node_class

    assert first_node.config_contract.model.__name__ == (
        second_node.config_contract.model.__name__
    )
    assert first_node.input_contract.model.__name__ == (
        second_node.input_contract.model.__name__
    )
    assert first_node.output_contract.model.__name__ == (
        second_node.output_contract.model.__name__
    )
    assert PluginCatalogManifest.from_plugin(
        first
    ) == PluginCatalogManifest.from_plugin(second)


@pytest.mark.asyncio
async def test_callable_node_runs_sync_functions_off_the_event_loop(
    tmp_path: Path,
) -> None:
    plugin = Plugin(slug="example.sync", title="Sync examples")
    plugin.register_artifact_type_dependency(INTEGER_VALUE)
    event_loop = asyncio.get_running_loop()
    event_loop_thread = get_ident()

    async def heartbeat() -> None:
        await asyncio.sleep(0)

    def worker(value: int) -> int:
        asyncio.run_coroutine_threadsafe(heartbeat(), event_loop).result(timeout=1)
        return get_ident() + value - value

    plugin.callable_node(
        operator_id="example.worker",
        version=1,
        title="Worker",
    )(worker)
    registration = plugin.nodes[0]
    node = PluginRegistry()
    node.install(plugin)
    built = node.build_node("example.worker", 1, runtime_context(tmp_path))
    inputs = registration.node_class.input_contract.model(value=7)
    config = registration.node_class.config_contract.model()

    output = await built.run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID), config, inputs
    )

    assert output.result != event_loop_thread


@pytest.mark.asyncio
async def test_callable_node_passes_context_and_async_cancellation_through(
    tmp_path: Path,
) -> None:
    plugin = Plugin(slug="example.async", title="Async examples")
    plugin.register_artifact_type_dependency(TEXT_VALUE)
    entered = asyncio.Event()
    cleaned_up = asyncio.Event()
    seen_contexts: list[NodeExecutionContext] = []

    async def waiting(context: NodeExecutionContext, value: str) -> str:
        seen_contexts.append(context)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()
        return value

    plugin.callable_node(
        operator_id="example.waiting",
        version=1,
        title="Waiting",
    )(waiting)
    registration = plugin.nodes[0]
    registry = PluginRegistry()
    registry.install(plugin)
    built = registry.build_node("example.waiting", 1, runtime_context(tmp_path))
    context = NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="waiting")
    task = asyncio.create_task(
        built.run(
            context,
            registration.node_class.config_contract.model(),
            registration.node_class.input_contract.model(value="pending"),
        )
    )
    await entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert seen_contexts == [context]
    assert cleaned_up.is_set()


@pytest.mark.asyncio
async def test_callable_node_context_can_report_progress(tmp_path: Path) -> None:
    plugin = Plugin(slug="example.progress", title="Progress examples")
    plugin.register_artifact_type_dependency(TEXT_VALUE)

    async def announce(context: NodeExecutionContext, value: str) -> str:
        await context.progress("Callable is running")
        return value

    plugin.callable_node(
        operator_id="example.announce",
        version=1,
        title="Announce",
    )(announce)
    registration = plugin.nodes[0]
    registry = PluginRegistry()
    registry.install(plugin)
    built = registry.build_node("example.announce", 1, runtime_context(tmp_path))
    reporter = RecordingProgressReporter()

    await built.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            progress_reporter=reporter,
        ),
        registration.node_class.config_contract.model(),
        registration.node_class.input_contract.model(value="done"),
    )

    assert reporter.messages == ["Callable is running"]


@pytest.mark.asyncio
async def test_callable_node_validates_return_values_strictly(tmp_path: Path) -> None:
    plugin = Plugin(slug="example.outputs", title="Output examples")
    plugin.register_artifact_type_dependency(TEXT_VALUE)

    async def broken(value: str) -> str:
        del value
        return 42  # type: ignore[return-value]

    plugin.callable_node(
        operator_id="example.broken",
        version=1,
        title="Broken",
    )(broken)
    registration = plugin.nodes[0]
    registry = PluginRegistry()
    registry.install(plugin)
    built = registry.build_node("example.broken", 1, runtime_context(tmp_path))

    with pytest.raises(ValidationError, match="result"):
        await built.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID),
            registration.node_class.config_contract.model(),
            registration.node_class.input_contract.model(value="ignored"),
        )


def test_callable_node_rejects_invalid_input_defaults() -> None:
    async def non_null_default(value: str = "default") -> str:
        return value

    async def none_default_on_non_nullable(value: str = None) -> str:  # type: ignore[assignment]
        return value

    for function in (non_null_default, none_default_on_non_nullable):
        plugin = Plugin(slug="example.defaults", title="Default examples")

        with pytest.raises(PluginRegistrationError, match="example.invalid-default"):
            plugin.callable_node(
                operator_id="example.invalid-default",
                version=1,
                title="Invalid default",
            )(function)

        assert plugin.nodes == ()


def test_callable_node_rejects_field_info_as_a_config_default() -> None:
    plugin = Plugin(slug="example.field-default", title="Field default examples")

    async def invalid(value: str, *, limit: int = Field(gt=0)) -> str:  # type: ignore[assignment]
        return value[:limit]

    with pytest.raises(PluginRegistrationError, match="example.field-default"):
        plugin.callable_node(
            operator_id="example.field-default",
            version=1,
            title="Invalid field default",
        )(invalid)

    assert plugin.nodes == ()


def test_callable_node_rejects_a_config_default_that_violates_its_constraints() -> None:
    plugin = Plugin(slug="example.invalid-config", title="Invalid config examples")

    async def invalid(
        value: str,
        *,
        limit: Annotated[int, Field(gt=0)] = 0,
    ) -> str:
        return value[:limit]

    with pytest.raises(PluginRegistrationError, match="example.invalid-config"):
        plugin.callable_node(
            operator_id="example.invalid-config",
            version=1,
            title="Invalid config",
        )(invalid)

    assert plugin.nodes == ()


def test_callable_node_rejects_untyped_open_ended_and_generator_signatures() -> None:
    async def missing_parameter_hint(  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        value,  # type: ignore[no-untyped-def]
    ) -> str:
        return str(value)  # pyright: ignore[reportUnknownArgumentType]

    async def missing_return_hint(value: str):  # type: ignore[no-untyped-def]
        return value

    async def varargs(*values: str) -> str:
        return "".join(values)

    async def kwargs(**values: str) -> str:
        return "".join(values.values())

    def generator(value: str) -> Generator[str, None, None]:
        yield value

    async def async_generator(value: str) -> AsyncIterator[str]:
        yield value

    functions = cast(
        tuple[Callable[..., object], ...],
        (
            missing_parameter_hint,
            missing_return_hint,
            varargs,
            kwargs,
            generator,
            async_generator,
        ),
    )
    for function in functions:
        plugin = Plugin(slug="example.invalid", title="Invalid examples")

        with pytest.raises(PluginRegistrationError, match="example.invalid"):
            plugin.callable_node(
                operator_id="example.invalid",
                version=1,
                title="Invalid",
            )(function)

        assert plugin.nodes == ()


def test_callable_node_rejects_ambiguous_inferred_outputs() -> None:
    async def no_output(value: str) -> None:
        del value

    async def tuple_output(value: str) -> tuple[str, str]:
        return value, value

    async def mapping_output(value: str) -> Mapping[str, str]:
        return {"value": value}

    async def legacy_output(value: str) -> NodeOutput:
        del value
        return NodeOutput()

    functions: tuple[Callable[..., object], ...] = (
        no_output,
        tuple_output,
        mapping_output,
        legacy_output,
    )
    for function in functions:
        plugin = Plugin(slug="example.outputs", title="Output examples")

        with pytest.raises(PluginRegistrationError, match="example.ambiguous"):
            plugin.callable_node(
                operator_id="example.ambiguous",
                version=1,
                title="Ambiguous",
            )(function)

        assert plugin.nodes == ()


def test_callable_node_rejects_reserved_generated_field_names() -> None:
    async def model_dump(model_dump: str) -> str:
        return model_dump

    async def model_config(model_config: str) -> str:
        return model_config

    async def _private(_private: str) -> str:
        return _private

    functions: tuple[Callable[..., object], ...] = (
        model_dump,
        model_config,
        _private,
    )
    for function in functions:
        plugin = Plugin(slug="example.names", title="Name examples")

        with pytest.raises(PluginRegistrationError, match="example.invalid-name"):
            plugin.callable_node(
                operator_id="example.invalid-name",
                version=1,
                title="Invalid name",
            )(function)

        assert plugin.nodes == ()


def test_callable_node_rejects_alias_metadata() -> None:
    aliases = (
        Field(alias="other"),
        Field(validation_alias="other"),
        Field(serialization_alias="other"),
    )
    for metadata in aliases:
        plugin = Plugin(slug="example.aliases", title="Alias examples")

        async def aliased(value: str) -> str:
            return value

        aliased.__annotations__["value"] = Annotated[str, metadata]

        with pytest.raises(PluginRegistrationError, match="example.aliased"):
            plugin.callable_node(
                operator_id="example.aliased",
                version=1,
                title="Aliased",
            )(aliased)

        assert plugin.nodes == ()


def test_callable_node_rejects_wrong_or_duplicate_input_port_markers() -> None:
    parameter_annotations = (
        Annotated[str, OutPort(TEXT_VALUE)],
        Annotated[str, InPort(TEXT_VALUE), InPort(TEXT_VALUE)],
    )
    for parameter_annotation in parameter_annotations:
        plugin = Plugin(slug="example.markers", title="Marker examples")

        async def marked(value: str) -> str:
            return value

        marked.__annotations__["value"] = parameter_annotation

        with pytest.raises(PluginRegistrationError, match="example.marked"):
            plugin.callable_node(
                operator_id="example.marked",
                version=1,
                title="Marked",
            )(marked)

        assert plugin.nodes == ()


def test_callable_node_rejects_wrong_duplicate_or_nullable_output_contracts() -> None:
    return_annotations = (
        Annotated[str, InPort(TEXT_VALUE)],
        Annotated[str, OutPort(TEXT_VALUE), OutPort(TEXT_VALUE)],
        str | None,
        list[str | None],
    )
    for return_annotation in return_annotations:
        plugin = Plugin(slug="example.return-markers", title="Return marker examples")

        async def marked(value: str) -> str:
            return value

        marked.__annotations__["return"] = return_annotation

        with pytest.raises(PluginRegistrationError, match="example.marked-return"):
            plugin.callable_node(
                operator_id="example.marked-return",
                version=1,
                title="Marked return",
            )(marked)

        assert plugin.nodes == ()


def test_callable_node_rejects_input_markers_on_keyword_only_config() -> None:
    plugin = Plugin(slug="example.config-marker", title="Config marker examples")

    async def marked(
        value: str,
        *,
        label: Annotated[str, InPort(TEXT_VALUE)] = "label",
    ) -> str:
        return f"{label}: {value}"

    with pytest.raises(PluginRegistrationError, match="example.config-marker"):
        plugin.callable_node(
            operator_id="example.config-marker",
            version=1,
            title="Config marker",
        )(marked)

    assert plugin.nodes == ()


def test_callable_node_rejects_invalid_output_names() -> None:
    async def echo(value: str) -> str:
        return value

    for output_name in ("", "_result", "model_dump", "not valid"):
        plugin = Plugin(slug="example.output-name", title="Output name examples")

        with pytest.raises(PluginRegistrationError, match="example.output-name"):
            plugin.callable_node(
                operator_id="example.output-name",
                version=1,
                title="Output name",
                output_name=output_name,
            )(echo)

        assert plugin.nodes == ()


def test_callable_node_rejects_context_outside_the_exact_first_position() -> None:
    async def context_after_input(
        value: str,
        context: NodeExecutionContext,
    ) -> str:
        del context
        return value

    async def defaulted_context(
        context: NodeExecutionContext = NodeExecutionContext(workspace_id=WORKSPACE_ID),
    ) -> str:
        return str(context.workspace_id)

    async def annotated_context(
        context: Annotated[
            NodeExecutionContext,
            Field(description="Runtime context"),
        ],
        value: str,
    ) -> str:
        del context
        return value

    async def keyword_context(
        value: str,
        *,
        context: NodeExecutionContext,
    ) -> str:
        del context
        return value

    functions: tuple[Callable[..., object], ...] = (
        context_after_input,
        defaulted_context,
        annotated_context,
        keyword_context,
    )
    for function in functions:
        plugin = Plugin(slug="example.context", title="Context examples")

        with pytest.raises(PluginRegistrationError, match="example.bad-context"):
            plugin.callable_node(
                operator_id="example.bad-context",
                version=1,
                title="Bad context",
            )(function)

        assert plugin.nodes == ()
