from pathlib import Path

import pytest
from pydantic import ValidationError

from grafy_api.system_plugin_inventory import (
    load_system_plugin_inventory,
)
from grafy_core.domain.system_plugin_inventory import (
    SYSTEM_PLUGIN_SLUGS,
    SystemPluginInventory,
    SystemPluginInventoryError,
)
from grafy_core.canonical_conversions import INTEGER_TO_TEXT
from grafy_core.domain.plugin_releases import (
    PluginArtifactConversionContract,
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCatalogManifest,
    PluginNodeContract,
)
from grafy_core.plugins import Plugin
from grafy_plugin_gis import GIS
from grafy_plugin_llm import LLM
from grafy_plugin_mistral import MISTRAL
from grafy_plugin_ocr import OCR
from grafy_plugin_sql import SQL
from grafy_plugin_typesafe import TYPESAFE


INVENTORY_PATH = Path(__file__).parents[3] / "plugins" / "system-plugins.toml"


def test_checked_in_system_inventory_is_complete_finite_and_excludes_modules() -> None:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)

    assert {plugin.slug for plugin in inventory.plugins} == SYSTEM_PLUGIN_SLUGS
    assert "builtin.module" not in SYSTEM_PLUGIN_SLUGS
    assert len(inventory.plugins) == 9
    assert next(
        plugin for plugin in inventory.plugins if plugin.slug == "external.sql"
    ).capabilities == (
        "node.secrets",
        "postgresql.egress",
        "sql.untrusted",
    )
    assert {
        entry.slug: (
            entry.operator_prefixes,
            entry.artifact_type_prefixes,
        )
        for entry in inventory.plugins
    } == {
        "external.image": (("image",), ("image.regions",)),
        "external.table": (("table",), ()),
        "external.gis": (("gis",), ("geo",)),
        "external.llm": (("llm", "prompt"), ("llm", "prompt.message")),
        "external.mistral": (("mistral",), ("mistral",)),
        "external.ocr": (("ocr",), ("ocr",)),
        "external.sql": (("sql",), ("sql",)),
        "external.python": (("python",), ()),
        "external.typesafe": (("typesafe",), ("typesafe",)),
    }


def _node_contract(operator_id: str, title: str) -> PluginNodeContract:
    return PluginNodeContract(
        operator_id=operator_id,
        operator_version=1,
        title=title,
        description=f"{title}.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(),
        outputs=(),
    )


def test_inventory_enforces_explicit_system_identity_authority() -> None:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)
    ocr_catalog = PluginCatalogManifest(
        slug="external.ocr",
        title="OCR",
        artifact_types=(
            PluginArtifactTypeContract(
                key=PluginArtifactTypeKey(id="ocr.page_result", schema_version=1),
                title="OCR page",
            ),
        ),
        nodes=(_node_contract("ocr.tesseract.pages", "OCR pages"),),
    )

    inventory.require_catalog_authority(ocr_catalog)

    entries = list(inventory.plugins)
    ocr_position = next(
        position
        for position, entry in enumerate(entries)
        if entry.slug == "external.ocr"
    )
    entries[ocr_position] = entries[ocr_position].model_copy(
        update={"operator_prefixes": ("ocr", "sql.query")}
    )
    delegating_inventory = inventory.model_copy(update={"plugins": tuple(entries)})

    delegated = PluginCatalogManifest(
        slug="external.sql",
        title="SQL",
        nodes=(_node_contract("sql.query", "Query"),),
    )
    with pytest.raises(SystemPluginInventoryError, match="delegated.*external.ocr"):
        delegating_inventory.require_catalog_authority(delegated)

    unauthorized = PluginCatalogManifest(
        slug="external.sql",
        title="SQL",
        nodes=(_node_contract("sqlalchemy.query", "SQL query"),),
    )
    with pytest.raises(SystemPluginInventoryError, match="allowlisted prefixes"):
        inventory.require_catalog_authority(unauthorized)


@pytest.mark.parametrize("plugin", (GIS, LLM, MISTRAL, OCR, SQL, TYPESAFE))
def test_inventory_accepts_each_preserved_external_catalog(plugin: Plugin) -> None:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)

    inventory.require_catalog_authority(PluginCatalogManifest.from_plugin(plugin))


def test_inventory_requires_exact_canonical_conversion_contracts() -> None:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)
    canonical = PluginArtifactConversionContract.from_conversion(INTEGER_TO_TEXT)
    catalog = PluginCatalogManifest.from_plugin(LLM).model_copy(
        update={"artifact_conversions": (canonical,)}
    )

    inventory.require_catalog_authority(catalog)

    changed = catalog.model_copy(
        update={
            "artifact_conversions": (
                canonical.model_copy(update={"title": "Different code contract"}),
            )
        }
    )
    with pytest.raises(SystemPluginInventoryError, match="exact.*canonical"):
        inventory.require_catalog_authority(changed)


def test_inventory_reserves_system_prefixes_from_workspace_catalogs() -> None:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)
    reserved = PluginCatalogManifest(
        slug="sql",
        title="Workspace SQL",
        nodes=(
            PluginNodeContract(
                operator_id="sql.query",
                operator_version=1,
                title="Query",
                description="Query.",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
            ),
        ),
    )
    unreserved = reserved.model_copy(
        update={
            "slug": "sqlalchemy",
            "nodes": (
                reserved.nodes[0].model_copy(
                    update={"operator_id": "sqlalchemy.query"}
                ),
            ),
        }
    )

    with pytest.raises(SystemPluginInventoryError, match="platform-reserved"):
        inventory.require_workspace_catalog_authority(reserved)
    inventory.require_workspace_catalog_authority(unreserved)


def test_inventory_and_exact_binding_collisions_are_rejected() -> None:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)
    entries = list(inventory.plugins)
    entries[1] = entries[1].model_copy(
        update={"loader_target": entries[0].loader_target}
    )

    with pytest.raises(ValidationError, match="loader targets must be unique"):
        SystemPluginInventory(plugins=tuple(entries))
