from grafy_core.artifact_contracts import INTEGER_VALUE, RASTER_IMAGE, TEXT_VALUE
from grafy_core.plugins import PluginRegistry
from grafy_core.table_contracts import TABLE_DATA
from grafy_plugin_image import IMAGES
from grafy_plugin_table import TABLES
from grafy_workbench import BUILTIN_FAMILIES, build_builtin_registry


EXPECTED_BUILTIN_OPERATORS = {
    ("module.input", 1),
    ("module.output", 1),
    ("sequence.collect", 1),
    ("sequence.count", 1),
    ("sequence.slice", 1),
    ("sequence.item_at", 1),
    ("value.integer", 1),
    ("text.input", 1),
    ("schema.builder", 1),
    ("file.interpret", 1),
}


def test_builtin_catalog_keeps_artifact_support_without_retired_operators() -> None:
    registry = build_builtin_registry()

    assert {node.key for node in registry.nodes} == EXPECTED_BUILTIN_OPERATORS
    assert {artifact.key for artifact in registry.artifact_types} >= {
        TEXT_VALUE.key,
        INTEGER_VALUE.key,
        RASTER_IMAGE.key,
        TABLE_DATA.key,
    }
    # ADR 0018 restores the Sequence family as application code. It depends on
    # the integer value contract but owns no artifact type of its own.
    assert "sequence" in {plugin.slug for plugin in registry.plugins}
    assert registry.artifact_type_owner(INTEGER_VALUE.key) != "sequence"
    installed_operators = {node.key[0] for node in registry.nodes}
    assert "sequence.collect" in installed_operators
    assert not installed_operators & {"text.split", "table.text.normalize"}


def test_file_plugins_install_alongside_builtin_artifact_contracts() -> None:
    registry = PluginRegistry()
    for family in (*BUILTIN_FAMILIES, IMAGES, TABLES):
        registry.install(family)
    registry.freeze()

    assert registry.node_registration("image.decode", 1).plugin_slug == "external.image"
    assert registry.node_registration("table.import", 1).plugin_slug == "external.table"
    assert registry.artifact_type_owner(RASTER_IMAGE.key) == "image"
    assert registry.artifact_type_owner(TABLE_DATA.key) == "table"
