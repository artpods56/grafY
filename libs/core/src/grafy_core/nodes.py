from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, ClassVar, cast, get_args, get_origin

from grafy_core.artifacts import ArtifactTypeKey, NodeConfig, NodeInput, NodeOutput
from grafy_core.node_context import (
    ALLOWED_NODE_PREVIEW_CONTENT_TYPES as ALLOWED_NODE_PREVIEW_CONTENT_TYPES,
    MAX_NODE_ERROR_MESSAGE_LENGTH as MAX_NODE_ERROR_MESSAGE_LENGTH,
    MAX_NODE_PREVIEW_BYTES as MAX_NODE_PREVIEW_BYTES,
    MAX_NODE_PREVIEW_DETAIL_LENGTH as MAX_NODE_PREVIEW_DETAIL_LENGTH,
    MAX_NODE_PREVIEW_LABEL_LENGTH as MAX_NODE_PREVIEW_LABEL_LENGTH,
    MAX_NODE_PROGRESS_COUNTER as MAX_NODE_PROGRESS_COUNTER,
    MAX_NODE_PROGRESS_MESSAGE_LENGTH as MAX_NODE_PROGRESS_MESSAGE_LENGTH,
    NodeExecutionContext as NodeExecutionContext,
    NodePreviewReporter as NodePreviewReporter,
    NodeProgressReporter as NodeProgressReporter,
    NodeSecretRequirementError as NodeSecretRequirementError,
    NodeSecrets as NodeSecrets,
    UserFacingNodeError as UserFacingNodeError,
    bind_node_secret_config as bind_node_secret_config,
    bind_node_secrets as bind_node_secrets,
)
from grafy_core.node_derivation import (
    derive_input_contract as derive_input_contract,
    derive_output_contract as derive_output_contract,
    validate_service_node as validate_service_node,
)
from grafy_core.node_ports import (
    ArtifactTypeContract as ArtifactTypeContract,
    ArtifactTypeVariable as ArtifactTypeVariable,
    Binds as Binds,
    ConfigContract as ConfigContract,
    InputContract as InputContract,
    InputPortSpec as InputPortSpec,
    NodeContractError as NodeContractError,
    NodeContractResolutionError as NodeContractResolutionError,
    OutputContract as OutputContract,
    OutputPortSpec as OutputPortSpec,
    Plugs as Plugs,
    PortShape as PortShape,
    Ref as Ref,
    RefSequence as RefSequence,
    RequiresServiceFeature as RequiresServiceFeature,
    ResolvedNodeContracts as ResolvedNodeContracts,
    ServiceContractFeatures as ServiceContractFeatures,
    ServiceContractKey as ServiceContractKey,
)
from grafy_core.node_progress import (
    active_node_context as active_node_context,
    bind_active_node as bind_active_node,
    emit_node_preview as emit_node_preview,
    emit_node_progress as emit_node_progress,
)
from grafy_core.service_contracts import (
    ServiceContract as ServiceContract,
    implements_service_contract as implements_service_contract,
    service_contract as service_contract,
)


class Node[
    ConfigT: NodeConfig,
    InputT: NodeInput,
    OutputT: NodeOutput,
](ABC):
    operator_id: ClassVar[str]
    operator_version: ClassVar[int]
    plugin_slug: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str]
    config_contract: ClassVar[ConfigContract[Any]]
    input_contract: ClassVar[InputContract[Any]]
    output_contract: ClassVar[OutputContract[Any]]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        for base in getattr(cls, "__orig_bases__", ()):
            if get_origin(base) is not Node:
                continue
            type_args = get_args(base)
            if len(type_args) != 3:
                continue
            config_model, input_model, output_model = type_args
            if not (
                isinstance(config_model, type)
                and issubclass(config_model, NodeConfig)
                and isinstance(input_model, type)
                and issubclass(input_model, NodeInput)
                and isinstance(output_model, type)
                and issubclass(output_model, NodeOutput)
            ):
                continue
            cls.config_contract = ConfigContract(model=config_model)
            cls.input_contract = derive_input_contract(input_model)
            cls.output_contract = derive_output_contract(output_model)
            validate_service_node(
                cls.__name__,
                cls.input_contract,
                cls.output_contract,
            )
            return

    @abstractmethod
    async def run(
        self,
        context: NodeExecutionContext,
        config: ConfigT,
        inputs: InputT,
        /,
    ) -> OutputT:
        """Execute one scalar invocation.

        MAP execution may call this method concurrently on the same node instance.
        Keep invocation-local mutable state inside this call rather than on ``self``.
        Let task cancellation propagate after any required cleanup.
        """
        ...

    @classmethod
    def validate_artifact_type_bindings(
        cls,
        bindings: Mapping[str, ArtifactTypeKey],
    ) -> None:
        """Refuse a binding that variable resolution cannot judge on its own.

        Resolution checks that every declared variable is bound, that each name
        is known, and that each key is an artifact type. A variable with a
        semantic constraint, such as one that must name a claimed file format,
        overrides this hook so an impossible binding never reaches a saved
        graph. Raise :class:`NodeContractResolutionError` with the reason.
        """


def _shape_from_config(
    operator_id: str,
    port_name: str,
    shape_field: str,
    raw_shape: object,
) -> PortShape:
    """The shape one config field names for a port.

    A ``shape_field`` carries the text of a :class:`PortShape`. Anything else is a
    mistake about the node's own configuration, so it is refused here rather than
    resolved to the port's declared default.
    """

    parsed_shape: PortShape | None = None
    if isinstance(raw_shape, str):
        try:
            parsed_shape = PortShape(raw_shape)
        except ValueError:
            pass
    if parsed_shape is None:
        raise NodeContractResolutionError(
            f"Node {operator_id!r} port {port_name!r} shape field "
            f"{shape_field!r} must be 'one' or 'many', got {raw_shape!r}"
        )
    return parsed_shape


def resolve_node_contracts(
    node: Node[Any, Any, Any],
    bindings: Mapping[str, ArtifactTypeKey],
    config: Mapping[str, object] | None = None,
) -> ResolvedNodeContracts:
    """Resolve the artifact type variables and config-chosen shapes of one node.

    A port that names a ``shape_field`` takes its shape from that config field;
    an absent field leaves the shape the port declares.
    """

    variables: set[str] = set()
    for port in node.input_contract.ports.values():
        if isinstance(port.accepts, ArtifactTypeVariable):
            variables.add(port.accepts.name)
    for port in node.output_contract.ports.values():
        if isinstance(port.produces, ArtifactTypeVariable):
            variables.add(port.produces.name)
    raw_bindings = cast(Mapping[object, object], bindings)
    binding_names: set[str] = set()
    for raw_name in raw_bindings:
        if not isinstance(raw_name, str):
            raise NodeContractResolutionError(
                f"Node {node.operator_id!r} artifact type binding names must be "
                f"strings, got {type(raw_name).__name__}"
            )
        binding_names.add(raw_name)

    unknown = sorted(binding_names - variables)
    if unknown:
        rendered = ", ".join(unknown)
        raise NodeContractResolutionError(
            f"Node {node.operator_id!r} received unknown artifact type bindings: "
            f"{rendered}"
        )

    missing = sorted(variables - binding_names)
    if missing:
        rendered = ", ".join(missing)
        raise NodeContractResolutionError(
            f"Node {node.operator_id!r} is missing artifact type bindings: {rendered}"
        )

    for raw_name, raw_key in raw_bindings.items():
        if not isinstance(raw_name, str):
            continue
        if not isinstance(raw_key, ArtifactTypeKey):
            raise NodeContractResolutionError(
                f"Node {node.operator_id!r} artifact type binding {raw_name!r} "
                f"must be an ArtifactTypeKey, got {type(raw_key).__name__}"
            )
        if raw_key.id.strip() == "":
            raise NodeContractResolutionError(
                f"Node {node.operator_id!r} artifact type binding {raw_name!r} must "
                "reference a non-empty artifact type id"
            )
        if raw_key.id != raw_key.id.strip():
            raise NodeContractResolutionError(
                f"Node {node.operator_id!r} artifact type binding {raw_name!r} must "
                "reference an artifact type id without surrounding whitespace"
            )
        if isinstance(raw_key.schema_version, bool) or raw_key.schema_version < 1:
            raise NodeContractResolutionError(
                f"Node {node.operator_id!r} artifact type binding {raw_name!r} must "
                "reference a positive schema version"
            )

    node.validate_artifact_type_bindings(bindings)
    input_ports: dict[str, InputPortSpec] = {}
    for name, port in node.input_contract.ports.items():
        if isinstance(port.accepts, ArtifactTypeVariable):
            port = replace(port, accepts=bindings[port.accepts.name])
        if port.shape_field is not None:
            if config is None or port.shape_field not in config:
                shape = port.shape
            else:
                raw_shape = config[port.shape_field]
                shape = _shape_from_config(
                    node.operator_id, name, port.shape_field, raw_shape
                )
            port = replace(port, shape=shape, accepted_shapes=(shape,))
        input_ports[name] = port
    output_ports: dict[str, OutputPortSpec] = {}
    for name, port in node.output_contract.ports.items():
        if isinstance(port.produces, ArtifactTypeVariable):
            port = replace(port, produces=bindings[port.produces.name])
        if port.shape_field is not None:
            if config is None or port.shape_field not in config:
                shape = port.shape
            else:
                raw_shape = config[port.shape_field]
                shape = _shape_from_config(
                    node.operator_id, name, port.shape_field, raw_shape
                )
            port = replace(port, shape=shape)
        output_ports[name] = port
    return ResolvedNodeContracts(
        input_contract=replace(node.input_contract, ports=input_ports),
        output_contract=replace(node.output_contract, ports=output_ports),
    )
