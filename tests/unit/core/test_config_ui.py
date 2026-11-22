from collections.abc import Mapping
from enum import Enum
from typing import Annotated, Literal, cast

import pytest
from grafy_core.config_ui import (
    WidgetKind,
    field_ui,
    validate_config_ui_schema,
    when_all,
    when_any,
    when_field_eq,
    when_field_in,
    when_field_neq,
    when_field_truthy,
    when_not,
    when_port_artifact_type,
    when_port_connected,
)
from pydantic import BaseModel, Field, JsonValue


def test_field_predicates() -> None:
    assert when_field_eq("scope", None) == {"field": "scope", "eq": None}
    assert when_field_neq("scope", "whole") == {"field": "scope", "neq": "whole"}
    assert when_field_in("scope", ("whole", "area")) == {
        "field": "scope",
        "in": ["whole", "area"],
    }
    assert when_field_truthy("scope") == {"field": "scope", "truthy": True}
    assert when_field_truthy("scope", False) == {"field": "scope", "truthy": False}


def test_port_predicates() -> None:
    assert when_port_connected("file") == {"portConnected": "file"}
    assert when_port_connected("file", False) == {"portConnected": "file", "is": False}
    assert when_port_artifact_type(
        "file",
        in_types=("file.csv@1",),
        not_in=("file.xlsx@2",),
        when_unconnected="hide",
    ) == {
        "portArtifactType": {
            "port": "file",
            "in": ["file.csv@1"],
            "notIn": ["file.xlsx@2"],
            "whenUnconnected": "hide",
        }
    }
    assert when_port_artifact_type("file", in_types=(), not_in=("file.csv@1",)) == {
        "portArtifactType": {"port": "file", "notIn": ["file.csv@1"]}
    }


def test_composite_predicates() -> None:
    assert when_all(when_port_connected("file"), when_field_eq("scope", "area")) == {
        "all": [{"portConnected": "file"}, {"field": "scope", "eq": "area"}]
    }
    assert when_any(when_not(when_field_truthy("scope"))) == {
        "any": [{"not": {"field": "scope", "truthy": True}}]
    }


def test_predicate_builders_reject_bad_arguments() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        when_field_eq("", True)
    with pytest.raises(ValueError, match="JSON value"):
        when_field_neq("scope", float("inf"))
    with pytest.raises(ValueError, match="sequence of JSON values"):
        when_field_in("scope", "area")
    with pytest.raises(ValueError, match="requires in or notIn"):
        when_port_artifact_type("file", in_types=(), not_in=())
    with pytest.raises(ValueError, match="id@version"):
        when_port_artifact_type("file", in_types=("file.csv@0",))
    with pytest.raises(ValueError, match="id@version"):
        when_port_artifact_type("file", not_in=("file.csv",))
    with pytest.raises(ValueError, match="whenUnconnected"):
        when_port_artifact_type(
            "file",
            in_types=("file.csv@1",),
            when_unconnected=cast("Literal['show', 'hide']", "yes"),
        )
    with pytest.raises(ValueError, match="non-empty list"):
        when_all()
    with pytest.raises(ValueError, match="non-empty list"):
        when_any()
    with pytest.raises(ValueError, match="predicate structure"):
        when_not({"unknown": "scope"})


def test_field_ui_emits_only_selected_extensions() -> None:
    assert field_ui() == {}
    assert field_ui(
        advanced=True,
        hidden=True,
        auto_id=True,
        widget="segmented",
        enum_labels={"whole": "Whole page"},
        group="Scan",
        visible_when=when_port_connected("file"),
    ) == {
        "x-grafy-advanced": True,
        "x-grafy-hidden": True,
        "x-grafy-auto-id": True,
        "x-grafy-widget": "segmented",
        "x-grafy-enum-labels": {"whole": "Whole page"},
        "x-grafy-group": "Scan",
        "x-grafy-visible-when": {"portConnected": "file"},
    }


def test_field_ui_rejects_bad_arguments() -> None:
    with pytest.raises(ValueError, match="boolean"):
        field_ui(advanced=cast(bool, 1))
    with pytest.raises(ValueError, match="unknown x-grafy-widget"):
        field_ui(widget=cast(WidgetKind, "textbox"))
    with pytest.raises(ValueError, match="non-empty string"):
        field_ui(group=" ")
    with pytest.raises(ValueError, match="mapping of strings to strings"):
        field_ui(enum_labels={})
    with pytest.raises(ValueError, match="mapping of strings to strings"):
        field_ui(enum_labels=cast(Mapping[str, str], {"small": 1}))
    with pytest.raises(ValueError, match="exactly one operator"):
        field_ui(visible_when={"field": "scope", "eq": "area", "truthy": True})


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("x-grafy-other", True, "unknown extension"),
        ("x-grafy-advanced", 1, "expected a boolean"),
        ("x-grafy-hidden", "false", "expected a boolean"),
        ("x-grafy-auto-id", None, "expected a boolean"),
        ("x-grafy-widget", "textbox", "unknown widget 'textbox'"),
        ("x-grafy-group", "", "expected a non-empty string"),
        (
            "x-grafy-enum-labels",
            {"area": True},
            "expected a non-empty object of strings to strings",
        ),
        (
            "x-grafy-enum-labels",
            {"unknown": "Unknown"},
            "labels reference unknown enum values ['unknown']",
        ),
        (
            "x-grafy-visible-when",
            {"field": "missing", "eq": None},
            "unknown sibling field 'missing'",
        ),
        (
            "x-grafy-visible-when",
            {"field": "scope", "truthy": True},
            "field 'scope' references itself",
        ),
        (
            "x-grafy-visible-when",
            {"portConnected": "wrong"},
            "unknown input port 'wrong'",
        ),
        (
            "x-grafy-visible-when",
            {"portArtifactType": {"port": "wrong", "in": ["file.csv@1"]}},
            "unknown input port 'wrong'",
        ),
        (
            "x-grafy-visible-when",
            {"portConnected": "file", "is": 0},
            "portConnected.is must be a boolean",
        ),
        (
            "x-grafy-visible-when",
            {"any": []},
            "any must be a non-empty list of predicates",
        ),
        (
            "x-grafy-visible-when",
            {"not": {"field": "mode", "truthy": "yes"}},
            "truthy must be a boolean",
        ),
    ],
)
def test_schema_reports_bad_ui_extension(
    key: str, value: JsonValue, error: str
) -> None:
    schema = {
        "properties": {"mode": {}, "scope": {"enum": ["area", "whole"], key: value}}
    }
    assert validate_config_ui_schema(schema, input_ports=("file",)) == [
        f"$.scope: {key}: {error}"
    ]


class ScanMode(Enum):
    AREA = 1
    WHOLE = 2


class ScanWindow(BaseModel):
    mode: ScanMode | None = Field(
        default=None, json_schema_extra=field_ui(enum_labels={"1": "Selected area"})
    )
    width: int = Field(
        json_schema_extra=field_ui(visible_when=when_field_eq("mode", 1))
    )


class InvalidWindow(BaseModel):
    width: int = Field(
        json_schema_extra=field_ui(
            visible_when=when_all(
                when_field_truthy("mode"), when_port_connected("file")
            )
        )
    )


def test_schema_resolves_nullable_enum_refs_and_nested_array_fields() -> None:
    class Config(BaseModel):
        windows: list[ScanWindow]

    assert validate_config_ui_schema(Config.model_json_schema(), input_ports=()) == []


def test_nested_fields_only_see_siblings_inside_their_object() -> None:
    class Config(BaseModel):
        mode: str
        windows: list[InvalidWindow]

    assert validate_config_ui_schema(
        Config.model_json_schema(), input_ports=("file",)
    ) == [
        "$.windows.items.width: x-grafy-visible-when: all[0]: unknown sibling field 'mode'"
    ]


class UniformStyle(BaseModel):
    kind: Literal["uniform"]


class CategorizedStyle(BaseModel):
    kind: Literal["categorized"]
    category: str = Field(
        json_schema_extra=field_ui(visible_when=when_field_eq("kind", "categorized"))
    )


def test_schema_checks_discriminator_mapping_and_variants() -> None:
    class Layer(BaseModel):
        style: Annotated[
            UniformStyle | CategorizedStyle, Field(discriminator="kind")
        ] = Field(
            json_schema_extra=field_ui(
                enum_labels={"uniform": "Uniform", "categorized": "Categories"}
            )
        )

    schema = Layer.model_json_schema()
    assert validate_config_ui_schema(schema, input_ports=()) == []
    schema["properties"]["style"]["x-grafy-enum-labels"]["other"] = "Other"
    schema["$defs"]["CategorizedStyle"]["properties"]["category"][
        "x-grafy-visible-when"
    ] = {"field": "style", "truthy": True}
    assert validate_config_ui_schema(schema, input_ports=()) == [
        "$.style: x-grafy-enum-labels: labels reference unknown enum values ['other']",
        "$.style.oneOf[1].category: x-grafy-visible-when: unknown sibling field 'style'",
    ]


def test_schema_checks_ref_siblings_in_each_enclosing_object() -> None:
    schema = {
        "$defs": {"scope/mode": {"enum": ["area", "whole"]}},
        "properties": {
            "enabled": {"type": "boolean"},
            "scope": {
                "$ref": "#/$defs/scope~1mode",
                "x-grafy-enum-labels": {"area": "Selected area"},
                "x-grafy-visible-when": {"field": "enabled", "eq": True},
            },
            "nested": {
                "properties": {
                    "scope": {
                        "$ref": "#/$defs/scope~1mode",
                        "x-grafy-visible-when": {"field": "enabled", "eq": True},
                    }
                }
            },
        },
    }
    assert validate_config_ui_schema(schema, input_ports=()) == [
        "$.nested.scope: x-grafy-visible-when: unknown sibling field 'enabled'"
    ]


def test_schema_terminates_on_recursive_refs_and_checks_siblings() -> None:
    schema = {
        "$ref": "#/$defs/Tree",
        "$defs": {
            "Tree": {
                "properties": {
                    "children": {
                        "items": {"$ref": "#/$defs/Tree", "x-grafy-widget": "invalid"}
                    }
                }
            }
        },
    }
    assert validate_config_ui_schema(schema, input_ports=()) == [
        "$.children.items: x-grafy-widget: unknown widget 'invalid'"
    ]
