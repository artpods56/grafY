from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field, replace
from enum import StrEnum
from types import UnionType
from typing import (
    Annotated,
    Any,
    ClassVar,
    Final,
    Literal,
    Protocol,
    Union,
    cast,
    get_args,
    get_origin,
)
from uuid import UUID

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactTypeKey,
    ArtifactTypeSpec,
    ArtifactRef,
    ArtifactRefSequence,
    NodeConfig,
    NodeInput,
    NodeOutput,
)


MAX_NODE_PROGRESS_MESSAGE_LENGTH: Final = 1_000
MAX_NODE_PROGRESS_COUNTER: Final = 9_007_199_254_740_991
MAX_NODE_ERROR_MESSAGE_LENGTH: Final = 1_000


class PortShape(StrEnum):
    ONE = "one"
    MANY = "many"


class NodeContractError(TypeError):
    pass


class NodeContractResolutionError(ValueError):
    pass


class UserFacingNodeError(RuntimeError):
    """An operator failure whose bounded message is safe to show to graph users.

    Raising this exception is an explicit assertion by Plugin code that the
    message contains no credentials, prompts, provider response bodies, or other
    sensitive runtime state. Unknown exceptions remain private implementation
    failures and cross runtime adapters only as a generic error.
    """

    def __init__(self, message: str) -> None:
        normalized = message.strip()
        if normalized == "":
            raise ValueError("User-facing node error message must not be blank")
        if len(normalized) > MAX_NODE_ERROR_MESSAGE_LENGTH:
            raise ValueError(
                "User-facing node error message must be at most "
                f"{MAX_NODE_ERROR_MESSAGE_LENGTH} characters"
            )
        super().__init__(normalized)


@dataclass(frozen=True, slots=True)
class ArtifactTypeVariable:
    """A named artifact type chosen when a node instance is bound."""

    name: str

    def __post_init__(self) -> None:
        if self.name.strip() == "":
            raise ValueError("Artifact type variable name must not be empty")
        if self.name != self.name.strip():
            raise ValueError(
                "Artifact type variable name must not have surrounding whitespace"
            )
        if len(self.name) > 255:
            raise ValueError(
                "Artifact type variable name must be at most 255 characters"
            )


ArtifactTypeContract = ArtifactTypeKey | ArtifactTypeVariable


@dataclass(frozen=True, slots=True)
class InPort:
    """Marks an input model field as an artifact port via Annotated metadata.

    ``accepts`` is the primary artifact type (or the single artifact type
    variable). ``also_accepts`` adds the remaining concrete types the same input
    accepts, so one port can take several artifact types without a type variable.
    ``shape_field`` names the node config field that chooses this port's shape
    for one node instance; the field holds ``one`` or ``many``.
    """

    accepts: ArtifactTypeSpec | ArtifactTypeContract
    variadic: bool = False
    instance_plugs: bool = False
    also_accepts: tuple[ArtifactTypeSpec | ArtifactTypeKey, ...] = ()
    shape_field: str | None = None
    agent_default: Literal["fill", "hidden"] = "fill"
    """What an Agent tool link does with this input unless told otherwise.

    ``fill`` offers it to the model as a parameter; ``hidden`` leaves it to the Graph. An
    input that makes the node fetch whatever address a model writes is hidden by default."""

    def __post_init__(self) -> None:
        if self.also_accepts and isinstance(self.accepts, ArtifactTypeVariable):
            raise NodeContractError(
                "An input port must declare either an artifact type variable or "
                "additional accepted artifact types, not both"
            )
        if self.shape_field is not None and (self.variadic or self.instance_plugs):
            raise NodeContractError(
                "A config-chosen port shape cannot be variadic or use instance plugs"
            )


@dataclass(frozen=True, slots=True)
class OutPort:
    """Marks an output model field as an artifact port via Annotated metadata.

    ``shape_field`` names the node config field that chooses this port's shape
    for one node instance; the field holds ``one`` or ``many``.
    """

    produces: ArtifactTypeSpec | ArtifactTypeContract
    shape_field: str | None = None


@dataclass(frozen=True, slots=True)
class InputPortSpec:
    name: str
    accepts: ArtifactTypeContract
    title: str | None = None
    description: str | None = None
    shape: PortShape = PortShape.ONE
    variadic: bool = False
    instance_plugs: bool = False
    accepted_shapes: tuple[PortShape, ...] = (PortShape.ONE,)
    target_type: type[object] | None = None
    preserves_ref_container: bool = False
    allows_none: bool = False
    required: bool = True
    also_accepts: tuple[ArtifactTypeKey, ...] = ()
    shape_field: str | None = None
    agent_default: Literal["fill", "hidden"] = "fill"

    def __post_init__(self) -> None:
        if not self.also_accepts:
            return
        if isinstance(self.accepts, ArtifactTypeVariable):
            raise NodeContractError(
                f"Input port {self.name!r} must declare either an artifact type "
                "variable or additional accepted artifact types, not both"
            )
        if self.accepts in self.also_accepts:
            raise NodeContractError(
                f"Input port {self.name!r} repeats its primary artifact type "
                "among its additional accepted artifact types"
            )
        if len(set(self.also_accepts)) != len(self.also_accepts):
            raise NodeContractError(
                f"Input port {self.name!r} declares duplicate additional accepted "
                "artifact types"
            )

    @property
    def accepted_types(self) -> tuple[ArtifactTypeKey, ...]:
        """Concrete artifact types this input accepts, primary type first.

        Empty for a port that declares a named artifact type variable.
        """

        if isinstance(self.accepts, ArtifactTypeVariable):
            return ()
        return (self.accepts, *self.also_accepts)


@dataclass(frozen=True, slots=True)
class OutputPortSpec:
    name: str
    produces: ArtifactTypeContract
    title: str | None = None
    description: str | None = None
    shape: PortShape = PortShape.ONE
    required: bool = True
    shape_field: str | None = None


@dataclass(frozen=True, slots=True)
class InputContract[T: BaseModel]:
    model: type[T]
    ports: dict[str, InputPortSpec]


@dataclass(frozen=True, slots=True)
class OutputContract[T: BaseModel]:
    model: type[T]
    ports: dict[str, OutputPortSpec]


@dataclass(frozen=True, slots=True)
class ConfigContract[T: BaseModel]:
    model: type[T]


@dataclass(frozen=True, slots=True)
class ResolvedNodeContracts:
    input_contract: InputContract[Any]
    output_contract: OutputContract[Any]


class NodeProgressReporter(Protocol):
    """Host boundary for ephemeral, user-visible node progress."""

    async def report_progress(
        self,
        context: "NodeExecutionContext",
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class NodeExecutionContext:
    """Where one node instance runs, in Project vocabulary (ADR 0020).

    ``graph_id`` and ``node_id`` name the instance inside the Graph it belongs to,
    ``call_path`` the call nodes entered to reach that Graph, and ``fingerprint``
    the digest its result is stored under. An operator that needs a stable
    identity of its own has that fingerprint, not a per-run identifier: runs are
    demands for fresh results and never own one.
    """

    workspace_id: UUID
    project_id: UUID | None = None
    graph_id: str | None = None
    node_id: str | None = None
    call_path: tuple[str, ...] = ()
    fingerprint: str | None = None
    invocation_index: int | None = None
    invocation_path: tuple[int, ...] = ()
    artifact_type_bindings: Mapping[str, ArtifactTypeKey] = dataclass_field(
        default_factory=dict[str, ArtifactTypeKey],
        repr=False,
        compare=False,
    )
    progress_reporter: NodeProgressReporter | None = dataclass_field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_path", tuple(self.call_path))
        object.__setattr__(self, "invocation_path", tuple(self.invocation_path))

    async def progress(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        """Publish bounded progress text without exposing node inputs or config."""

        normalized_message = message.strip()
        if normalized_message == "":
            raise ValueError("Node progress message must not be blank")
        if len(normalized_message) > MAX_NODE_PROGRESS_MESSAGE_LENGTH:
            raise ValueError(
                "Node progress message must be at most "
                f"{MAX_NODE_PROGRESS_MESSAGE_LENGTH} characters"
            )
        if current is not None and current < 0:
            raise ValueError("Node progress current value must not be negative")
        if current is not None and current > MAX_NODE_PROGRESS_COUNTER:
            raise ValueError(
                "Node progress current value must not exceed "
                f"{MAX_NODE_PROGRESS_COUNTER}"
            )
        if total is not None and total < 0:
            raise ValueError("Node progress total value must not be negative")
        if total is not None and total > MAX_NODE_PROGRESS_COUNTER:
            raise ValueError(
                f"Node progress total value must not exceed {MAX_NODE_PROGRESS_COUNTER}"
            )
        if current is not None and total is not None and current > total:
            raise ValueError("Node progress current value must not exceed total")

        reporter = self.progress_reporter
        if reporter is None:
            return
        try:
            await reporter.report_progress(
                self,
                normalized_message,
                current=current,
                total=total,
            )
        except Exception:
            # User-visible reporting is best-effort. Reporter failures must not
            # turn a successful node action into a failed graph execution.
            return


def derive_input_contract[T: BaseModel](model: type[T]) -> InputContract[T]:
    ports: dict[str, InputPortSpec] = {}
    for name, field in model.model_fields.items():
        if any(isinstance(meta, OutPort) for meta in field.metadata):
            message = (
                f"{model.__name__}.{name} declares a {OutPort.__name__}; "
                f"only {InPort.__name__} is valid on this side of the contract"
            )
            raise NodeContractError(message)
        metadata_ports = [meta for meta in field.metadata if isinstance(meta, InPort)]
        if len(metadata_ports) > 1:
            message = (
                f"{model.__name__}.{name} declares {len(metadata_ports)} "
                f"{InPort.__name__} annotations; at most one is allowed"
            )
            raise NodeContractError(message)
        port = metadata_ports[0] if metadata_ports else None
        if port is None:
            continue
        if port.shape_field is not None:
            annotation = field.annotation
            if get_origin(annotation) is Annotated:
                annotation = get_args(annotation)[0]
            members: set[object] = (
                set(get_args(annotation))
                if get_origin(annotation) in (UnionType, Union)
                else set()
            )
            if members - {type(None)} == {ArtifactRef, ArtifactRefSequence}:
                allows_none = type(None) in members
            else:
                message = (
                    f"{model.__name__}.{name} chooses its shape from config and must "
                    "use exactly ArtifactRef | ArtifactRefSequence"
                )
                raise NodeContractError(message)
            shape = PortShape.ONE
            accepted_shapes = (PortShape.ONE, PortShape.MANY)
            target_type = None
            preserves_ref_container = True
        elif port.instance_plugs:
            annotation = field.annotation
            if not port.variadic:
                message = (
                    f"{model.__name__}.{name} declares instance_plugs=True; "
                    "instance plugs require variadic=True"
                )
                raise NodeContractError(message)
            if get_origin(annotation) is not list:
                message = (
                    f"{model.__name__}.{name} must use exactly "
                    "list[T] for typed instance plugs or "
                    "list[ArtifactRef | ArtifactRefSequence] to preserve refs"
                )
                raise NodeContractError(message)
            item_type = _sequence_item_type(
                model=model,
                field_name=name,
                annotation=annotation,
                purpose="instance plugs",
            )
            item_origin = get_origin(item_type)
            item_types = set(get_args(item_type))
            if item_origin in (UnionType, Union) and item_types == {
                ArtifactRef,
                ArtifactRefSequence,
            }:
                shape = PortShape.ONE
                accepted_shapes = (PortShape.ONE, PortShape.MANY)
                target_type = None
                preserves_ref_container = True
                allows_none = False
            else:
                shape = PortShape.ONE
                accepted_shapes = (PortShape.ONE,)
                target_type = _concrete_type(model, name, item_type)
                preserves_ref_container = False
                allows_none = False
        else:
            annotation = field.annotation
            value_type, allows_none = _unwrap_optional(annotation)
            if port.variadic:
                value_type = _sequence_item_type(
                    model=model,
                    field_name=name,
                    annotation=value_type,
                    purpose="a variadic input port",
                )
                value_type, item_allows_none = _unwrap_optional(value_type)
                allows_none = allows_none or item_allows_none
            if value_type is ArtifactRef:
                shape = PortShape.ONE
                accepted_shapes = (PortShape.ONE,)
                target_type = None
                preserves_ref_container = True
            elif value_type is ArtifactRefSequence:
                shape = PortShape.MANY
                accepted_shapes = (PortShape.MANY,)
                target_type = None
                preserves_ref_container = True
            elif _is_sequence_origin(get_origin(value_type)):
                item_type = _sequence_item_type(
                    model=model,
                    field_name=name,
                    annotation=value_type,
                    purpose="an artifact sequence",
                )
                item_type, _ = _unwrap_optional(item_type)
                target_type = _concrete_type(model, name, item_type)
                shape = PortShape.MANY
                accepted_shapes = (PortShape.MANY,)
                preserves_ref_container = False
            else:
                target_type = _concrete_type(model, name, value_type)
                shape = PortShape.ONE
                accepted_shapes = (PortShape.ONE,)
                preserves_ref_container = False
        accepts = (
            port.accepts.key
            if isinstance(port.accepts, ArtifactTypeSpec)
            else port.accepts
        )
        concrete_also_accepts: list[ArtifactTypeKey] = []
        for raw_also_accepts in port.also_accepts:
            value = cast(object, raw_also_accepts)
            if isinstance(value, ArtifactTypeSpec):
                concrete_also_accepts.append(value.key)
            elif isinstance(value, ArtifactTypeKey):
                concrete_also_accepts.append(value)
            else:
                raise NodeContractError(
                    "Additional accepted artifact types must be concrete artifact types, got "
                    f"{type(value).__name__}"
                )
        ports[name] = InputPortSpec(
            name=name,
            accepts=accepts,
            also_accepts=tuple(concrete_also_accepts),
            title=field.title,
            description=field.description,
            shape=shape,
            variadic=port.variadic,
            instance_plugs=port.instance_plugs,
            accepted_shapes=accepted_shapes,
            target_type=target_type,
            preserves_ref_container=preserves_ref_container,
            allows_none=allows_none,
            required=field.is_required(),
            shape_field=port.shape_field,
            agent_default=port.agent_default,
        )
    return InputContract(model=model, ports=ports)


def derive_output_contract[T: BaseModel](model: type[T]) -> OutputContract[T]:
    ports: dict[str, OutputPortSpec] = {}
    for name, field in model.model_fields.items():
        if any(isinstance(meta, InPort) for meta in field.metadata):
            message = (
                f"{model.__name__}.{name} declares a {InPort.__name__}; "
                f"only {OutPort.__name__} is valid on this side of the contract"
            )
            raise NodeContractError(message)
        metadata_ports = [meta for meta in field.metadata if isinstance(meta, OutPort)]
        if len(metadata_ports) > 1:
            message = (
                f"{model.__name__}.{name} declares {len(metadata_ports)} "
                f"{OutPort.__name__} annotations; at most one is allowed"
            )
            raise NodeContractError(message)
        port = metadata_ports[0] if metadata_ports else None
        if port is None:
            continue
        value_type, _ = _unwrap_optional(field.annotation)
        if value_type is ArtifactRef:
            shape = PortShape.ONE
        elif value_type is ArtifactRefSequence:
            shape = PortShape.MANY
        elif _is_sequence_origin(get_origin(value_type)):
            _sequence_item_type(
                model=model,
                field_name=name,
                annotation=value_type,
                purpose="an artifact sequence",
            )
            shape = PortShape.MANY
        else:
            shape = PortShape.ONE
        produces = (
            port.produces.key
            if isinstance(port.produces, ArtifactTypeSpec)
            else port.produces
        )
        ports[name] = OutputPortSpec(
            name=name,
            produces=produces,
            title=field.title,
            description=field.description,
            shape=shape,
            required=field.is_required(),
            shape_field=port.shape_field,
        )
    return OutputContract(model=model, ports=ports)


def _unwrap_optional(annotation: object) -> tuple[object, bool]:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _unwrap_optional(get_args(annotation)[0])
    if origin not in (UnionType, Union):
        return annotation, False

    args = get_args(annotation)
    non_none = tuple(arg for arg in args if arg is not type(None))
    if len(non_none) == 1 and len(non_none) != len(args):
        return non_none[0], True
    return annotation, False


def _is_sequence_origin(origin: object) -> bool:
    return origin is list or origin is tuple or origin is Sequence


def _sequence_item_type(
    *,
    model: type[BaseModel],
    field_name: str,
    annotation: object,
    purpose: str,
) -> object:
    origin = get_origin(annotation)
    if not _is_sequence_origin(origin):
        message = (
            f"{model.__name__}.{field_name} must use a list, tuple, or Sequence "
            f"annotation for {purpose}"
        )
        raise NodeContractError(message)
    args = get_args(annotation)
    if len(args) == 0:
        message = (
            f"{model.__name__}.{field_name} must declare an item type for {purpose}"
        )
        raise NodeContractError(message)
    return args[0]


def _concrete_type(
    model: type[BaseModel],
    field_name: str,
    annotation: object,
) -> type[object]:
    if isinstance(annotation, type):
        return annotation
    message = (
        f"{model.__name__}.{field_name} artifact value type must be a concrete "
        f"Python type, got {annotation!r}"
    )
    raise NodeContractError(message)


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
                parsed_shape: PortShape | None = None
                if isinstance(raw_shape, str):
                    try:
                        parsed_shape = PortShape(raw_shape)
                    except ValueError:
                        pass
                if parsed_shape is None:
                    raise NodeContractResolutionError(
                        f"Node {node.operator_id!r} port {name!r} shape field "
                        f"{port.shape_field!r} must be 'one' or 'many', got "
                        f"{raw_shape!r}"
                    )
                shape = parsed_shape
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
                parsed_shape: PortShape | None = None
                if isinstance(raw_shape, str):
                    try:
                        parsed_shape = PortShape(raw_shape)
                    except ValueError:
                        pass
                if parsed_shape is None:
                    raise NodeContractResolutionError(
                        f"Node {node.operator_id!r} port {name!r} shape field "
                        f"{port.shape_field!r} must be 'one' or 'many', got "
                        f"{raw_shape!r}"
                    )
                shape = parsed_shape
            port = replace(port, shape=shape)
        output_ports[name] = port
    return ResolvedNodeContracts(
        input_contract=replace(node.input_contract, ports=input_ports),
        output_contract=replace(node.output_contract, ports=output_ports),
    )
