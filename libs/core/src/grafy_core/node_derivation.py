from types import UnionType
from typing import Annotated, Any, Literal, Union, cast, get_args, get_origin

from pydantic import BaseModel, StrictInt, StrictStr

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.node_ports import (
    ArtifactTypeContract,
    ArtifactTypeVariable,
    Binds,
    InputContract,
    InputPortSpec,
    NodeContractError,
    OutputContract,
    OutputPortSpec,
    Plugs,
    PortShape,
    Ref,
    RefSequence,
    ServiceContractKey,
)
from grafy_core.declared_values import declared_key
from grafy_core.service_contracts import marked_contract, produced_contracts


def derive_input_contract[T: BaseModel](model: type[T]) -> InputContract[T]:
    ports: dict[str, InputPortSpec] = {}
    for name, field in model.model_fields.items():
        plugs, binds = _markers(model, name, field.metadata)
        described = _describe(model, name, field.annotation, plugs, binds, output=False)
        if described is None:
            continue
        variadic, instance, spare, agent_default = _plug_flags(plugs)
        if described.kind == "service":
            # A service input is never a model parameter. The Graph feeds it.
            agent_default = "hidden"
        ports[name] = InputPortSpec(
            name=name,
            accepts=described.accepts,
            also_accepts=described.also_accepts,
            title=field.title,
            description=field.description,
            shape=described.shape,
            variadic=variadic,
            instance_plugs=instance,
            spare_plugs=spare,
            accepted_shapes=described.accepted_shapes,
            value_types=described.value_types,
            preserves_ref_container=described.preserves_ref_container,
            allows_none=described.allows_none,
            required=field.is_required(),
            agent_default=agent_default,
            kind=described.kind,
            service_contracts=described.service_contracts,
        )
    return InputContract(model=model, ports=ports)


def derive_output_contract[T: BaseModel](model: type[T]) -> OutputContract[T]:
    ports: dict[str, OutputPortSpec] = {}
    for name, field in model.model_fields.items():
        plugs, binds = _markers(model, name, field.metadata)
        described = _describe(model, name, field.annotation, plugs, binds, output=True)
        if described is None:
            continue
        ports[name] = OutputPortSpec(
            name=name,
            produces=described.accepts,
            title=field.title,
            description=field.description,
            shape=described.shape,
            required=field.is_required(),
            value_type=described.value_type,
            kind=described.kind,
            service_contracts=described.service_contracts,
        )
    return OutputContract(model=model, ports=ports)


class _Described:
    def __init__(
        self,
        *,
        shape: PortShape,
        accepted_shapes: tuple[PortShape, ...],
        value_types: tuple[type[object], ...],
        accepts: ArtifactTypeContract | None,
        also_accepts: tuple[ArtifactTypeKey, ...],
        preserves_ref_container: bool,
        allows_none: bool,
        value_type: type[object] | None,
        kind: Literal["artifact", "service"] = "artifact",
        service_contracts: tuple[ServiceContractKey, ...] = (),
    ) -> None:
        self.shape = shape
        self.accepted_shapes = accepted_shapes
        self.value_types = value_types
        self.accepts = accepts
        self.also_accepts = also_accepts
        self.preserves_ref_container = preserves_ref_container
        self.allows_none = allows_none
        self.value_type = value_type
        self.kind = kind
        self.service_contracts = service_contracts


def _markers(
    model: type[BaseModel],
    name: str,
    metadata: list[object],
) -> tuple[Plugs | None, Binds | None]:
    plugs = _one_marker(model, name, metadata, Plugs)
    binds = _one_marker(model, name, metadata, Binds)
    if plugs is not None and plugs.instance and not plugs.variadic:
        raise NodeContractError(
            f"{model.__name__}.{name}: Plugs instance requires variadic plugs"
        )
    return plugs, binds


def _one_marker[MarkerT](
    model: type[BaseModel],
    name: str,
    metadata: list[object],
    marker: type[MarkerT],
) -> MarkerT | None:
    found = [item for item in metadata if isinstance(item, marker)]
    if len(found) > 1:
        raise NodeContractError(
            f"{model.__name__}.{name} declares {len(found)} {marker.__name__} "
            "annotations; at most one is allowed"
        )
    if not found:
        return None
    return found[0]


def _plug_flags(
    plugs: Plugs | None,
) -> tuple[bool, bool, bool, Literal["fill", "hidden"]]:
    if plugs is None:
        return False, False, False, "fill"
    return plugs.variadic, plugs.instance, plugs.spare, plugs.agent_default


def _describe(
    model: type[BaseModel],
    name: str,
    annotation: object,
    plugs: Plugs | None,
    binds: Binds | None,
    *,
    output: bool,
) -> _Described | None:
    members, allows_none = _without_none(annotation)
    service = _service_port(model, name, members, plugs, output=output)
    if service is not None:
        service.allows_none = allows_none
        return service
    if plugs is not None and (plugs.variadic or plugs.instance):
        kind = "instance plugs" if plugs.instance else "variadic plugs"
        if len(members) != 1 or get_origin(members[0]) is not list:
            raise NodeContractError(
                f"{model.__name__}.{name} must use a list annotation for {kind}"
            )
        item = _sequence_item_type(
            model=model,
            field_name=name,
            annotation=members[0],
            purpose=kind,
        )
        item_members, item_allows_none = _without_none(item)
        members = item_members
        allows_none = allows_none or item_allows_none
    listed = False
    if len(members) == 1 and get_origin(members[0]) is list:
        item = _sequence_item_type(
            model=model,
            field_name=name,
            annotation=members[0],
            purpose="an artifact sequence",
        )
        members, item_allows_none = _without_none(item)
        allows_none = allows_none or item_allows_none
        listed = True
    described = _describe_members(model, name, members, plugs, binds, output=output)
    if described is None:
        if plugs is not None or binds is not None:
            raise NodeContractError(f"{model.__name__}.{name} is not an artifact port")
        return None
    described.allows_none = allows_none
    if listed:
        if described.preserves_ref_container:
            raise NodeContractError(
                f"{model.__name__}.{name} cannot list Ref values; use RefSequence"
            )
        described.shape = PortShape.MANY
        described.accepted_shapes = (PortShape.MANY,)
    return described


def _service_port(
    model: type[BaseModel],
    name: str,
    members: tuple[object, ...],
    plugs: Plugs | None,
    *,
    output: bool,
) -> _Described | None:
    """Describe a service port, or return None when the field is not one.

    A service port is one value. A list, a variadic plug, or an instance plug
    is rejected here, and a union of service types is rejected. An input is
    typed as the contract itself; an output produces every contract its class
    subclasses, including a contract the class declares on itself.
    """

    if not _contains_service(members):
        return None
    if plugs is not None and (plugs.variadic or plugs.instance):
        raise NodeContractError(
            f"{model.__name__}.{name} service port must be one value, not "
            "variadic or instance plugs"
        )
    if len(members) == 1 and get_origin(members[0]) is list:
        raise NodeContractError(
            f"{model.__name__}.{name} service port must be one value, not "
            "variadic or instance plugs"
        )
    if len(members) != 1 or not isinstance(members[0], type):
        raise NodeContractError(
            f"{model.__name__}.{name} service port cannot be a union"
        )
    member = members[0]
    if output:
        keys = tuple(spec.key for spec in produced_contracts(member))
    else:
        own = marked_contract(member)
        if own is None:
            raise NodeContractError(
                f"{model.__name__}.{name} service input must be the contract, "
                "not an implementation"
            )
        keys = (own.key,)
    return _Described(
        shape=PortShape.ONE,
        accepted_shapes=(PortShape.ONE,),
        value_types=(),
        accepts=None,
        also_accepts=(),
        preserves_ref_container=False,
        allows_none=False,
        value_type=None,
        kind="service",
        service_contracts=keys,
    )


def _contains_service(members: tuple[object, ...]) -> bool:
    for member in members:
        if _is_service_type(member):
            return True
        if get_origin(member) is list:
            args = get_args(member)
            if args and _contains_service(_without_none(args[0])[0]):
                return True
    return False


def _is_service_type(member: object) -> bool:
    return isinstance(member, type) and bool(produced_contracts(member))


def _describe_members(
    model: type[BaseModel],
    name: str,
    members: tuple[object, ...],
    plugs: Plugs | None,
    binds: Binds | None,
    *,
    output: bool,
) -> _Described | None:
    if not members or members == (type(None),):
        return None
    classified: list[_Member] = []
    saw_port = False
    for member in members:
        item = _classify_member(model, name, member)
        if item is None:
            continue
        saw_port = True
        classified.append(item)
    if not saw_port:
        return None
    if len(classified) != len(members):
        raise NodeContractError(
            f"{model.__name__}.{name} mixes a declared port type with a value "
            "that is not a port"
        )
    kinds = {item.kind for item in classified}
    if "value" in kinds and kinds != {"value"}:
        raise NodeContractError(f"{model.__name__}.{name} mixes a value class with Ref")
    if kinds == {"value"}:
        return _value_port(model, name, classified, output=output)
    return _ref_port(model, name, classified, plugs, binds, output=output)


class _Member:
    def __init__(
        self,
        kind: str,
        argument: object,
        value_type: type[object] | None,
        key: ArtifactTypeKey | None,
    ) -> None:
        self.kind = kind
        self.argument = argument
        self.value_type = value_type
        self.key = key


def _classify_member(
    model: type[BaseModel],
    name: str,
    member: object,
) -> _Member | None:
    if _is_file_base(member):
        raise NodeContractError(
            f"{model.__name__}.{name} cannot use File; name a declared file class"
        )
    if member is ArtifactRef or member is ArtifactRefSequence:
        raise NodeContractError(
            f"{model.__name__}.{name} must use Ref, not {member.__name__}"
        )
    if member is Ref or member is RefSequence:
        raise NodeContractError(
            f"{model.__name__}.{name} must parameterize {member.__name__}"
        )
    ref = _ref_parameter(member)
    if ref is not None:
        origin, argument = ref
        kind = "ref" if origin is Ref else "refseq"
        if argument is Any:
            return _Member(kind, argument, None, None)
        declared = _declared_class(argument)
        if declared is None:
            raise NodeContractError(
                f"{model.__name__}.{name} Ref argument is not a declared value class"
            )
        value_type, key = declared
        return _Member(kind, value_type, value_type, key)
    declared = _declared_class(member)
    if declared is None:
        return None
    value_type, key = declared
    return _Member("value", value_type, value_type, key)


def _value_port(
    model: type[BaseModel],
    name: str,
    members: list[_Member],
    *,
    output: bool,
) -> _Described:
    if output and len(members) != 1:
        raise NodeContractError(
            f"{model.__name__}.{name} output cannot be a union of value classes"
        )
    keys = tuple(_required_key(model, name, member) for member in members)
    value_types = _concrete_type(
        model,
        name,
        tuple(_required_type(model, name, member) for member in members),
    )
    return _Described(
        shape=PortShape.ONE,
        accepted_shapes=(PortShape.ONE,),
        value_types=value_types,
        accepts=keys[0],
        also_accepts=keys[1:],
        preserves_ref_container=False,
        allows_none=False,
        value_type=None if output and len(value_types) != 1 else value_types[0],
    )


def _ref_port(
    model: type[BaseModel],
    name: str,
    members: list[_Member],
    plugs: Plugs | None,
    binds: Binds | None,
    *,
    output: bool,
) -> _Described:
    del output
    generic = any(member.argument is Any for member in members)
    if generic and any(member.argument is not Any for member in members):
        raise NodeContractError(
            f"{model.__name__}.{name} mixes a generic Ref with a concrete Ref"
        )
    if generic and binds is None:
        raise NodeContractError(f"{model.__name__}.{name} generic port requires Binds")
    if not generic and binds is not None:
        raise NodeContractError(
            f"{model.__name__}.{name} concrete port cannot declare Binds"
        )
    kinds = {member.kind for member in members}
    mixed = kinds == {"ref", "refseq"}
    if mixed:
        if len(members) != 2:
            raise NodeContractError(
                f"{model.__name__}.{name} must use Ref and RefSequence together"
            )
        if plugs is None or not plugs.instance:
            raise NodeContractError(
                f"{model.__name__}.{name}: Ref and RefSequence together require "
                "Plugs instance"
            )
        shape = PortShape.ONE
        accepted = (PortShape.ONE, PortShape.MANY)
    elif kinds == {"refseq"}:
        shape = PortShape.MANY
        accepted = (PortShape.MANY,)
    else:
        shape = PortShape.ONE
        accepted = (PortShape.ONE,)
    if generic:
        assert binds is not None
        accepts: ArtifactTypeKey | ArtifactTypeVariable = ArtifactTypeVariable(
            binds.variable
        )
        also: tuple[ArtifactTypeKey, ...] = ()
    else:
        keys = tuple(_required_key(model, name, member) for member in members)
        accepts = keys[0]
        also = tuple(key for key in keys[1:] if key != accepts)
    return _Described(
        shape=shape,
        accepted_shapes=accepted,
        value_types=(),
        accepts=accepts,
        also_accepts=also,
        preserves_ref_container=True,
        allows_none=False,
        value_type=None,
    )


def _required_key(
    model: type[BaseModel],
    name: str,
    member: _Member,
) -> ArtifactTypeKey:
    if member.key is None:
        raise NodeContractError(
            f"{model.__name__}.{name} is missing an artifact type key"
        )
    return member.key


def _required_type(
    model: type[BaseModel],
    name: str,
    member: _Member,
) -> type[object]:
    if member.value_type is None:
        raise NodeContractError(f"{model.__name__}.{name} is missing a value class")
    return member.value_type


def _declared_class(member: object) -> tuple[type[object], ArtifactTypeKey] | None:
    if member is StrictStr:
        member = str
    elif member is StrictInt:
        member = int
    if not isinstance(member, type):
        return None
    key = declared_key(member)
    if key is None:
        return None
    return member, key


def _ref_parameter(member: object) -> tuple[type[object], object] | None:
    if not isinstance(member, type):
        return None
    metadata = cast(object, getattr(member, "__pydantic_generic_metadata__", None))
    if not isinstance(metadata, dict):
        return None
    items = cast(dict[object, object], metadata)
    origin = items.get("origin")
    if origin is not Ref and origin is not RefSequence:
        return None
    args = items.get("args")
    if not isinstance(args, tuple):
        return None
    parameters = cast(tuple[object, ...], args)
    if len(parameters) != 1:
        return None
    return cast(type[object], origin), parameters[0]


def _is_file_base(member: object) -> bool:
    return (
        isinstance(member, type)
        and member.__module__ == "grafy_core.documents"
        and member.__name__ == "File"
    )


def _without_none(annotation: object) -> tuple[tuple[object, ...], bool]:
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    origin = get_origin(annotation)
    if origin not in (UnionType, Union):
        return (annotation,), False
    members: list[object] = []
    for member in get_args(annotation):
        while get_origin(member) is Annotated:
            member = get_args(member)[0]
        members.append(member)
    if type(None) not in members:
        return tuple(members), False
    return tuple(member for member in members if member is not type(None)), True


def _is_sequence_origin(origin: object) -> bool:
    return origin is list


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
            f"{model.__name__}.{field_name} must use a list annotation for {purpose}"
        )
        raise NodeContractError(message)
    args = get_args(annotation)
    if len(args) == 0:
        message = (
            f"{model.__name__}.{field_name} must declare an item type for {purpose}"
        )
        raise NodeContractError(message)
    return args[0]


def validate_service_node(
    name: str,
    inputs: InputContract[Any],
    outputs: OutputContract[Any],
) -> None:
    """Reject a node shape v1 does not run.

    A service output is a whole node: it has no input ports and no artifact
    outputs. A service port is one value. The port specs already reject a
    variadic or instance-plug service port; this checks the node around them.
    """

    service_outputs = [
        port for port in outputs.ports.values() if port.kind == "service"
    ]
    for port in inputs.ports.values():
        if port.kind == "service" and (
            port.shape is not PortShape.ONE or port.variadic or port.instance_plugs
        ):
            raise NodeContractError(
                f"{name}.{port.name} service port must be one value, not "
                "variadic or instance plugs"
            )
    for port in service_outputs:
        if port.shape is not PortShape.ONE:
            raise NodeContractError(
                f"{name}.{port.name} service port must be one value, not "
                "variadic or instance plugs"
            )
    if not service_outputs:
        return
    if inputs.ports:
        raise NodeContractError(
            f"{name} declares a service output and cannot declare input ports"
        )
    if any(port.kind != "service" for port in outputs.ports.values()):
        raise NodeContractError(
            f"{name} declares a service output and cannot declare an artifact output"
        )


def _concrete_type(
    model: type[BaseModel],
    field_name: str,
    annotations: tuple[type[object], ...],
) -> tuple[type[object], ...]:
    """Return declared value classes in catalog order, including a union."""

    if not annotations:
        raise NodeContractError(
            f"{model.__name__}.{field_name} is missing a value class"
        )
    resolved: list[type[object]] = []
    for annotation in annotations:
        declared = _declared_class(annotation)
        if declared is None:
            message = (
                f"{model.__name__}.{field_name} artifact value type must be a "
                f"declared class, got {annotation!r}"
            )
            raise NodeContractError(message)
        resolved.append(declared[0])
    return tuple(resolved)
