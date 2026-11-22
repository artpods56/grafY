import pytest
from grafy_api.services.families import build_application_registry
from grafy_core.config_ui import validate_config_ui_schema
from grafy_plugin_gis.nodes import VectorLayerConfig
from grafy_plugin_llm.openai_compatible import OpenAICompatibleConfig
from grafy_plugin_table.nodes import TableImportConfig
from grafy_workbench.ocr.label_studio import ExportLabelStudioConfig
from grafy_workbench.ocr.text_regions import DetectTextConfig, TiffTextRegions
from grafy_workbench.table.concat import ConcatTablesConfig
from grafy_workbench.table.place_matching import MatchPlacesConfig
from pydantic import BaseModel, JsonValue


def test_registered_nodes_have_valid_config_ui_schemas() -> None:
    failures: list[str] = []
    for registration in build_application_registry().nodes:
        node = registration.node_class
        errors = validate_config_ui_schema(
            node.config_contract.model.model_json_schema(),
            input_ports=node.input_contract.ports.keys(),
        )
        failures.extend(f"{registration.key}: {error}" for error in errors)
    assert failures == []


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (
            DetectTextConfig,
            {
                "scope": {"x-grafy-widget": "segmented"},
                "strategy": {"x-grafy-widget": "segmented"},
                **{
                    name: {
                        "x-grafy-visible-when": {
                            "field": "scope",
                            "eq": "Selected area",
                        }
                    }
                    for name in ("col", "row", "width", "height")
                },
            },
        ),
        (
            ConcatTablesConfig,
            {
                "add_source_index": {"x-grafy-widget": "switch"},
                "source_index_column": {
                    "x-grafy-visible-when": {"field": "add_source_index", "eq": True}
                },
            },
        ),
        (
            TableImportConfig,
            {
                "delimiter": {
                    "x-grafy-advanced": True,
                    "x-grafy-visible-when": {
                        "portArtifactType": {"port": "file", "notIn": ["file.xlsx@1"]}
                    },
                },
                "sheet_name": {
                    "x-grafy-visible-when": {
                        "portArtifactType": {"port": "file", "notIn": ["file.csv@1"]}
                    }
                },
                "skip_empty_rows": {
                    "x-grafy-advanced": True,
                    "x-grafy-widget": "switch",
                },
            },
        ),
        (
            OpenAICompatibleConfig,
            {
                "temperature": {"x-grafy-advanced": True, "x-grafy-widget": "slider"},
                "schema_name": {
                    "x-grafy-visible-when": {"portConnected": "json_schema"}
                },
                "strict": {
                    "x-grafy-widget": "switch",
                    "x-grafy-visible-when": {"portConnected": "json_schema"},
                },
            },
        ),
        (
            ExportLabelStudioConfig,
            {
                "label_studio_url": {"x-grafy-group": "Label Studio"},
                "project_title": {"x-grafy-group": "Label Studio"},
                "s3_bucket": {"x-grafy-group": "Storage (S3 / MinIO)"},
                "skip_auto_drop": {
                    "x-grafy-visible-when": {
                        "field": "mode",
                        "eq": "Region crops (fast triage)",
                    }
                },
                "tile_edge_px": {
                    "x-grafy-advanced": True,
                    "x-grafy-visible-when": {
                        "field": "mode",
                        "eq": "Tiled windows (polygons)",
                    },
                },
            },
        ),
        (
            MatchPlacesConfig,
            {
                "scope_boost": {
                    "x-grafy-widget": "slider",
                    "x-grafy-visible-when": {
                        "any": [
                            {"field": "reference_scope_column", "truthy": True},
                            {"field": "candidate_scope_column", "truthy": True},
                        ]
                    },
                },
                "sort_by": {
                    "x-grafy-advanced": True,
                    "x-grafy-enum-labels": {
                        "input": "Reference order",
                        "score_desc": "Best match first",
                    },
                },
            },
        ),
        (
            VectorLayerConfig,
            {
                "visible": {"x-grafy-widget": "switch"},
                "style": {
                    "x-grafy-widget": "segmented",
                    "x-grafy-enum-labels": {
                        "vector": "Uniform",
                        "categorized_points": "Categories",
                    },
                },
            },
        ),
    ],
)
def test_config_fields_emit_expected_ui_hints(
    model: type[BaseModel], expected: dict[str, dict[str, JsonValue]]
) -> None:
    properties = model.model_json_schema()["properties"]
    for name, hints in expected.items():
        assert {
            key: value
            for key, value in properties[name].items()
            if key.startswith("x-grafy-")
        } == hints


def test_tiff_artifact_window_has_no_config_visibility_rules() -> None:
    artifact_window = TiffTextRegions.model_json_schema()["$defs"]["TiffPixelWindow"]
    config = DetectTextConfig.model_json_schema()
    for name in ("col", "row", "width", "height"):
        config_field = dict(config["properties"][name])
        assert config_field.pop("x-grafy-visible-when") == {
            "field": "scope",
            "eq": "Selected area",
        }
        assert config_field == artifact_window["properties"][name]
