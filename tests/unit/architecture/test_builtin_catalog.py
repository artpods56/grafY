from grafy_api.services.families import APPLICATION_FAMILIES, build_application_registry
from grafy_core.artifact_contracts import (
    HTML_PAGE,
    INTEGER_VALUE,
    RASTER_IMAGE,
    TEXT_VALUE,
)
from grafy_core.contracts.ocr import CropTextReader, DocumentOcr, TextBoxDetector
from grafy_core.plugins import PluginRegistry
from grafy_core.table_contracts import TABLE_DATA
from grafy_plugin_image import IMAGES
from grafy_plugin_table import TABLES
from grafy_workbench import BUILTIN_FAMILIES, build_builtin_registry

EXPECTED_BUILTIN_OPERATORS = {
    ("sequence.collect", 1),
    ("sequence.count", 1),
    ("sequence.slice", 1),
    ("sequence.item_at", 1),
    ("value.integer", 1),
    ("text.input", 1),
    ("schema.builder", 1),
    ("table.concat", 1),
    ("table.extract_from_markdown", 1),
    ("ocr.read_document", 1),
}


def test_builtin_catalog_keeps_artifact_support_without_retired_operators() -> None:
    registry = build_builtin_registry()

    assert {node.key for node in registry.nodes} == EXPECTED_BUILTIN_OPERATORS
    assert {artifact.key for artifact in registry.artifact_types} >= {
        TEXT_VALUE.key,
        HTML_PAGE.key,
        INTEGER_VALUE.key,
        RASTER_IMAGE.key,
        TABLE_DATA.key,
    }
    # ADR 0022 restores the Sequence family as application code. It depends on
    # the integer value contract but owns no artifact type of its own.
    assert "sequence" in {plugin.slug for plugin in registry.plugins}
    assert registry.artifact_type_owner(INTEGER_VALUE.key) != "sequence"
    installed_operators = {node.key[0] for node in registry.nodes}
    assert "sequence.collect" in installed_operators
    assert not installed_operators & {
        "text.split",
        "table.text.normalize",
        "file.interpret",
        "image.decode",
    }


def test_file_plugins_install_alongside_builtin_artifact_contracts() -> None:
    registry = PluginRegistry()
    for family in (*BUILTIN_FAMILIES, IMAGES, TABLES):
        registry.install(family)
    registry.freeze()

    assert (
        registry.node_registration("image.draw_regions", 1).plugin_slug
        == "external.image"
    )
    assert registry.node_registration("table.import", 1).plugin_slug == "external.table"
    assert registry.artifact_type_owner(RASTER_IMAGE.key) == "image"
    assert registry.artifact_type_owner(TABLE_DATA.key) == "table"


def test_application_catalog_has_explicit_descriptions() -> None:
    registry = build_application_registry()

    assert len(registry.nodes) == 42
    for node in registry.nodes:
        assert node.description.strip(), node.key
        assert "ABC" not in node.description, node.key


def test_builtin_ocr_family_owns_the_shared_service_contracts() -> None:
    owners = {
        contract.protocol: plugin.slug
        for plugin in APPLICATION_FAMILIES
        for contract in plugin.service_contracts
        if contract.protocol in {DocumentOcr, TextBoxDetector, CropTextReader}
    }
    assert owners == {
        DocumentOcr: "ocr",
        TextBoxDetector: "ocr",
        CropTextReader: "ocr",
    }
