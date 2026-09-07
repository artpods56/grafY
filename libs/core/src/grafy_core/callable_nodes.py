"""Compile ordinary Python callables into the existing node contracts."""

import asyncio
from collections.abc import Callable, Mapping
from inspect import (
    Parameter,
    getdoc,
    isasyncgenfunction,
    iscoroutinefunction,
    isfunction,
    isgeneratorfunction,
    signature,
)
from keyword import iskeyword
import re
from types import UnionType
from typing import (
    Annotated,
    Any,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    override,
)

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, create_model
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.artifacts import ArtifactTypeSpec, NodeConfig, NodeInput, NodeOutput
from grafy_core.nodes import (
    ConfigContract,
    InPort,
    Node,
    NodeContractError,
    NodeExecutionContext,
    OutPort,
    derive_input_contract,
    derive_output_contract,
)


def _annotation_parts(annotation: object) -> tuple[object, tuple[object, ...]]:
    if get_origin(annotation) is Annotated:
        value, *metadata = get_args(annotation)
        return value, tuple(metadata)
    return annotation, ()


def _without_none(annotation: object) -> tuple[object, bool]:
    value, _ = _annotation_parts(annotation)
    if get_origin(value) not in (Union, UnionType):
        return value, False
    args = get_args(value)
    non_null = tuple(arg for arg in args if arg is not type(None))
    if len(non_null) == 1 and len(non_null) != len(args):
        return non_null[0], True
    return value, False


def _inferred_artifact(annotation: object) -> ArtifactTypeSpec | None:
    value, _ = _without_none(annotation)
    if get_origin(value) is list:
        args = get_args(value)
        if len(args) != 1:
            return None
        value, _ = _annotation_parts(args[0])
    value, _ = _annotation_parts(value)
    if value is str:
        return TEXT_VALUE
    if value is int:
        return INTEGER_VALUE
    return None


def _validate_field(name: str, annotation: object) -> tuple[object, ...]:
    if (
        not name.isidentifier()
        or iskeyword(name)
        or name.startswith("_")
        or hasattr(BaseModel, name)
    ):
        raise NodeContractError(
            f"Field {name!r} must be a non-private Python identifier that does "
            "not shadow a Pydantic model attribute"
        )
    _, metadata = _annotation_parts(annotation)
    for item in metadata:
        if not isinstance(item, FieldInfo):
            continue
        if (
            item.alias is not None
            or item.validation_alias is not None
            or item.serialization_alias is not None
        ):
            raise NodeContractError(
                f"Field {name!r} cannot declare aliases; callable field names "
                "are the graph contract names"
            )
        if item.default is not PydanticUndefined or item.default_factory is not None:
            raise NodeContractError(
                f"Field {name!r} must use an ordinary Python parameter default, "
                "not a default inside Field metadata"
            )
    return metadata


def callable_node_class(
    function: Callable[..., object],
    *,
    operator_id: str,
    version: int,
    output_name: str,
) -> type[Node[NodeConfig, NodeInput, NodeOutput]]:
    """Derive one artifact output, positional inputs, and keyword configuration.

    This compiler does not register nodes or artifact types. Registration remains
    atomic at the owning Plugin, and artifact ownership remains explicit.
    """
    if not isfunction(function):
        raise NodeContractError("callable_node requires a Python function")
    if isgeneratorfunction(function) or isasyncgenfunction(function):
        raise NodeContractError(
            "callable_node does not accept generator functions; return a list "
            "for an artifact sequence"
        )
    try:
        hints = get_type_hints(function, include_extras=True)
    except Exception as exc:
        raise NodeContractError("Callable has unresolvable type annotations") from exc

    parameters = tuple(signature(function).parameters.values())
    input_fields: dict[str, tuple[object, object]] = {}
    config_fields: dict[str, tuple[object, object]] = {}
    positional_names: list[str] = []
    context_name: str | None = None
    for index, parameter in enumerate(parameters):
        name = parameter.name
        if parameter.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
            raise NodeContractError(
                f"Parameter {name!r} cannot use *args or **kwargs; declare named "
                "graph inputs and keyword-only configuration"
            )
        if name not in hints:
            raise NodeContractError(f"Parameter {name!r} requires a type annotation")
        annotation = hints[name]
        value_type, _ = _annotation_parts(annotation)
        if value_type is NodeExecutionContext:
            if (
                index != 0
                or annotation is not NodeExecutionContext
                or parameter.kind is Parameter.KEYWORD_ONLY
                or parameter.default is not Parameter.empty
            ):
                raise NodeContractError(
                    f"Parameter {name!r}: NodeExecutionContext must be the first "
                    "positional parameter with no default or annotation metadata"
                )
            context_name = name
            positional_names.append(name)
            continue

        metadata = _validate_field(name, annotation)
        input_ports = [item for item in metadata if isinstance(item, InPort)]
        if any(isinstance(item, OutPort) for item in metadata):
            raise NodeContractError(f"Parameter {name!r} cannot declare OutPort")
        if len(input_ports) > 1:
            raise NodeContractError(
                f"Parameter {name!r} declares multiple InPort markers"
            )
        default = parameter.default
        if isinstance(default, FieldInfo):
            raise NodeContractError(
                f"Parameter {name!r} cannot use Field as its default; put "
                "constraints in Annotated and use an ordinary Python default"
            )
        if parameter.kind is Parameter.KEYWORD_ONLY:
            if input_ports:
                raise NodeContractError(
                    f"Keyword-only parameter {name!r} is configuration and cannot "
                    "declare InPort; move it before * to declare a graph input"
                )
            if default is not Parameter.empty:
                default_adapter: TypeAdapter[object] = TypeAdapter(annotation)
                try:
                    default_adapter.validate_python(default, strict=True)
                except ValidationError as exc:
                    raise NodeContractError(
                        f"Configuration parameter {name!r} has a default that "
                        "does not satisfy its annotated type and constraints"
                    ) from exc
            config_fields[name] = (
                annotation,
                ... if default is Parameter.empty else default,
            )
            continue

        _, nullable = _without_none(annotation)
        if default is not Parameter.empty and (default is not None or not nullable):
            raise NodeContractError(
                f"Graph input {name!r} may default only to None with a nullable "
                "annotation; use keyword-only parameters for configuration defaults"
            )
        if not input_ports:
            artifact = _inferred_artifact(annotation)
            if artifact is None:
                raise NodeContractError(
                    f"Graph input {name!r} needs an explicit InPort artifact "
                    "contract; only str, int, and their list/optional forms are inferred"
                )
            annotation = Annotated[annotation, InPort(artifact)]
        input_fields[name] = (
            annotation,
            ... if default is Parameter.empty else default,
        )
        positional_names.append(name)

    if "return" not in hints:
        raise NodeContractError("Callable requires a return type annotation")
    output_annotation = hints["return"]
    output_metadata = _validate_field(output_name, output_annotation)
    output_ports = [item for item in output_metadata if isinstance(item, OutPort)]
    if any(isinstance(item, InPort) for item in output_metadata):
        raise NodeContractError("Return annotation cannot declare InPort")
    if len(output_ports) > 1:
        raise NodeContractError("Return annotation declares multiple OutPort markers")
    output_type, nullable = _without_none(output_annotation)
    output_origin = get_origin(output_type)
    if (
        nullable
        or output_type is type(None)
        or output_origin in (tuple, dict, Mapping)
        or isinstance(output_type, type)
        and issubclass(output_type, NodeOutput)
    ):
        raise NodeContractError(
            "callable_node requires one non-null artifact output; use "
            "function_node with a NodeOutput model for advanced or multiple outputs"
        )
    if output_origin is list:
        output_args = get_args(output_type)
        if output_args and _without_none(output_args[0])[1]:
            raise NodeContractError(
                "Artifact output sequences cannot contain nullable items"
            )
    if not output_ports:
        artifact = _inferred_artifact(output_annotation)
        if artifact is None:
            raise NodeContractError(
                "Return annotation needs an explicit OutPort artifact contract; "
                "only str, int, and their list forms are inferred"
            )
        output_annotation = Annotated[output_annotation, OutPort(artifact)]

    model_prefix = re.sub(r"\W", "_", f"Callable_{operator_id}_v{version}")
    # Pydantic accepts dynamic field definitions through **kwargs. Names were
    # checked above so they cannot bind its reserved model-construction options.
    config_model = create_model(
        f"{model_prefix}_Config",
        __base__=NodeConfig,
        __config__=ConfigDict(validate_default=True),
        **cast(dict[str, Any], config_fields),
    )
    input_model = create_model(
        f"{model_prefix}_Inputs",
        __base__=NodeInput,
        **cast(dict[str, Any], input_fields),
    )
    output_model = create_model(
        f"{model_prefix}_Outputs",
        __base__=NodeOutput,
        **cast(dict[str, Any], {output_name: (output_annotation, ...)}),
    )
    if (
        set(config_model.model_fields) != set(config_fields)
        or set(input_model.model_fields) != set(input_fields)
        or set(output_model.model_fields) != {output_name}
    ):
        raise NodeContractError("Pydantic could not preserve the callable field names")
    # These schemas are part of every published node's catalog contract.
    for model in (config_model, input_model, output_model):
        model.model_json_schema()

    class CallableNodeAdapter(Node[NodeConfig, NodeInput, NodeOutput]):
        @override
        async def run(
            self,
            context: NodeExecutionContext,
            config: NodeConfig,
            inputs: NodeInput,
            /,
        ) -> NodeOutput:
            args = [
                context if name == context_name else getattr(inputs, name)
                for name in positional_names
            ]
            kwargs = {name: getattr(config, name) for name in config_fields}
            if iscoroutinefunction(function):
                result = await function(*args, **kwargs)
            else:
                result = await asyncio.to_thread(function, *args, **kwargs)
            return output_model.model_validate({output_name: result}, strict=True)

    CallableNodeAdapter.__name__ = function.__name__
    CallableNodeAdapter.__qualname__ = function.__qualname__
    CallableNodeAdapter.__doc__ = getdoc(function)
    CallableNodeAdapter.config_contract = ConfigContract(model=config_model)
    CallableNodeAdapter.input_contract = derive_input_contract(input_model)
    CallableNodeAdapter.output_contract = derive_output_contract(output_model)
    return CallableNodeAdapter
