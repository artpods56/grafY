from collections.abc import Mapping
from hashlib import sha256
from typing import Annotated, cast, final, override

from pydantic import Field, JsonValue, StrictInt, StrictStr

from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    PortShape,
    UserFacingNodeError,
)
from grafy_core.plugins import (
    NodeCachePolicy,
    PluginRuntimeContext,
    PluginUnitOfWorkPort,
)

from grafy_plugin_python.code import (
    MAX_CODE_LENGTH,
    CodeContract,
    CodeError,
    Context,
    LoadedCode,
    ParamsError,
    inspect_code,
    load_code,
    port_types,
)
from grafy_plugin_python.declaration import PORT_ARTIFACT_TYPES, PYTHON


PORT_TYPES = port_types(PORT_ARTIFACT_TYPES)


class PythonTransformConfig(NodeConfig):
    code: StrictStr = Field(
        min_length=1,
        max_length=MAX_CODE_LENGTH,
        description="Applied Python code: an optional Params class and transform.",
    )
    code_sha256: StrictStr = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the applied code, checked before every run.",
    )
    input_shape: PortShape = Field(
        default=PortShape.ONE,
        description="Whether the data input is one value or a sequence.",
    )
    output_shape: PortShape = Field(
        default=PortShape.ONE,
        description="Whether transform returns one value or a sequence.",
    )
    params_schema: dict[str, JsonValue] | None = Field(
        default=None,
        description="JSON Schema of the Params class, derived at Apply.",
    )
    params: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue],
        description="Values for the Params class.",
    )
    preset_id: StrictStr | None = Field(
        default=None,
        description="Preset this node was copied from, if any.",
    )
    preset_version: StrictInt | None = Field(default=None, ge=1)


class PythonTransformInput(NodeInput):
    input: Annotated[
        ArtifactRef | ArtifactRefSequence,
        InPort(ArtifactTypeVariable("input"), shape_field="input_shape"),
        Field(description="The value passed to the data parameter of transform."),
    ]


class PythonTransformOutput(NodeOutput):
    output: Annotated[
        JsonValue,
        OutPort(ArtifactTypeVariable("output"), shape_field="output_shape"),
        Field(description="The value transform returns."),
    ]


def build_python_transform_node(context: PluginRuntimeContext) -> "PythonTransformNode":
    return PythonTransformNode(context.uow)


@PYTHON.node(
    operator_id="python.transform",
    version=1,
    title="Python",
    factory=build_python_transform_node,
    cache_policy=NodeCachePolicy.EXACT,
    # The node library lists Python presets, including a blank one, instead.
    listed=False,
)
@final
class PythonTransformNode(
    Node[PythonTransformConfig, PythonTransformInput, PythonTransformOutput]
):
    """Runs applied Python code on one input. Transforms must be deterministic."""

    def __init__(self, uow: PluginUnitOfWorkPort) -> None:
        self._uow = uow

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: PythonTransformConfig,
        inputs: PythonTransformInput,
        /,
    ) -> PythonTransformOutput:
        if sha256(config.code.encode("utf-8")).hexdigest() != config.code_sha256:
            raise UserFacingNodeError(
                "The code changed after it was applied. Apply it again."
            )
        try:
            loaded = load_code(config.code, PORT_TYPES)
        except CodeError as exc:
            raise UserFacingNodeError(f"Line {exc.line}: {exc.message}") from exc
        _require_applied(loaded.contract, config, context.artifact_type_bindings)
        payload = await self._payloads(context, inputs.input)
        try:
            output = loaded.run(payload, config.params, _context(context))
        except ParamsError as exc:
            raise UserFacingNodeError(str(exc)) from exc
        except CodeError as exc:
            raise UserFacingNodeError(f"Line {exc.line}: {exc.message}") from exc
        return PythonTransformOutput(output=cast(JsonValue, output))

    async def _payloads(
        self,
        context: NodeExecutionContext,
        value: ArtifactRef | ArtifactRefSequence,
    ) -> JsonObject | list[JsonObject]:
        refs = value.item_refs if isinstance(value, ArtifactRefSequence) else [value]
        payloads: list[JsonObject] = []
        async with self._uow as uow:
            for ref in refs:
                artifact = await uow.artifacts.get(
                    context.workspace_id, ref.artifact_id
                )
                if artifact is None or artifact.inline_payload is None:
                    raise UserFacingNodeError(
                        f"Input artifact {ref.artifact_id} is not inline JSON"
                    )
                payloads.append(artifact.inline_payload)
        return payloads if isinstance(value, ArtifactRefSequence) else payloads[0]


def _require_applied(
    contract: CodeContract,
    config: PythonTransformConfig,
    bindings: Mapping[str, ArtifactTypeKey],
) -> None:
    """Refuse to run code whose ports no longer match what Apply stored."""

    expected = {
        "input": (contract.input.artifact_type, contract.input.shape),
        "output": (contract.output.artifact_type, contract.output.shape),
    }
    stored_shapes = {"input": config.input_shape, "output": config.output_shape}
    for port, (artifact_type, shape) in expected.items():
        bound = bindings.get(port)
        if (
            bound is None
            or bound.id != artifact_type.id
            or bound.schema_version != artifact_type.schema_version
            or stored_shapes[port] is not shape
        ):
            raise UserFacingNodeError(
                f"The {port} port no longer matches the code. Apply it again."
            )
    if contract.params_schema != config.params_schema:
        raise UserFacingNodeError("Params no longer match the code. Apply it again.")


def _context(context: NodeExecutionContext) -> Context:
    return Context(
        workspace_id=str(context.workspace_id),
        node_id=context.node_id,
        graph_id=(
            None if context.secret_graph_id is None else str(context.secret_graph_id)
        ),
        graph_revision=context.secret_graph_revision,
        run_id=(
            None if context.workflow_run_id is None else str(context.workflow_run_id)
        ),
        item_index=context.invocation_index,
    )


class PythonInspectConfig(NodeConfig):
    code: StrictStr = Field(max_length=MAX_CODE_LENGTH)


class PythonInspectInput(NodeInput):
    pass


class PythonInspectOutput(NodeOutput):
    report: Annotated[
        StrictStr,
        OutPort(TEXT_VALUE),
        Field(description="The inspection report as JSON."),
    ]


@PYTHON.function_node(
    operator_id="python.inspect",
    version=1,
    title="Inspect Python code",
    # Apply runs this; it is never a canvas node.
    listed=False,
)
async def inspect_python_code(
    config: PythonInspectConfig,
    _inputs: PythonInspectInput,
) -> PythonInspectOutput:
    """Derives the ports and params schema of Python node code for Apply."""
    return PythonInspectOutput(
        report=inspect_code(config.code, PORT_TYPES).model_dump_json()
    )


__all__ = [
    "PORT_TYPES",
    "LoadedCode",
    "PythonInspectConfig",
    "PythonTransformConfig",
    "PythonTransformNode",
    "inspect_python_code",
]
