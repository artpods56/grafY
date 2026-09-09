from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path

import pytest

from grafy_api.plugins.compatibility.deployment import (
    SystemPluginDeploymentBuildError,
    SystemPluginDeploymentManifestBuilder,
)
from grafy_api.system_plugin_inventory import (
    CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH,
    load_system_plugin_inventory,
)
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventory,
    SystemPluginInventoryEntry,
)
from grafy_api.plugins.publication.source import (
    build_deterministic_archive,
    scan_source_tree,
)
from grafy_core.domain.plugin_releases import (
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
from grafy_persistence.database import Database, create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_plugin_llm import LLM
from tests.support.identity import create_schema


REPOSITORY_ROOT = CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH.parents[1]


def _mismatched_host_digest(_distribution_name: str) -> str:
    return "f" * 64


def _project_digests(
    entry: SystemPluginInventoryEntry,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[str, str]:
    project = repository_root / entry.project
    source_digest = sha256(
        build_deterministic_archive(scan_source_tree(project))
    ).hexdigest()
    lock_digest = sha256((project / "uv.lock").read_bytes()).hexdigest()
    return source_digest, lock_digest


def _release(
    inventory: SystemPluginInventory,
    revision: int,
    *,
    catalog: PluginCatalogManifest | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> InstalledPluginRelease:
    entry = inventory.entry_for("external.llm")
    source_digest, lock_digest = _project_digests(entry, repository_root)
    release_catalog = catalog or PluginCatalogManifest.from_plugin(LLM)
    capabilities = PluginCapabilityManifest(capabilities=entry.capabilities)
    runtime_artifact = PluginRuntimeArtifact(
        object_key=f"plugin-releases/system/external.llm/{revision}.oci.tar",
        archive_digest=sha256(f"archive:{revision}".encode()).hexdigest(),
        manifest_digest=sha256(f"manifest:{revision}".encode()).hexdigest(),
        config_digest=sha256(f"config:{revision}".encode()).hexdigest(),
    )
    release = PluginRelease(
        slug=entry.slug,
        revision=revision,
        catalog=release_catalog,
        contract_digest=plugin_contract_digest(release_catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/system/external.llm/{revision}.tar.gz",
        source_digest=source_digest,
        lock_digest=lock_digest,
        runtime_profile="python-uv",
        loader_target=entry.loader_target,
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor="test:deployment",
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
            installed_by_platform_actor="test:deployment",
        ),
    )


def _isolated_release(inventory: SystemPluginInventory) -> InstalledPluginRelease:
    entry = inventory.entry_for("external.gis")
    source_digest, lock_digest = _project_digests(entry)
    catalog = PluginCatalogManifest(
        slug=entry.slug,
        title="GIS",
        nodes=(
            PluginNodeContract(
                operator_id="gis.test",
                operator_version=1,
                title="GIS test",
                description="An isolated System Plugin fixture.",
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
    runtime_artifact = PluginRuntimeArtifact(
        object_key="plugin-releases/system/external.gis/1.oci.tar",
        archive_digest=sha256(b"gis-archive").hexdigest(),
        manifest_digest=sha256(b"gis-manifest").hexdigest(),
        config_digest=sha256(b"gis-config").hexdigest(),
    )
    release = PluginRelease(
        slug=entry.slug,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/system/external.gis/1.tar.gz",
        source_digest=source_digest,
        lock_digest=lock_digest,
        runtime_profile="python-uv",
        loader_target=entry.loader_target,
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor="test:deployment",
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
            installed_by_platform_actor="test:deployment",
        ),
    )


def _inventory_release(
    entry: SystemPluginInventoryEntry,
    revision: int,
) -> InstalledPluginRelease:
    source_digest, lock_digest = _project_digests(entry)
    catalog = PluginCatalogManifest(
        slug=entry.slug,
        title=entry.slug,
        nodes=(
            PluginNodeContract(
                operator_id=f"{entry.operator_prefixes[0]}.test",
                operator_version=1,
                title="Inventory test",
                description="An all-staged System Plugin fixture.",
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
    runtime_artifact = PluginRuntimeArtifact(
        object_key=f"plugin-releases/system/{entry.slug}/{revision}.oci.tar",
        archive_digest=sha256(
            f"all-archive:{entry.slug}:{revision}".encode()
        ).hexdigest(),
        manifest_digest=sha256(
            f"all-manifest:{entry.slug}:{revision}".encode()
        ).hexdigest(),
        config_digest=sha256(
            f"all-config:{entry.slug}:{revision}".encode()
        ).hexdigest(),
    )
    release = PluginRelease(
        slug=entry.slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/system/{entry.slug}/{revision}.tar.gz",
        source_digest=source_digest,
        lock_digest=lock_digest,
        runtime_profile="python-uv",
        loader_target=entry.loader_target,
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor="test:deployment",
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
            installed_by_platform_actor="test:deployment",
        ),
    )


@pytest.fixture
async def deployment_database(
    tmp_path: Path,
) -> AsyncIterator[tuple[Database, SystemPluginInventory]]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'deployment.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    inventory = load_system_plugin_inventory(CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH)
    yield database, inventory
    await database.dispose()


async def _persist_release(
    database: Database,
    release: InstalledPluginRelease,
) -> None:
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.plugin_releases.add(release.release)
        await unit_of_work.plugin_releases.add_installation(release.installation)
        await unit_of_work.commit()


async def _persist_selection(
    database: Database,
    release: InstalledPluginRelease,
) -> None:
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.plugin_releases.add_selection(
            PluginReleaseSelection.from_release(release)
        )
        await unit_of_work.commit()


@pytest.mark.asyncio
async def test_builder_writes_exact_idempotent_manifest_for_absent_selection(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    release = _release(inventory, 1)
    await _persist_release(database, release)
    output = tmp_path / "deployment.json"
    builder = SystemPluginDeploymentManifestBuilder(database.sessions)

    first = await builder.build(
        inventory,
        repository_root=REPOSITORY_ROOT,
        output=output,
        slug=release.release.slug,
        revision=release.release.revision,
    )
    first_bytes = output.read_bytes()
    second = await builder.build(
        inventory,
        repository_root=REPOSITORY_ROOT,
        output=output,
        slug=release.release.slug,
        revision=release.release.revision,
    )

    assert first == second
    assert output.read_bytes() == first_bytes
    assert first.plugins == ()


@pytest.mark.asyncio
async def test_builder_retains_generation_for_same_selection_and_increments_changed(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    first_release = _release(inventory, 1)
    second_release = _release(inventory, 2)
    await _persist_release(database, first_release)
    await _persist_release(database, second_release)
    await _persist_selection(database, first_release)
    builder = SystemPluginDeploymentManifestBuilder(database.sessions)

    same = await builder.build(
        inventory,
        repository_root=REPOSITORY_ROOT,
        output=tmp_path / "same.json",
        slug=first_release.release.slug,
        revision=first_release.release.revision,
    )
    changed = await builder.build(
        inventory,
        repository_root=REPOSITORY_ROOT,
        output=tmp_path / "changed.json",
        slug=second_release.release.slug,
        revision=second_release.release.revision,
    )

    assert same.plugins == ()
    assert changed.plugins == ()


@pytest.mark.asyncio
async def test_builder_does_not_import_isolated_plugin_as_host_target(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    installed_catalog = PluginCatalogManifest.from_plugin(LLM)
    mismatched_catalog = installed_catalog.model_copy(
        update={"title": "Tampered catalog title"}
    )
    release = _release(inventory, 1, catalog=mismatched_catalog)
    await _persist_release(database, release)

    manifest = await SystemPluginDeploymentManifestBuilder(database.sessions).build(
        inventory,
        repository_root=REPOSITORY_ROOT,
        output=tmp_path / "mismatch.json",
        slug=release.release.slug,
        revision=release.release.revision,
    )

    assert manifest.plugins == ()


@pytest.mark.asyncio
async def test_builder_rejects_same_catalog_with_different_project_implementation(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    repository_root = tmp_path / "repository"
    source_project = REPOSITORY_ROOT / "plugins" / "llm"
    copied_project = repository_root / "plugins" / "llm"
    for name, content in scan_source_tree(source_project):
        destination = copied_project / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    release = _release(inventory, 1, repository_root=repository_root)
    await _persist_release(database, release)
    implementation = (
        copied_project / "src" / "grafy_plugin_llm" / "openai_compatible.py"
    )
    implementation.write_bytes(
        implementation.read_bytes() + b"\n# different image implementation\n"
    )

    with pytest.raises(
        SystemPluginDeploymentBuildError,
        match="project source digest does not match",
    ):
        await SystemPluginDeploymentManifestBuilder(database.sessions).build(
            inventory,
            repository_root=repository_root,
            output=tmp_path / "implementation-mismatch.json",
            slug=release.release.slug,
            revision=release.release.revision,
        )


@pytest.mark.asyncio
async def test_builder_rejects_inventory_project_that_escapes_repository_root(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    release = _release(inventory, 1)
    await _persist_release(database, release)
    repository_root = tmp_path / "repository"
    plugins = repository_root / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "llm").symlink_to(
        REPOSITORY_ROOT / "plugins" / "llm",
        target_is_directory=True,
    )

    with pytest.raises(SystemPluginDeploymentBuildError, match="escapes repository"):
        await SystemPluginDeploymentManifestBuilder(database.sessions).build(
            inventory,
            repository_root=repository_root,
            output=tmp_path / "escaped.json",
            slug=release.release.slug,
            revision=release.release.revision,
        )


@pytest.mark.asyncio
async def test_builder_rejects_staged_lock_digest_mismatch(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    release = _release(inventory, 1)
    release.release.lock_digest = "f" * 64
    release.release.descriptor_digest = release.release.descriptor.digest
    await _persist_release(database, release)

    with pytest.raises(
        SystemPluginDeploymentBuildError,
        match="project lock digest does not match",
    ):
        await SystemPluginDeploymentManifestBuilder(database.sessions).build(
            inventory,
            repository_root=REPOSITORY_ROOT,
            output=tmp_path / "lock-mismatch.json",
            slug=release.release.slug,
            revision=release.release.revision,
        )


@pytest.mark.asyncio
async def test_builder_ignores_host_distribution_digest_for_isolated_releases(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, inventory = deployment_database
    release = _release(inventory, 1)
    await _persist_release(database, release)
    monkeypatch.setattr(
        "grafy_api.plugins.compatibility.deployment.installed_distribution_build_digest",
        _mismatched_host_digest,
    )

    manifest = await SystemPluginDeploymentManifestBuilder(database.sessions).build(
        inventory,
        repository_root=REPOSITORY_ROOT,
        output=tmp_path / "isolated-tamper.json",
        slug=release.release.slug,
        revision=release.release.revision,
    )

    assert manifest.plugins == ()
    assert (tmp_path / "isolated-tamper.json").is_file()


@pytest.mark.asyncio
async def test_builder_rejects_inventory_policy_mismatch(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    release = _release(inventory, 1)
    await _persist_release(database, release)
    changed_entries = tuple(
        entry.model_copy(update={"execution_policy": "host-eligible"})
        if entry.slug == release.release.slug
        else entry
        for entry in inventory.plugins
    )
    mismatched_inventory = SystemPluginInventory(plugins=changed_entries)

    with pytest.raises(
        SystemPluginDeploymentBuildError,
        match="execution policy",
    ):
        await SystemPluginDeploymentManifestBuilder(database.sessions).build(
            mismatched_inventory,
            repository_root=REPOSITORY_ROOT,
            output=tmp_path / "policy.json",
            slug=release.release.slug,
            revision=release.release.revision,
        )


@pytest.mark.asyncio
async def test_builder_never_host_binds_isolated_only_release(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    release = _isolated_release(inventory)
    await _persist_release(database, release)

    manifest = await SystemPluginDeploymentManifestBuilder(database.sessions).build(
        inventory,
        repository_root=REPOSITORY_ROOT,
        output=tmp_path / "isolated.json",
        slug=release.release.slug,
        revision=release.release.revision,
    )

    assert manifest.plugins == ()


@pytest.mark.asyncio
async def test_builder_all_mode_does_not_host_bind_isolated_inventory(
    deployment_database: tuple[Database, SystemPluginInventory],
    tmp_path: Path,
) -> None:
    database, inventory = deployment_database
    for entry in inventory.plugins:
        await _persist_release(database, _inventory_release(entry, 1))
    llm_entry = inventory.entry_for("external.llm")
    await _persist_release(database, _inventory_release(llm_entry, 2))

    manifest = await SystemPluginDeploymentManifestBuilder(database.sessions).build(
        inventory,
        repository_root=REPOSITORY_ROOT,
        output=tmp_path / "all.json",
    )

    assert manifest.plugins == ()
    assert {entry.slug for entry in inventory.plugins} == {
        "external.gis",
        "external.llm",
        "external.ocr",
        "external.sql",
    }
