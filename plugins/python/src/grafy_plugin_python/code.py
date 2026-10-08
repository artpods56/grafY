"""The Python node's code model: payload classes, analysis and execution.

Node code is an optional ``Params`` class plus one ``transform`` function whose
first parameter is the data input. ``params`` and ``context`` may follow. Port
types come from the annotations and must be artifact types the release declares.
This module runs only inside the Plugin sandbox.
"""

import ast
import contextlib
import keyword
import re
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import NoneType, UnionType
from typing import Literal, Union, cast, get_args, get_origin, get_type_hints

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec, JsonObject
from grafy_core.nodes import PortShape


CODE_FILENAME = "transform.py"
MAX_CODE_LENGTH = 65_536
MAX_MESSAGE_LENGTH = 900
# Names the code module already binds; a payload class must not shadow them.
_RESERVED = {
    "BaseModel",
    "ConfigDict",
    "Context",
    "Field",
    "Literal",
    "Params",
    "transform",
}
_SCALAR_TYPES: Mapping[str, type[object]] = {"string": str, "integer": int}
_PARAM_SCALARS: tuple[type[object], ...] = (str, int, float, bool)


class Context(BaseModel):
    """Where one invocation runs. It carries no credentials and no artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    node_id: str | None = None
    graph_id: str | None = None
    graph_revision: int | None = None
    run_id: str | None = None
    item_index: int | None = Field(
        default=None,
        description="Position in the sequence when a map edge runs the node per item",
    )


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: int = Field(ge=1)
    column: int = Field(default=0, ge=0)
    message: str


class ArtifactTypeReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: int = Field(ge=1)

    @classmethod
    def of(cls, key: ArtifactTypeKey) -> "ArtifactTypeReference":
        return cls(id=key.id, schema_version=key.schema_version)


class PortContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: ArtifactTypeReference
    shape: PortShape


class CodeContract(BaseModel):
    """What Apply stores: the ports and params schema the code declares."""

    model_config = ConfigDict(extra="forbid")

    input_name: str
    input: PortContract
    output: PortContract
    params_schema: dict[str, JsonValue] | None = None


class InspectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: CodeContract | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list[Diagnostic])


class ParamsError(ValueError):
    """The node's params do not satisfy its ``Params`` class."""


class CodeError(Exception):
    """User code is not a valid Python node, anchored to one line."""

    def __init__(self, line: int, message: str, column: int = 0) -> None:
        super().__init__(message)
        self.line = max(1, line)
        self.column = max(0, column)
        self.message = _bounded(message)

    def diagnostic(self) -> Diagnostic:
        return Diagnostic(line=self.line, column=self.column, message=self.message)


@dataclass(frozen=True, slots=True)
class PortType:
    """One artifact type as user code sees it: ``str``, ``int`` or a class."""

    name: str
    spec: ArtifactTypeSpec
    python_type: type[object]

    @property
    def scalar(self) -> bool:
        return not issubclass(self.python_type, BaseModel)

    def value(self, payload: JsonObject) -> object:
        if not self.scalar:
            return cast(type[BaseModel], self.python_type).model_validate(payload)
        if set(payload) != {"value"}:
            raise ValueError(f"{self.spec.key.id} payload must hold one 'value'")
        return TypeAdapter(self.python_type).validate_python(
            payload["value"], strict=True
        )

    def payload(self, value: object) -> JsonObject:
        if not self.scalar:
            if not isinstance(value, self.python_type):
                raise TypeError(f"expected {self.name}, got {_type_label(type(value))}")
            return cast(
                JsonObject,
                cast(BaseModel, value).model_dump(
                    mode="json", by_alias=True, exclude_unset=True
                ),
            )
        try:
            scalar = TypeAdapter(self.python_type).validate_python(value, strict=True)
        except ValidationError as exc:
            raise TypeError(
                f"expected {self.name}, got {_type_label(type(value))}"
            ) from exc
        return {"value": cast(JsonValue, scalar)}


def port_types(specs: Sequence[ArtifactTypeSpec]) -> tuple[PortType, ...]:
    """Name every declared artifact type the way node code annotates it."""

    structured = [
        spec for spec in specs if spec.materialized_json_type not in _SCALAR_TYPES
    ]
    source, roots = payload_classes_source(structured)
    namespace: dict[str, object] = {"__name__": "grafy_payload_classes"}
    exec(compile(source, "<grafy payload classes>", "exec"), namespace)
    types: list[PortType] = []
    for spec in specs:
        scalar = (
            None
            if spec.materialized_json_type is None
            else _SCALAR_TYPES.get(spec.materialized_json_type)
        )
        if scalar is not None:
            types.append(PortType(name=scalar.__name__, spec=spec, python_type=scalar))
            continue
        name = roots[spec.key]
        types.append(
            PortType(name=name, spec=spec, python_type=cast(type, namespace[name]))
        )
    return tuple(types)


def class_name(spec: ArtifactTypeSpec) -> str:
    """``Text value`` becomes ``TextValue``; the id is the fallback for odd titles."""

    for candidate in (spec.title, spec.key.id.rsplit(".", 1)[-1]):
        words = re.findall(r"[A-Za-z0-9]+", candidate)
        name = "".join(word[:1].upper() + word[1:] for word in words)
        if name and not name[0].isdigit():
            return f"{name}Payload" if name in _RESERVED else name
    return "Payload"


def payload_classes_source(
    specs: Sequence[ArtifactTypeSpec],
) -> tuple[str, dict[ArtifactTypeKey, str]]:
    """Generate Pydantic classes for structured payloads, named after titles.

    Unsupported shapes are refused instead of offering fields the runner
    cannot fill.
    """

    declarations: list[str] = [
        "from typing import Literal",
        "",
        "from pydantic import BaseModel, ConfigDict, Field",
        "",
        "",
    ]
    taken = set(_RESERVED)
    roots: dict[ArtifactTypeKey, str] = {}
    for spec in specs:
        if spec.bundle.format not in {"inline-json", "table-bundle"} or spec.references:
            raise ValueError(
                "Python nodes carry inline artifacts without artifact references"
            )
        root = class_name(spec)
        if root in taken:
            root = f"{root}{spec.key.schema_version}"
        if root in taken:
            raise ValueError(f"Payload class name {root!r} is already taken")
        roots[spec.key] = root
        _ = _ShapeGenerator(spec.payload_schema, declarations, taken).annotation(
            spec.payload_schema, root, (), root=True
        )
    return "\n".join(declarations), roots


def _pascal(field: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in field.split("_") if part)


class _ShapeGenerator:
    def __init__(
        self, schema: JsonObject, declarations: list[str], taken: set[str]
    ) -> None:
        self.schema = schema
        self.declarations = declarations
        self.taken = taken
        self.aliases: dict[str, str] = {}

    def _claim(self, name: str) -> str:
        candidate, suffix = name, 2
        while candidate in self.taken:
            candidate, suffix = f"{name}{suffix}", suffix + 1
        self.taken.add(candidate)
        return candidate

    def annotation(
        self, schema: object, name: str, refs: tuple[str, ...], *, root: bool = False
    ) -> str:
        if len(refs) > 20 or len(self.declarations) > 2000:
            raise ValueError("Payload schema is too complex for a Python node")
        if not isinstance(schema, dict):
            raise ValueError(f"Unsupported payload schema for {name}")
        definition = cast(JsonObject, schema)
        ref = definition.get("$ref")
        if isinstance(ref, str):
            if not ref.startswith("#/$defs/"):
                raise ValueError(f"Unsupported schema reference: {ref}")
            if ref in self.aliases:
                return self.aliases[ref]
            if ref in refs:
                raise ValueError(f"Recursive object schema reference: {ref}")
            defs = self.schema.get("$defs")
            if not isinstance(defs, dict):
                raise ValueError(f"Missing schema definition: {ref}")
            target = cast(JsonObject, defs).get(ref[8:])
            if isinstance(target, dict) and "anyOf" in target:
                alias = self._claim(name)
                self.aliases[ref] = alias
                annotation = self.annotation(
                    cast(JsonObject, target), alias, (*refs, ref)
                )
                self.declarations.extend([f"type {alias} = {annotation}", "", ""])
                return alias
            return self.annotation(
                cast(JsonObject, target), name, (*refs, ref), root=root
            )
        alternatives = definition.get("anyOf", definition.get("oneOf"))
        if isinstance(alternatives, list) and not root:
            return " | ".join(
                self.annotation(item, f"{name}{index + 1}", refs)
                for index, item in enumerate(cast(list[object], alternatives))
            )
        choices = definition.get("enum")
        if (
            isinstance(choices, list)
            and choices
            and all(
                isinstance(choice, (str, int, bool))
                for choice in cast(list[object], choices)
            )
        ):
            rendered = ", ".join(repr(choice) for choice in cast(list[object], choices))
            return f"Literal[{rendered}]"
        kind = definition.get("type")
        if isinstance(kind, list) and not root:
            return " | ".join(
                self.annotation({**definition, "type": item}, name, refs)
                for item in cast(list[object], kind)
            )
        primitives = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "null": "None",
        }
        if isinstance(kind, str) and kind in primitives and not root:
            return primitives[kind]
        if kind == "array" and not root:
            item = self.annotation(definition.get("items"), name + "Item", refs)
            return f"list[{item}]"
        if kind != "object":
            raise ValueError(f"Unsupported payload schema at {name}")
        properties = definition.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError(f"Invalid object properties at {name}")
        extra = definition.get("additionalProperties", False)
        if not properties and not root and isinstance(extra, dict):
            value = self.annotation(cast(JsonObject, extra), name + "Value", refs)
            return f"dict[str, {value}]"
        if extra is not False:
            raise ValueError(f"Payload objects must have fixed fields: {name}")
        name = name if root else self._claim(name)
        if root:
            self.taken.add(name)
        fields: list[str] = []
        required = definition.get("required", [])
        for field, child in cast(JsonObject, properties).items():
            if (
                not field.isidentifier()
                or keyword.iskeyword(field)
                or field.startswith("_")
                or hasattr(BaseModel, field)
            ):
                raise ValueError(
                    f"Field {field!r} cannot be exposed as a Python attribute"
                )
            annotation = self.annotation(child, f"{name}{_pascal(field)}", refs)
            default = ""
            if field not in cast(list[str], required):
                annotation += " | None"
                default = "default=None, "
            description = (
                cast(JsonObject, child).get("description", "")
                if isinstance(child, dict)
                else ""
            )
            fields.append(
                f"    {field}: {annotation} = Field({default}description={description!r})"
            )
        self.declarations.extend(
            [
                f"class {name}(BaseModel):",
                "    model_config = ConfigDict(extra='forbid', strict=True)",
                *fields,
                "",
                "",
            ]
        )
        return name


@dataclass(frozen=True, slots=True)
class _Signature:
    function: ast.FunctionDef
    data: ast.arg
    params: ast.arg | None
    context: ast.arg | None
    params_class: ast.ClassDef | None


@dataclass(frozen=True, slots=True)
class LoadedCode:
    """Executed code with its contract, ready to run invocations."""

    contract: CodeContract
    transform: Callable[..., object]
    input_type: PortType
    output_type: PortType
    params_model: type[BaseModel] | None
    takes_context: bool

    def run(
        self,
        payload: JsonObject | list[JsonObject],
        params: Mapping[str, JsonValue],
        context: Context,
    ) -> JsonObject | list[JsonObject]:
        """Call ``transform`` on one input and return the output payload(s)."""

        input_value = (
            [self.input_type.value(item) for item in payload]
            if isinstance(payload, list)
            else self.input_type.value(payload)
        )
        arguments: dict[str, object] = {}
        if self.params_model is not None:
            try:
                arguments["params"] = self.params_model.model_validate(params)
            except ValidationError as exc:
                raise ParamsError(f"Params are invalid: {_errors(exc)}") from exc
        if self.takes_context:
            arguments["context"] = context
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result = self.transform(input_value, **arguments)
        except Exception as exc:
            raise _user_code_error(exc) from exc
        try:
            if self.contract.output.shape is PortShape.ONE:
                return self.output_type.payload(result)
            if not isinstance(result, list | tuple):
                raise TypeError(
                    f"expected list[{self.output_type.name}], "
                    f"got {_type_label(type(result))}"
                )
            items = cast(Sequence[object], result)
            return [self.output_type.payload(item) for item in items]
        except (TypeError, ValueError) as exc:
            raise CodeError(
                self.transform.__code__.co_firstlineno,
                f"transform returned the wrong type: {exc}",
            ) from exc


def inspect_code(code: str, types: Sequence[PortType]) -> InspectionReport:
    """Derive the contract Apply stores, or the diagnostics that block it."""

    try:
        loaded = load_code(code, types)
    except CodeError as exc:
        return InspectionReport(diagnostics=[exc.diagnostic()])
    return InspectionReport(contract=loaded.contract)


def load_code(code: str, types: Sequence[PortType]) -> LoadedCode:
    if len(code) > MAX_CODE_LENGTH:
        raise CodeError(1, f"Code must be at most {MAX_CODE_LENGTH} characters")
    signature = _signature(code)
    namespace = _execute_module(code, types)
    return _resolve(signature, namespace, types)


def _signature(code: str) -> _Signature:
    try:
        tree = ast.parse(code, filename=CODE_FILENAME)
    except SyntaxError as exc:
        raise CodeError(
            exc.lineno or 1,
            f"SyntaxError: {exc.msg}",
            column=(exc.offset or 1) - 1,
        ) from exc
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == "transform"
    ]
    if not functions:
        raise CodeError(1, "Define one top-level function `def transform(...)`")
    if len(functions) > 1:
        raise CodeError(functions[1].lineno, "Define `transform` only once")
    function = functions[0]
    if isinstance(function, ast.AsyncFunctionDef):
        raise CodeError(function.lineno, "`transform` must not be async")
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Params"
    ]
    if len(classes) > 1:
        raise CodeError(classes[1].lineno, "Define `Params` only once")
    params_class = classes[0] if classes else None
    arguments = function.args
    if (
        arguments.posonlyargs
        or arguments.vararg
        or arguments.kwarg
        or arguments.kwonlyargs
    ):
        raise CodeError(
            function.lineno,
            "`transform` takes one data input, then optional `params` and "
            "`context`, without *args, **kwargs, / or * markers",
        )
    if arguments.defaults:
        raise CodeError(function.lineno, "`transform` parameters cannot have defaults")
    named = {arg.arg: arg for arg in arguments.args if arg.arg in {"params", "context"}}
    data = [arg for arg in arguments.args if arg.arg not in {"params", "context"}]
    if len(data) != 1:
        raise CodeError(
            function.lineno,
            "`transform` takes exactly one data input besides `params` and `context`",
        )
    if arguments.args[0] is not data[0]:
        raise CodeError(data[0].lineno, "The data input must be the first parameter")
    if data[0].annotation is None:
        raise CodeError(
            data[0].lineno,
            f"Annotate `{data[0].arg}` with its type, for example `{data[0].arg}: str`",
        )
    if function.returns is None:
        raise CodeError(
            function.lineno,
            "Annotate what `transform` returns, for example `-> str`",
        )
    params = named.get("params")
    if params_class is None and params is not None:
        raise CodeError(params.lineno, "`params` needs a `class Params(BaseModel)`")
    if params_class is not None and params is None:
        raise CodeError(function.lineno, "Add `params: Params` to `transform`")
    return _Signature(
        function=function,
        data=data[0],
        params=params,
        context=named.get("context"),
        params_class=params_class,
    )


def _execute_module(code: str, types: Sequence[PortType]) -> dict[str, object]:
    namespace: dict[str, object] = {
        "__name__": "grafy_transform",
        "BaseModel": BaseModel,
        "Context": Context,
        "Field": Field,
        "Literal": Literal,
    }
    namespace.update({port.name: port.python_type for port in types if not port.scalar})
    try:
        with contextlib.redirect_stdout(sys.stderr):
            exec(compile(code, CODE_FILENAME, "exec"), namespace)
    except Exception as exc:
        raise _user_code_error(exc) from exc
    return namespace


def _resolve(
    signature: _Signature,
    namespace: Mapping[str, object],
    types: Sequence[PortType],
) -> LoadedCode:
    function = signature.function
    transform = namespace.get("transform")
    if not callable(transform) or not hasattr(transform, "__code__"):
        raise CodeError(function.lineno, "`transform` must stay a function")
    try:
        hints = get_type_hints(transform, globalns=dict(namespace))
    except Exception as exc:
        raise CodeError(
            function.lineno,
            f"The annotations of `transform` do not resolve: {exc}",
        ) from exc
    data_annotation = signature.data.annotation
    returns = function.returns
    assert data_annotation is not None and returns is not None
    input_type, input_shape = _port(
        hints.get(signature.data.arg),
        types,
        line=data_annotation.lineno,
        role=f"input `{signature.data.arg}`",
    )
    output_type, output_shape = _port(
        hints.get("return"),
        types,
        line=returns.lineno,
        role="return",
    )
    params_model: type[BaseModel] | None = None
    if signature.params_class is not None:
        candidate = namespace.get("Params")
        if not isinstance(candidate, type) or not issubclass(candidate, BaseModel):
            raise CodeError(
                signature.params_class.lineno, "`Params` must subclass `BaseModel`"
            )
        params_model = candidate
        params = signature.params
        if (
            params is not None
            and params.annotation is not None
            and hints.get("params") is not params_model
        ):
            raise CodeError(params.lineno, "Annotate `params` as `Params`")
        _check_params(params_model, signature.params_class)
    context = signature.context
    if (
        context is not None
        and context.annotation is not None
        and hints.get("context") is not Context
    ):
        raise CodeError(context.lineno, "Annotate `context` as `Context`")
    return LoadedCode(
        contract=CodeContract(
            input_name=signature.data.arg,
            input=PortContract(
                artifact_type=ArtifactTypeReference.of(input_type.spec.key),
                shape=input_shape,
            ),
            output=PortContract(
                artifact_type=ArtifactTypeReference.of(output_type.spec.key),
                shape=output_shape,
            ),
            params_schema=(
                None
                if params_model is None
                else cast(dict[str, JsonValue], params_model.model_json_schema())
            ),
        ),
        transform=transform,
        input_type=input_type,
        output_type=output_type,
        params_model=params_model,
        takes_context=context is not None,
    )


def _port(
    hint: object,
    types: Sequence[PortType],
    *,
    line: int,
    role: str,
) -> tuple[PortType, PortShape]:
    item, shape = hint, PortShape.ONE
    if get_origin(hint) is list and len(get_args(hint)) == 1:
        item, shape = get_args(hint)[0], PortShape.MANY
    for port in types:
        if item is port.python_type:
            return port, shape
    names = ", ".join(port.name for port in types)
    raise CodeError(
        line,
        f"The {role} type {_type_label(hint)} is not an artifact type this node "
        f"carries; use {names}, or list[...] of one of them",
    )


def _check_params(model: type[BaseModel], declaration: ast.ClassDef) -> None:
    lines = {
        statement.target.id: statement.lineno
        for statement in declaration.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
    }
    for name, field in model.model_fields.items():
        if _supported_param(field.annotation):
            continue
        raise CodeError(
            lines.get(name, declaration.lineno),
            f"Params field `{name}` has type {_type_label(field.annotation)}; "
            "the params form supports str, int, float, bool, Literal[...], "
            "list[str] and their optional forms",
        )


def _supported_param(annotation: object) -> bool:
    if get_origin(annotation) in (Union, UnionType):
        members = get_args(annotation)
        values = [member for member in members if member is not NoneType]
        return (
            len(members) == 2 and len(values) == 1 and _supported_param_value(values[0])
        )
    return _supported_param_value(annotation)


def _supported_param_value(annotation: object) -> bool:
    if any(annotation is scalar for scalar in _PARAM_SCALARS):
        return True
    if get_origin(annotation) is Literal:
        return all(
            isinstance(choice, str | int) and not isinstance(choice, bool)
            for choice in get_args(annotation)
        )
    return get_origin(annotation) is list and get_args(annotation) == (str,)


def _user_code_error(exc: BaseException) -> CodeError:
    lines = [
        frame.lineno
        for frame in traceback.extract_tb(exc.__traceback__)
        if frame.filename == CODE_FILENAME and frame.lineno is not None
    ]
    line = lines[-1] if lines else 1
    return CodeError(line, f"{type(exc).__name__}: {exc}")


def _errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'params'}: {error['msg']}"
        for error in exc.errors()
    )


def _type_label(annotation: object) -> str:
    if annotation is None:
        return "None"
    if isinstance(annotation, type) and get_args(annotation) == ():
        return annotation.__name__
    return repr(annotation).replace("typing.", "")


def _bounded(message: str) -> str:
    message = message.strip() or "Python code failed"
    if len(message) <= MAX_MESSAGE_LENGTH:
        return message
    return message[: MAX_MESSAGE_LENGTH - 1] + "…"


__all__ = [
    "CODE_FILENAME",
    "MAX_CODE_LENGTH",
    "ArtifactTypeReference",
    "CodeContract",
    "CodeError",
    "Context",
    "Diagnostic",
    "InspectionReport",
    "LoadedCode",
    "ParamsError",
    "PortContract",
    "PortType",
    "class_name",
    "inspect_code",
    "load_code",
    "payload_classes_source",
    "port_types",
]
