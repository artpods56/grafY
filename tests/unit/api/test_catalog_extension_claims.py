"""The extension table refuses a colliding selection, not a catalog read."""

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
    PluginRuntimeArtifact,
)
from grafy_core.file_contracts import ExtensionClaimCollisionError
from grafy_core.plugins import PluginRegistry
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from tests.support.identity import create_schema


PLATFORM_ACTOR = PlatformPluginActor("test:extension-claims")


def _snapshot(registry: PluginRegistry) -> CatalogSnapshot:
    return CatalogSnapshot.from_registry(registry, [], [])


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


async def test_a_colliding_extension_claim_refuses_promotion(
    deployment: tuple[PluginReleaseService, Database],
) -> None:
    service, database = deployment

    published = await _publish_system(
        service,
        catalog=_catalog("file", artifact_id="file.plain", extensions=("txt",)),
        source=b"colliding-source",
        lock_digest="1" * 64,
    )

    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.txt@1 and file\.plain@1 both claim extension 'txt'",
    ):
        await service.promote_system(
            slug=published.release.slug,
            revision=published.release.revision,
            platform_actor=PLATFORM_ACTOR,
            expected_generation=0,
        )

    assert await service.list_catalog() == []
    assert await service.get_selection("file") is None
    assert await _release_count(database, "file") == 1

    clean = await _publish_system(
        service,
        catalog=_catalog("file", artifact_id="file.plain", extensions=()),
        source=b"clean-source",
        lock_digest="2" * 64,
    )
    await service.promote_system(
        slug=clean.release.slug,
        revision=clean.release.revision,
        platform_actor=PLATFORM_ACTOR,
        expected_generation=0,
    )

    assert clean.release.revision == 2
    assert [entry.release.release.revision for entry in await service.list_catalog()] == [2]


async def test_a_collision_with_an_installed_format_leaves_the_selection_unchanged(
    deployment: tuple[PluginReleaseService, Database],
) -> None:
    service, database = deployment

    first = await _publish_system(
        service,
        catalog=_catalog("file", artifact_id="file.laz", extensions=()),
        source=b"clean-laz-source",
        lock_digest="1" * 64,
    )
    await service.promote_system(
        slug=first.release.slug,
        revision=first.release.revision,
        platform_actor=PLATFORM_ACTOR,
        expected_generation=0,
    )
    assert first.release.revision == 1

    colliding = await _publish_system(
        service,
        catalog=_catalog("file", artifact_id="file.laz", extensions=("csv",)),
        source=b"colliding-laz-source",
        lock_digest="2" * 64,
    )

    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.csv@1 and file\.laz@1 both claim extension 'csv'",
    ):
        await service.promote_system(
            slug=colliding.release.slug,
            revision=colliding.release.revision,
            platform_actor=PLATFORM_ACTOR,
            expected_generation=1,
        )

    selection = await service.get_selection("file")
    assert selection is not None
    assert selection.selected_revision == 1
    assert [entry.release.release.revision for entry in await service.list_catalog()] == [1]
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

    assert await service.get_selection("system.plain") is None
    assert await service.list_catalog() == []


async def test_a_system_promotion_colliding_with_a_selected_family_is_refused(
    deployment: tuple[PluginReleaseService, Database],
) -> None:
    service, _database = deployment

    installed = await _publish_system(
        service,
        catalog=_catalog("file", artifact_id="file.laz", extensions=("laz",)),
        source=b"laz-source",
        lock_digest="1" * 64,
    )
    await service.promote_system(
        slug=installed.release.slug,
        revision=installed.release.revision,
        platform_actor=PLATFORM_ACTOR,
        expected_generation=0,
    )

    await _publish_system(
        service,
        catalog=_catalog("system.las", artifact_id="file.las", extensions=("laz",)),
        source=b"system-las-source",
        lock_digest="2" * 64,
    )

    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.laz@1 and file\.las@1 both claim extension 'laz'",
    ):
        await service.promote_system(
            slug="system.las",
            revision=1,
            platform_actor=PLATFORM_ACTOR,
            expected_generation=0,
        )

    assert [item.release.release.slug for item in await service.list_catalog()] == ["file"]


def test_deployment_table_resolves_json_and_declares_document_confirmation() -> None:
    snapshot = _snapshot(PluginRegistry())

    assert snapshot.extension_claims["json"] == ArtifactTypeKey("file.json", 1)
    assert snapshot.extension_claims["geojson"] == ArtifactTypeKey("file.geojson", 1)

    assert _contract(snapshot, "file.json").confirmation_rule.rule == "json_document"


def test_deployment_table_resolves_a_rule_less_format_by_extension() -> None:
    snapshot = _snapshot(PluginRegistry())

    assert snapshot.extension_claims["csv"] == ArtifactTypeKey("file.csv", 1)
    assert _contract(snapshot, "file.csv").confirmation_rule.rule == "none"
