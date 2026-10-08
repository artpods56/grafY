from typing import Annotated, Protocol, cast, final, override

from pydantic import BaseModel, Field, create_model

from grafy_core.artifacts import (
    ArtifactRef,
    NoConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.modules import (
    MODULE_ARTIFACT_TYPE_VARIABLE,
    MODULE_BOUNDARY_OPERATOR_VERSION,
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
    GraphModuleDefinition,
    ModuleBoundaryConfig,
    ModuleInputConfig,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
    derive_input_contract,
    derive_output_contract,
)
from grafy_core.plugins import NodeCachePolicy, NodeRegistration, Plugin
from grafy_core.ports.modules import GraphModuleExecutorPort


class _DynamicModelFactory(Protocol):
    def __call__(
        self,
        model_name: str,
        /,
        *,
        __base__: type[BaseModel],
        **field_definitions: object,
    ) -> type[BaseModel]: ...


_create_dynamic_model = cast(
    _DynamicModelFactory,
    cast(object, create_model),
)


_MODULE_BOUNDARIES = Plugin(
    slug="graph.module",
    title="Workspace library",
)

MODULE_ARTIFACT_TYPE = ArtifactTypeVariable(MODULE_ARTIFACT_TYPE_VARIABLE)


class ModuleInputInput(NodeInput):
    pass


class ModuleInputOutput(NodeOutput):
    value: Annotated[
        ArtifactRef,
        OutPort(MODULE_ARTIFACT_TYPE),
        Field(description="Artifact supplied through the public module input."),
    ]


class ModuleOutputInput(NodeInput):
    value: Annotated[
        ArtifactRef,
        InPort(MODULE_ARTIFACT_TYPE),
        Field(description="Artifact exposed through the public module output."),
    ]


class ModuleOutputOutput(NodeOutput):
    value: Annotated[
        ArtifactRef,
        OutPort(MODULE_ARTIFACT_TYPE),
        Field(description="Artifact exposed through the public module output."),
    ]


class ModuleBoundaryExecutionError(RuntimeError):
    pass


class GraphModuleExecutionError(UserFacingNodeError):
    pass


@_MODULE_BOUNDARIES.node(
    operator_id=MODULE_INPUT_OPERATOR_ID,
    version=MODULE_BOUNDARY_OPERATOR_VERSION,
    title="Module input",
    # Added from Module setup. A normal graph cannot run this boundary.
    listed=False,
)
@final
class ModuleInputNode(Node[ModuleInputConfig, ModuleInputInput, ModuleInputOutput]):
    """Declares one generic scalar input on a saved graph module."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ModuleInputConfig,
        _inputs: ModuleInputInput,
        /,
    ) -> ModuleInputOutput:
        node_id = context.node_id or "<unknown>"
        raise ModuleBoundaryExecutionError(
            f"Module Input boundary {node_id!r} for public input "
            f"{config.public_name!r} can only run inside a graph module"
        )


@_MODULE_BOUNDARIES.node(
    operator_id=MODULE_OUTPUT_OPERATOR_ID,
    version=MODULE_BOUNDARY_OPERATOR_VERSION,
    title="Module output",
    cache_policy=NodeCachePolicy.EXACT,
    # Added from Module setup. A normal graph cannot run this boundary.
    listed=False,
)
@final
class ModuleOutputNode(
    Node[ModuleBoundaryConfig, ModuleOutputInput, ModuleOutputOutput]
):
    """Declares one generic scalar output on a saved graph module."""

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: ModuleBoundaryConfig,
        inputs: ModuleOutputInput,
        /,
    ) -> ModuleOutputOutput:
        return ModuleOutputOutput(value=inputs.value)


MODULE_BOUNDARY_REGISTRATIONS = cast(
    tuple[NodeRegistration, NodeRegistration],
    _MODULE_BOUNDARIES.nodes,
)


class GraphModuleInput(NodeInput):
    pass


class GraphModuleOutput(NodeOutput):
    pass


class GraphModuleNode(Node[NoConfig, GraphModuleInput, GraphModuleOutput]):
    """Invokes one exact saved graph revision through its public module ports."""

    operator_id = "graph.module.unbound"
    operator_version = 1
    plugin_slug = "graph.module"
    title = "Unbound graph module"
    description = "A graph module node that has not been bound to a saved graph."

    def __init__(
        self,
        definition: GraphModuleDefinition,
        executor: GraphModuleExecutorPort,
    ) -> None:
        self._definition = definition
        self._executor = executor

        input_model = _input_model_for(definition)
        output_model = _output_model_for(definition)
        dynamic_attributes = cast(dict[str, object], self.__dict__)
        dynamic_attributes["operator_id"] = definition.operator_id
        dynamic_attributes["operator_version"] = definition.operator_version
        dynamic_attributes["plugin_slug"] = "graph.module"
        dynamic_attributes["title"] = definition.title
        dynamic_attributes["description"] = definition.description
        dynamic_attributes["input_contract"] = derive_input_contract(input_model)
        dynamic_attributes["output_contract"] = derive_output_contract(output_model)

    @property
    def definition(self) -> GraphModuleDefinition:
        return self._definition

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: GraphModuleInput,
        /,
    ) -> GraphModuleOutput:
        public_inputs: dict[str, ArtifactRef] = {}
        for port in self._definition.input_ports:
            value = getattr(inputs, port.name)
            if value is None:
                if port.required:
                    raise GraphModuleExecutionError(
                        f"Graph module {self.operator_id!r}@"
                        f"{self.operator_version} required input {port.name!r} "
                        "was absent"
                    )
                continue
            if not isinstance(value, ArtifactRef):
                raise GraphModuleExecutionError(
                    f"Graph module {self.operator_id!r}@{self.operator_version} "
                    f"input {port.name!r} expected an ArtifactRef, got "
                    f"{type(value).__name__}"
                )
            public_inputs[port.name] = value

        try:
            result = await self._executor.execute_module(
                self._definition,
                context,
                public_inputs,
            )
        except UserFacingNodeError:
            raise
        except Exception as exc:
            node_id = context.node_id or "<unknown>"
            raise GraphModuleExecutionError(
                f"Graph module {self._definition.name!r} "
                f"({self.operator_id}@{self.operator_version}) failed while "
                f"executing parent node {node_id!r}"
            ) from exc

        expected_names = {port.name for port in self._definition.output_ports}
        actual_names = set(result.outputs)
        missing_names = expected_names - actual_names
        unexpected_names = actual_names - expected_names
        if missing_names or unexpected_names:
            details: list[str] = []
            if missing_names:
                details.append(f"missing {', '.join(sorted(missing_names))}")
            if unexpected_names:
                details.append(f"unexpected {', '.join(sorted(unexpected_names))}")
            raise GraphModuleExecutionError(
                f"Graph module {self.operator_id!r}@{self.operator_version} "
                f"executor returned invalid output names: {'; '.join(details)}"
            )

        output_values: dict[str, ArtifactRef] = {}
        for port in self._definition.output_ports:
            value = result.outputs[port.name]
            if value.key() != port.artifact_type:
                raise GraphModuleExecutionError(
                    f"Graph module {self.operator_id!r}@{self.operator_version} "
                    f"output {port.name!r} expected {port.artifact_type.id}@"
                    f"{port.artifact_type.schema_version}, got "
                    f"{value.artifact_type}@{value.schema_version}"
                )
            output_values[port.name] = value

        output_model = cast(type[GraphModuleOutput], self.output_contract.model)
        return output_model.model_validate(output_values)


def _input_model_for(definition: GraphModuleDefinition) -> type[GraphModuleInput]:
    fields: dict[str, tuple[object, object]] = {}
    for port in definition.input_ports:
        field = Field(
            title=port.name.replace("_", " ").title(),
            description=port.description,
        )
        if port.required:
            annotation = Annotated[
                ArtifactRef,
                InPort(port.artifact_type),
                field,
            ]
            fields[port.name] = (annotation, ...)
            continue
        optional_annotation = Annotated[
            ArtifactRef | None,
            InPort(port.artifact_type),
            field,
        ]
        fields[port.name] = (optional_annotation, None)
    model_name = (
        f"GraphModule_{definition.reference.graph_id.hex}_"
        f"r{definition.reference.revision}_Input"
    )
    return cast(
        type[GraphModuleInput],
        _create_dynamic_model(
            model_name,
            __base__=GraphModuleInput,
            **fields,
        ),
    )


def _output_model_for(definition: GraphModuleDefinition) -> type[GraphModuleOutput]:
    fields: dict[str, tuple[object, object]] = {}
    for port in definition.output_ports:
        annotation = Annotated[
            ArtifactRef,
            OutPort(port.artifact_type),
            Field(
                title=port.name.replace("_", " ").title(),
                description=port.description,
            ),
        ]
        fields[port.name] = (annotation, ...)
    model_name = (
        f"GraphModule_{definition.reference.graph_id.hex}_"
        f"r{definition.reference.revision}_Output"
    )
    return cast(
        type[GraphModuleOutput],
        _create_dynamic_model(
            model_name,
            __base__=GraphModuleOutput,
            **fields,
        ),
    )


__all__ = [
    "MODULE_ARTIFACT_TYPE",
    "MODULE_BOUNDARY_REGISTRATIONS",
    "GraphModuleExecutionError",
    "GraphModuleInput",
    "GraphModuleNode",
    "GraphModuleOutput",
    "ModuleBoundaryConfig",
    "ModuleBoundaryExecutionError",
    "ModuleInputConfig",
    "ModuleInputInput",
    "ModuleInputNode",
    "ModuleInputOutput",
    "ModuleOutputInput",
    "ModuleOutputNode",
    "ModuleOutputOutput",
]
