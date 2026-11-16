from collections.abc import Sequence
from types import UnionType
from typing import Annotated, Union, cast, get_args, get_origin

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactTypeKey,
    ArtifactTypeSpec,
    ArtifactRef,
    ArtifactRefSequence,
)
from grafy_core.node_ports import (
    InPort,
    InputContract,
    InputPortSpec,
    NodeContractError,
    OutPort,
    OutputContract,
    OutputPortSpec,
    PortShape,
)


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
            spare_plugs=port.spare_plugs,
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
