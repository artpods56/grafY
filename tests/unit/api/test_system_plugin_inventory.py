from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import delete

from grafy_core.domain.plugin_host_bindings import (
    SystemHostPluginBinding,
)
from grafy_api.system_cutover_operations import (
    canonical_model_json_bytes,
    generate_system_baseline_file,
    load_system_baseline_manifest,
)
from grafy_api.system_plugin_inventory import (
    load_system_plugin_inventory,
)
from grafy_core.domain.system_plugin_inventory import (
    SYSTEM_PLUGIN_SLUGS,
    SystemPluginInventory,
    SystemPluginInventoryEntry,
    SystemPluginInventoryError,
)
from grafy_persistence.system_baseline import (
    SystemBaselineManifestGenerator,
)
from grafy_api.plugins.compatibility.loader import (
    SystemPluginDeploymentEntry,
    SystemPluginDeploymentManifest,
)
from grafy_core.canonical_conversions import INTEGER_TO_TEXT
from grafy_core.domain.plugin_releases import (
    PluginArtifactConversionContract,
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.plugins import Plugin
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_plugin_gis import GIS
from grafy_plugin_llm import LLM
from grafy_plugin_ocr import OCR
from grafy_plugin_sql import SQL


INVENTORY_PATH = Path(__file__).parents[3] / "plugins" / "system-plugins.toml"


def _release(
    entry: SystemPluginInventoryEntry,
    position: int,
) -> InstalledPluginRelease:
    operator_prefix = entry.operator_prefixes[0]
    catalog = PluginCatalogManifest(
        slug=entry.slug,
        title=entry.slug,
        nodes=(
            PluginNodeContract(
                operator_id=f"{operator_prefix}.node",
                operator_version=1,
                title="Node",
                description="Inventory generator fixture.",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
                required_capabilities=entry.capabilities,
            ),
        ),
    )
    capabilities = PluginCapabilityManifest(capabilities=entry.capabilities)
    archive_digest = sha256(f"archive:{entry.slug}".encode()).hexdigest()
    manifest_digest = sha256(f"manifest:{entry.slug}".encode()).hexdigest()
    runtime = PluginRuntimeArtifact(
        object_key=f"plugin-releases/system/{entry.slug}/runtime.oci.tar",
        archive_digest=archive_digest,
        manifest_digest=manifest_digest,
        config_digest=sha256(f"config:{entry.slug}".encode()).hexdigest(),
    )
    release = PluginRelease(
        slug=entry.slug,
        revision=position + 1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/system/{entry.slug}/source.tar.gz",
        source_digest=sha256(f"source:{entry.slug}".encode()).hexdigest(),
        lock_digest=sha256(f"lock:{entry.slug}".encode()).hexdigest(),
        runtime_profile="python-uv",
        loader_target=entry.loader_target,
        runtime_image_digest=manifest_digest,
        runtime_artifact=runtime,
        published_by_platform_actor="test:inventory",
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            execution_policy=entry.execution_policy,
            installed_by_user_id=None,
            installed_by_platform_actor="test:inventory",
        ),
    )


@pytest.fixture
async def inventory_database(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[Database, SystemPluginInventory, dict[str, InstalledPluginRelease]]
]:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)
    database = create_database(
        f"sqlite+aiosqlite:///{tmp_path / 'system-inventory.sqlite3'}"
    )
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    releases = {
        entry.slug: _release(entry, position)
        for position, entry in enumerate(inventory.plugins)
    }
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        for entry in inventory.plugins:
            release = releases[entry.slug]
            await unit_of_work.plugin_releases.add(release.release)
            await unit_of_work.plugin_releases.add_installation(release.installation)
            await unit_of_work.plugin_releases.add_selection(
                PluginReleaseSelection.from_release(
                    release,
                    actor_reference="test:inventory",
                )
            )
        await unit_of_work.commit()
    try:
        yield database, inventory, releases
    finally:
        await database.dispose()


def test_checked_in_system_inventory_is_complete_finite_and_excludes_modules() -> None:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)

    assert {plugin.slug for plugin in inventory.plugins} == SYSTEM_PLUGIN_SLUGS
    assert "builtin.module" not in SYSTEM_PLUGIN_SLUGS
    assert len(inventory.plugins) == 4
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
        "external.gis": (("gis",), ("geo",)),
        "external.llm": (("llm", "prompt"), ("llm", "prompt.message")),
        "external.ocr": (("ocr",), ("ocr",)),
        "external.sql": (("sql",), ("sql",)),
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


@pytest.mark.parametrize("plugin", (GIS, LLM, OCR, SQL))
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


@pytest.mark.asyncio
async def test_generator_resolves_exact_releases_and_host_bindings_idempotently(
    inventory_database: tuple[
        Database,
        SystemPluginInventory,
        dict[str, InstalledPluginRelease],
    ],
    tmp_path: Path,
) -> None:
    database, inventory, releases = inventory_database
    bindings = tuple(
        SystemHostPluginBinding.from_release(
            releases[entry.slug],
            selection_generation=1,
            loader_target=entry.loader_target,
            host_build_digest=sha256(f"host:{entry.slug}".encode()).hexdigest(),
        )
        for entry in inventory.plugins
        if entry.execution_policy == "host-eligible"
    )
    generator = SystemBaselineManifestGenerator(database.sessions)

    first = await generator.generate(inventory, host_bindings=bindings)
    second = await generator.generate(inventory, host_bindings=bindings)

    assert first == second
    assert [release.slug for release in first.releases] == sorted(SYSTEM_PLUGIN_SLUGS)
    entries_by_slug = {entry.slug: entry for entry in inventory.plugins}
    for generated in first.releases:
        selected = releases[generated.slug]
        assert generated.release_id == selected.release.id
        assert generated.descriptor_digest == selected.release.descriptor.digest
        assert generated.operators[0].operator_id == (
            f"{entries_by_slug[generated.slug].operator_prefixes[0]}.node"
        )

    deployment = SystemPluginDeploymentManifest(
        plugins=tuple(
            SystemPluginDeploymentEntry(
                binding=binding,
                distribution_name=entries_by_slug[binding.slug].distribution_name,
                loader_target=binding.loader_target,
                host_build_digest=binding.host_build_digest,
            )
            for binding in bindings
        )
    )
    deployment_path = tmp_path / "deployment.json"
    deployment_path.write_bytes(deployment.canonical_json_bytes())
    output = tmp_path / "baseline.json"
    written = await generate_system_baseline_file(
        generator,
        inventory_path=INVENTORY_PATH,
        deployment_manifest_path=deployment_path,
        output=output,
    )
    assert written.release_count == 4
    assert output.read_bytes() == canonical_model_json_bytes(first)
    assert load_system_baseline_manifest(output) == first

    unexpected_binding = SystemHostPluginBinding.from_release(
        releases["external.sql"],
        selection_generation=1,
        loader_target=entries_by_slug["external.sql"].loader_target,
        host_build_digest=sha256(b"host:external.sql").hexdigest(),
    )
    with pytest.raises(SystemPluginInventoryError, match="unique slugs"):
        await generator.generate(
            inventory,
            host_bindings=(unexpected_binding, unexpected_binding),
        )
    with pytest.raises(SystemPluginInventoryError, match="unexpected"):
        await generator.generate(
            inventory,
            host_bindings=(unexpected_binding,),
        )


@pytest.mark.asyncio
async def test_generator_refuses_missing_selection_and_inventory_release_mismatch(
    inventory_database: tuple[
        Database,
        SystemPluginInventory,
        dict[str, InstalledPluginRelease],
    ],
) -> None:
    database, inventory, _releases = inventory_database
    generator = SystemBaselineManifestGenerator(database.sessions)
    async with database.engine.begin() as connection:
        await connection.execute(
            delete(schema.plugin_release_selections).where(
                schema.plugin_release_selections.c.slug == "external.sql"
            )
        )
    with pytest.raises(SystemPluginInventoryError, match="missing=.*external.sql"):
        await generator.generate(inventory)

    database_two = create_database("sqlite+aiosqlite:///:memory:")
    try:
        async with database_two.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        entries = list(inventory.plugins)
        first = entries[0]
        mismatched_entry = first.model_copy(
            update={"execution_policy": "host-eligible"}
        )
        entries[0] = mismatched_entry
        mismatched_inventory = inventory.model_copy(update={"plugins": tuple(entries)})
        async with SqlAlchemyUnitOfWork(database_two.sessions) as unit_of_work:
            for position, entry in enumerate(inventory.plugins):
                release = _release(entry, position)
                await unit_of_work.plugin_releases.add(release.release)
                await unit_of_work.plugin_releases.add_installation(
                    release.installation
                )
                await unit_of_work.plugin_releases.add_selection(
                    PluginReleaseSelection.from_release(release)
                )
            await unit_of_work.commit()
        with pytest.raises(SystemPluginInventoryError, match="execution policy"):
            await SystemBaselineManifestGenerator(database_two.sessions).generate(
                mismatched_inventory
            )
    finally:
        await database_two.dispose()


def test_inventory_and_exact_binding_collisions_are_rejected() -> None:
    inventory = load_system_plugin_inventory(INVENTORY_PATH)
    entries = list(inventory.plugins)
    entries[1] = entries[1].model_copy(
        update={"loader_target": entries[0].loader_target}
    )

    with pytest.raises(ValidationError, match="loader targets must be unique"):
        SystemPluginInventory(plugins=tuple(entries))
