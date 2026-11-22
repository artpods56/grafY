"""UI hints for node config schemas. These hints do not validate config values."""

import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from math import isfinite
from typing import Literal, cast, get_args

from pydantic import JsonValue

WidgetKind = Literal[
    "textarea", "slider", "color", "segmented", "switch", "one-based-integer"
]

_FLAG_KEYS = ("x-grafy-advanced", "x-grafy-hidden", "x-grafy-auto-id")
_WIDGETS: tuple[str, ...] = get_args(WidgetKind)
_ARTIFACT_TYPE_KEY = re.compile(r"[^@\s]+@[1-9][0-9]*")


def when_field_eq(field: str, value: JsonValue) -> dict[str, JsonValue]:
    return _checked_predicate({"field": field, "eq": value})


def when_field_neq(field: str, value: JsonValue) -> dict[str, JsonValue]:
    return _checked_predicate({"field": field, "neq": value})


def when_field_in(field: str, values: Sequence[JsonValue]) -> dict[str, JsonValue]:
    if not _is_sequence(values):
        raise ValueError("in must be a sequence of JSON values")
    return _checked_predicate({"field": field, "in": list(values)})


def when_field_truthy(field: str, expected: bool = True) -> dict[str, JsonValue]:
    return _checked_predicate({"field": field, "truthy": expected})


def when_port_connected(port: str, connected: bool = True) -> dict[str, JsonValue]:
    if not _is_boolean(connected):
        raise ValueError("connected must be a boolean")
    if connected:
        return _checked_predicate({"portConnected": port})
    return _checked_predicate({"portConnected": port, "is": False})


def when_port_artifact_type(
    port: str,
    *,
    in_types: Sequence[str] | None = None,
    not_in: Sequence[str] | None = None,
    when_unconnected: Literal["show", "hide"] | None = None,
) -> dict[str, JsonValue]:
    predicate: dict[str, JsonValue] = {"port": port}
    for key, types in (("in", in_types), ("notIn", not_in)):
        if types is None:
            continue
        if not _is_sequence(types):
            raise ValueError(f"{key} must be a sequence of artifact type keys")
        if types:
            predicate[key] = list(types)
    if when_unconnected is not None:
        predicate["whenUnconnected"] = when_unconnected
    return _checked_predicate({"portArtifactType": predicate})


def when_all(*predicates: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return _checked_predicate({"all": [_checked_predicate(p) for p in predicates]})


def when_any(*predicates: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return _checked_predicate({"any": [_checked_predicate(p) for p in predicates]})


def when_not(predicate: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {"not": _checked_predicate(predicate)}


def field_ui(
    *,
    advanced: bool = False,
    hidden: bool = False,
    auto_id: bool = False,
    widget: WidgetKind | None = None,
    enum_labels: Mapping[str, str] | None = None,
    group: str | None = None,
    visible_when: Mapping[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Build schema extensions for a Pydantic field."""
    extra: dict[str, JsonValue] = {}
    for key, value in zip(_FLAG_KEYS, (advanced, hidden, auto_id), strict=True):
        if not _is_boolean(value):
            raise ValueError(f"{key} must be a boolean")
        if value:
            extra[key] = True
    if widget is not None:
        if not _valid_widget(widget):
            raise ValueError(f"unknown x-grafy-widget {widget!r}")
        extra["x-grafy-widget"] = widget
    if enum_labels is not None:
        if not _valid_enum_labels(enum_labels):
            raise ValueError(
                "x-grafy-enum-labels must be a non-empty mapping of strings to strings"
            )
        extra["x-grafy-enum-labels"] = dict(enum_labels)
    if group is not None:
        if not _nonempty_string(group):
            raise ValueError("x-grafy-group must be a non-empty string")
        extra["x-grafy-group"] = group
    if visible_when is not None:
        extra["x-grafy-visible-when"] = _checked_predicate(visible_when)
    return extra


def _is_boolean(value: object) -> bool:
    return isinstance(value, bool)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _valid_widget(value: object) -> bool:
    return isinstance(value, str) and value in _WIDGETS


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _list(value: object) -> list[object]:
    if isinstance(value, list):
        return cast(list[object], value)
    return []


def _valid_enum_labels(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    labels = cast(Mapping[object, object], value)
    return bool(labels) and all(
        isinstance(key, str) and isinstance(label, str) for key, label in labels.items()
    )


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, int, bool)):
        return True
    if isinstance(value, float):
        return isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in cast(list[object], value))
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in cast(dict[object, object], value).items()
        )
    return False


def _artifact_predicate_error(value: object) -> str | None:
    predicate = _mapping(value)
    if not _nonempty_string(predicate.get("port")):
        return "portArtifactType.port must be a non-empty string"
    if predicate.keys() - {"port", "in", "notIn", "whenUnconnected"}:
        return "portArtifactType contains an unknown key"
    if not ("in" in predicate or "notIn" in predicate):
        return "portArtifactType requires in or notIn"
    for key in ("in", "notIn"):
        if key not in predicate:
            continue
        keys = _list(predicate[key])
        if not keys or not all(
            isinstance(item, str) and _ARTIFACT_TYPE_KEY.fullmatch(item)
            for item in keys
        ):
            return f"portArtifactType.{key} must be a non-empty list of id@version keys"
    if "whenUnconnected" in predicate and predicate["whenUnconnected"] not in (
        "show",
        "hide",
    ):
        return "portArtifactType.whenUnconnected must be 'show' or 'hide'"
    return None


def _predicate_error(
    value: object,
    *,
    fields: Collection[str] | None = None,
    field: str | None = None,
    ports: Collection[str] | None = None,
) -> str | None:
    predicate = _mapping(value)
    keys = set(predicate)
    if "field" in keys:
        name = predicate["field"]
        if not isinstance(name, str) or not _nonempty_string(name):
            return "field must be a non-empty string"
        operators = keys - {"field"}
        if len(operators) != 1:
            return "field predicate requires exactly one operator"
        operator = next(iter(operators))
        operand = predicate[operator]
        match operator:
            case "eq" | "neq":
                if not _is_json_value(operand):
                    return f"{operator} must be a JSON value"
            case "in":
                if not isinstance(operand, list) or not all(
                    _is_json_value(item) for item in cast(list[object], operand)
                ):
                    return "in must be a list of JSON values"
            case "truthy":
                if not isinstance(operand, bool):
                    return "truthy must be a boolean"
            case _:
                return f"unknown field operator {operator!r}"
        if field == name:
            return f"field {name!r} references itself"
        if fields is not None and name not in fields:
            return f"unknown sibling field {name!r}"
        return None
    if keys in ({"portConnected"}, {"portConnected", "is"}):
        port = predicate["portConnected"]
        if not _nonempty_string(port):
            return "portConnected must be a non-empty string"
        if not isinstance(predicate.get("is", True), bool):
            return "portConnected.is must be a boolean"
    elif keys == {"portArtifactType"}:
        artifact_predicate = predicate["portArtifactType"]
        error = _artifact_predicate_error(artifact_predicate)
        if error:
            return error
        port = _mapping(artifact_predicate)["port"]
    elif keys == {"not"}:
        return _predicate_error(
            predicate["not"], fields=fields, field=field, ports=ports
        )
    elif keys in ({"all"}, {"any"}):
        operator = next(iter(keys))
        children = _list(predicate[operator])
        if not children:
            return f"{operator} must be a non-empty list of predicates"
        for index, child in enumerate(children):
            error = _predicate_error(child, fields=fields, field=field, ports=ports)
            if error:
                return f"{operator}[{index}]: {error}"
        return None
    else:
        return "invalid visibility predicate structure"
    if isinstance(port, str) and ports is not None and port not in ports:
        return f"unknown input port {port!r}"
    return None


def _checked_predicate(predicate: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    error = _predicate_error(predicate)
    if error:
        raise ValueError(error)
    result = dict(predicate)
    if not _is_json_value(result):
        raise ValueError("visibility predicate must be JSON-serializable")
    return result


def validate_config_ui_schema(
    schema: Mapping[str, object], *, input_ports: Collection[str]
) -> list[str]:
    """Check UI hints and their field and port references in a Pydantic schema."""
    definitions = _mapping(schema.get("$defs"))
    visited_definitions: set[str] = set()
    errors: list[str] = []

    def resolve(
        current: Mapping[str, object], active_refs: frozenset[str]
    ) -> tuple[list[Mapping[str, object]], frozenset[str]]:
        # Draft 2020-12 applies both the referenced schema and its siblings.
        layers = [current]
        while isinstance(ref := current.get("$ref"), str) and ref.startswith(
            "#/$defs/"
        ):
            name = ref.removeprefix("#/$defs/").replace("~1", "/").replace("~0", "~")
            if name in active_refs or name not in definitions:
                break
            visited_definitions.add(name)
            active_refs = active_refs | {name}
            current = _mapping(definitions[name])
            layers.append(current)
        return layers, active_refs

    def enum_keys(
        layers: Sequence[Mapping[str, object]], active_refs: frozenset[str]
    ) -> set[str]:
        keys: set[str] = set()
        for layer in layers:
            keys.update(str(value) for value in _list(layer.get("enum")))
            discriminator = _mapping(layer.get("discriminator"))
            keys.update(_mapping(discriminator.get("mapping")))
            for variant in _list(layer.get("anyOf")):
                resolved, refs = resolve(_mapping(variant), active_refs)
                keys.update(enum_keys(resolved, refs))
        return keys

    def walk(
        current: Mapping[str, object],
        path: str,
        *,
        fields: Collection[str] = (),
        field: str | None = None,
        active_refs: frozenset[str] = frozenset(),
    ) -> None:
        layers, active_refs = resolve(current, active_refs)
        properties = {
            name for layer in layers for name in _mapping(layer.get("properties"))
        }
        for layer in layers:
            for key, value in layer.items():
                if key.startswith("x-grafy-"):
                    error = _extension_error(
                        key, value, fields=fields, field=field, input_ports=input_ports
                    )
                    if key == "x-grafy-enum-labels" and error is None:
                        unknown = _mapping(value).keys() - enum_keys(
                            layers, active_refs
                        )
                        if unknown:
                            error = f"labels reference unknown enum values {sorted(unknown)!r}"
                    if error:
                        errors.append(f"{path}: {key}: {error}")

            for name, prop in _mapping(layer.get("properties")).items():
                walk(
                    _mapping(prop),
                    f"{path}.{name}",
                    fields=properties,
                    field=name,
                    active_refs=active_refs,
                )
            for location, child in _schema_children(layer):
                walk(
                    child,
                    f"{path}.{location}",
                    fields=fields,
                    field=field,
                    active_refs=active_refs,
                )

    walk(schema, "$")
    for name, definition in definitions.items():
        if name not in visited_definitions:
            walk(_mapping(definition), f"#/$defs/{name}", active_refs=frozenset({name}))
    return errors


def _schema_children(
    schema: Mapping[str, object],
) -> Iterator[tuple[str, Mapping[str, object]]]:
    for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for index, child in enumerate(_list(schema.get(keyword))):
            yield f"{keyword}[{index}]", _mapping(child)
    for keyword in (
        "items",
        "additionalProperties",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "contains",
    ):
        child = _mapping(schema.get(keyword))
        if child:
            yield keyword, child
    for keyword in ("patternProperties", "dependentSchemas"):
        for name, child in _mapping(schema.get(keyword)).items():
            yield f"{keyword}.{name}", _mapping(child)


def _extension_error(
    key: str,
    value: object,
    *,
    fields: Collection[str],
    field: str | None,
    input_ports: Collection[str],
) -> str | None:
    if key in _FLAG_KEYS:
        return None if isinstance(value, bool) else "expected a boolean"
    match key:
        case "x-grafy-widget":
            return None if _valid_widget(value) else f"unknown widget {value!r}"
        case "x-grafy-group":
            return None if _nonempty_string(value) else "expected a non-empty string"
        case "x-grafy-enum-labels":
            if not _valid_enum_labels(value) or not isinstance(value, dict):
                return "expected a non-empty object of strings to strings"
            return None
        case "x-grafy-visible-when":
            return _predicate_error(
                value, fields=fields, field=field, ports=input_ports
            )
        case _:
            return "unknown extension"
