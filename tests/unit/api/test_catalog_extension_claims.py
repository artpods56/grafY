"""The extension table refuses a colliding installation, not a catalog read."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from grafy_api.catalog import CatalogSnapshot
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.plugin_releases import (
    PlatformPluginActor,
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginReleaseScope,
    PluginRuntimeArtifact,
)
from grafy_core.file_contracts import ExtensionClaimCollisionError
from grafy_core.plugins import PluginRegistry
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID, create_schema


PLATFORM_ACTOR = PlatformPluginActor("test:extension-claims")


def _snapshot(registry: PluginRegistry) -> CatalogSnapshot:
    return CatalogSnapshot.from_registry(registry, [], [], workspace_id=WORKSPACE_ID)


def _contract(snapshot: CatalogSnapshot, artifact_type_id: str):
    return next(
        contract
        for contract in snapshot.artifact_contracts
        if contract.key.id == artifact_type_id
    )


def _catalog(
    slug: str,
    *,
    artifact_id: str,
    extensions: tuple[str, ...],
) -> PluginCatalogManifest:
    return PluginCatalogManifest(
        slug=slug,
        title=f"{slug} Plugin",
        nodes=(
            PluginNodeContract(
                operator_id=f"{slug}.echo",
                operator_version=1,
                title="Echo",
                description="Echo a value",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
            ),
        ),
        artifact_types=(
            PluginArtifactTypeContract(
                key=PluginArtifactTypeKey(id=artifact_id, schema_version=1),
                title="Claimed format",
                extensions=extensions,
            ),
        ),
    )


async def _release_count(database: Database, slug: str) -> int:
    async with database.engine.connect() as connection:
        count = await connection.scalar(
            select(func.count())
            .select_from(schema.plugin_releases)
            .where(schema.plugin_releases.c.slug == slug)
        )
    assert count is not None
    return count


async def _publish_workspace(
    service: PluginReleaseService,
    *,
    catalog: PluginCatalogManifest,
    source: bytes,
    lock_digest: str,
):
    return await service.publish(
        workspace_id=WORKSPACE_ID,
        catalog=catalog,
        capabilities=PluginCapabilityManifest(),
        source_archive=source,
        lock_digest=lock_digest,
        runtime_profile="python-uv",
        runtime_artifact=None,
        published_by_user_id=TEST_USER_ID,
        loader_target="grafy_plugin:PLUGIN",
    )


async def _publish_system(
    service: PluginReleaseService,
    *,
    catalog: PluginCatalogManifest,
    source: bytes,
    lock_digest: str,
):
    return await service.publish_system(
        catalog=catalog,
        capabilities=PluginCapabilityManifest(),
        source_archive=source,
        lock_digest=lock_digest,
        runtime_profile="python-uv",
        runtime_artifact=PluginRuntimeArtifact(
            object_key=f"plugin-releases/system/{catalog.slug}/runtime.oci.tar",
            archive_digest="1" * 64,
            manifest_digest="2" * 64,
            config_digest="3" * 64,
        ),
        execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
        platform_actor=PLATFORM_ACTOR,
        loader_target="grafy_plugin:PLUGIN",
    )


@pytest.fixture
async def deployment(
    tmp_path: Path,
) -> AsyncIterator[tuple[PluginReleaseService, Database]]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'extension-claims.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    try:
        yield (
            PluginReleaseService(
                lambda: SqlAlchemyUnitOfWork(database.sessions),
                LocalFileObjectStore(tmp_path / "objects"),
                bucket="extension-claims",
            ),
            database,
        )
    finally:
        await database.dispose()


async def test_colliding_extension_claim_refuses_the_installation(
    deployment: tuple[PluginReleaseService, Database],
) -> None:
    service, database = deployment

    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.txt@1 and file\.plain@1 both claim extension 'txt'",
    ):
        await _publish_workspace(
            service,
            catalog=_catalog("file", artifact_id="file.plain", extensions=("txt",)),
            source=b"colliding-source",
            lock_digest="1" * 64,
        )

    assert await service.list_current(WORKSPACE_ID) == []
    assert await service.get_selection(WORKSPACE_ID, "file") is None
    assert await _release_count(database, "file") == 1

    installed = await _publish_workspace(
        service,
        catalog=_catalog("file", artifact_id="file.plain", extensions=()),
        source=b"clean-source",
        lock_digest="2" * 64,
    )

    assert installed.release.revision == 2
    assert [
        entry.release.revision for entry in await service.list_current(WORKSPACE_ID)
    ] == [2]


async def test_a_collision_with_an_installed_plugin_leaves_the_selection_unchanged(
    deployment: tuple[PluginReleaseService, Database],
) -> None:
    service, database = deployment

    await _publish_system(
        service,
        catalog=_catalog("system.las", artifact_id="file.las", extensions=("las",)),
        source=b"system-las-source",
        lock_digest="1" * 64,
    )
    await service.promote_system(
        slug="system.las",
        revision=1,
        platform_actor=PLATFORM_ACTOR,
        expected_generation=0,
    )
    first = await _publish_workspace(
        service,
        catalog=_catalog("file", artifact_id="file.laz", extensions=()),
        source=b"workspace-laz-source",
        lock_digest="2" * 64,
    )
    assert first.release.revision == 1

    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.las@1 and file\.laz@1 both claim extension 'las'",
    ):
        await _publish_workspace(
            service,
            catalog=_catalog("file", artifact_id="file.laz", extensions=("las",)),
            source=b"colliding-laz-source",
            lock_digest="3" * 64,
        )

    selection = await service.get_selection(WORKSPACE_ID, "file")
    assert selection is not None
    assert selection.selected_revision == 1
    assert [
        entry.release.revision for entry in await service.list_current(WORKSPACE_ID)
    ] == [1]
    assert await _release_count(database, "file") == 2


async def test_a_system_promotion_colliding_with_a_builtin_is_refused(
    deployment: tuple[PluginReleaseService, Database],
) -> None:
    service, _database = deployment

    published = await _publish_system(
        service,
        catalog=_catalog(
            "system.plain",
            artifact_id="file.plain",
            extensions=("txt",),
        ),
        source=b"system-plain-source",
        lock_digest="1" * 64,
    )
    assert published.release.revision == 1

    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.txt@1 and file\.plain@1 both claim extension 'txt'",
    ):
        await service.promote_system(
            slug="system.plain",
            revision=1,
            platform_actor=PLATFORM_ACTOR,
            expected_generation=0,
        )

    assert (
        await service.get_selection(
            WORKSPACE_ID,
            "system.plain",
            scope=PluginReleaseScope.SYSTEM,
        )
        is None
    )
    assert await service.list_current_system() == []


async def test_a_system_promotion_colliding_with_a_workspace_plugin_is_refused(
    deployment: tuple[PluginReleaseService, Database],
) -> None:
    service, _database = deployment

    installed = await _publish_workspace(
        service,
        catalog=_catalog("file", artifact_id="file.laz", extensions=("las",)),
        source=b"workspace-laz-source",
        lock_digest="1" * 64,
    )
    assert installed.release.revision == 1

    await _publish_system(
        service,
        catalog=_catalog("system.las", artifact_id="file.las", extensions=("las",)),
        source=b"system-las-source",
        lock_digest="2" * 64,
    )

    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.laz@1 and file\.las@1 both claim extension 'las'",
    ):
        await service.promote_system(
            slug="system.las",
            revision=1,
            platform_actor=PLATFORM_ACTOR,
            expected_generation=0,
        )

    assert await service.list_current_system() == []


def test_deployment_table_resolves_json_and_confirms_documents_only() -> None:
    snapshot = _snapshot(PluginRegistry())

    assert snapshot.extension_claims["json"] == ArtifactTypeKey("file.json", 1)
    assert snapshot.extension_claims["geojson"] == ArtifactTypeKey("file.geojson", 1)

    rule = _contract(snapshot, "file.json").confirmation_rule.to_rule()
    assert rule.confirms(b"[1, 2, 3]")
    assert not rule.confirms(b"17")


def test_deployment_table_resolves_a_rule_less_format_by_extension() -> None:
    snapshot = _snapshot(PluginRegistry())

    assert snapshot.extension_claims["csv"] == ArtifactTypeKey("file.csv", 1)
    assert _contract(snapshot, "file.csv").confirmation_rule.rule == "none"
