from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select

from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.identity import User, Workspace, WorkspaceKind
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginRelease,
    PluginReleaseNamespace,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore

LEGACY_WORKSPACE_ID = UUID("00000000-4000-8000-0000-000000000904")
LEGACY_PUBLISHER_ID = UUID("00000000-4000-8000-0000-000000000905")
PLATFORM_ACTOR = "test:catalog"


def _digest(kind: str, slug: str, revision: int) -> str:
    return sha256(f"{kind}:{slug}@{revision}".encode()).hexdigest()


def _release(slug: str, *, revision: int = 1) -> InstalledPluginRelease:
    catalog = PluginCatalogManifest(
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
    )
    capabilities = PluginCapabilityManifest()
    runtime_artifact = PluginRuntimeArtifact(
        object_key=f"plugin-releases/system/{slug}/runtime.oci.tar",
        archive_digest=_digest("archive", slug, revision),
        manifest_digest=_digest("manifest", slug, revision),
        config_digest=_digest("config", slug, revision),
    )
    release = PluginRelease(
        slug=slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/{slug}.tar.gz",
        source_digest=_digest("source", slug, revision),
        lock_digest=_digest("lock", slug, revision),
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor=PLATFORM_ACTOR,
    )
    installation = PluginInstallation.from_release(
        release,
        namespace=PluginReleaseNamespace(),
        execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
        installed_by_platform_actor=PLATFORM_ACTOR,
    )
    return InstalledPluginRelease(release=release, installation=installation)


async def _database(tmp_path: Path, name: str) -> Database:
    database = create_database(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    return database


async def _install(
    database: Database,
    release: InstalledPluginRelease,
    *,
    selected: bool,
) -> None:
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.plugin_releases.add(release.release)
        await unit_of_work.plugin_releases.add_installation(release.installation)
        if selected:
            await unit_of_work.plugin_releases.add_selection(
                PluginReleaseSelection.from_release(release)
            )
        await unit_of_work.commit()


def _service(database: Database, tmp_path: Path) -> PluginReleaseService:
    return PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )


@pytest.mark.asyncio
async def test_catalog_offers_only_selected_system_releases(tmp_path: Path) -> None:
    database = await _database(tmp_path, "catalog.sqlite3")
    try:
        selected = _release("global-notes", revision=2)
        retained = _release("global-notes", revision=1)
        unselected = _release("unpublished-notes")
        for release, is_selected in (
            (selected, True),
            (retained, False),
            (unselected, False),
        ):
            await _install(database, release, selected=is_selected)
        service = _service(database, tmp_path)

        catalog = await service.list_catalog()
        assert [entry.release for entry in catalog] == [selected]
        assert await service.get_selection("global-notes") == catalog[0].selection
        assert await service.get_selection("unpublished-notes") is None
        assert await service.get_by_revision("global-notes", 1) == retained
        assert await service.get_by_revision("unpublished-notes", 1) == unselected
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_stored_workspace_scope_rows_are_not_offered(tmp_path: Path) -> None:
    """Rows written before Plugins became System-only stay unread, not fatal."""

    database = await _database(tmp_path, "legacy-scopes.sqlite3")
    legacy = _release("legacy-notes")
    system_release = _release("global-notes")
    try:
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await unit_of_work.identity.add_user(
                User(
                    id=LEGACY_PUBLISHER_ID,
                    email="legacy@example.test",
                    display_name="Legacy publisher",
                )
            )
            await unit_of_work.identity.add_workspace(
                Workspace(
                    id=LEGACY_WORKSPACE_ID,
                    slug="legacy",
                    name="Legacy workspace",
                    kind=WorkspaceKind.SHARED,
                )
            )
            await unit_of_work.plugin_releases.add(legacy.release)
            await unit_of_work.plugin_releases.add(system_release.release)
            await unit_of_work.plugin_releases.add_installation(
                system_release.installation
            )
            await unit_of_work.plugin_releases.add_selection(
                PluginReleaseSelection.from_release(system_release)
            )
            await unit_of_work.commit()

        installed_at = datetime.now(UTC)
        async with database.engine.begin() as connection:
            await connection.execute(
                insert(schema.plugin_installations).values(
                    id=uuid4(),
                    release_id=legacy.release.id,
                    scope="workspace",
                    workspace_id=LEGACY_WORKSPACE_ID,
                    slug=legacy.release.slug,
                    release_revision=legacy.release.revision,
                    execution_policy="isolated-only",
                    installed_by_user_id=LEGACY_PUBLISHER_ID,
                    installed_at=installed_at,
                )
            )
            await connection.execute(
                insert(schema.plugin_release_selections).values(
                    id=uuid4(),
                    scope="workspace",
                    workspace_id=LEGACY_WORKSPACE_ID,
                    slug=legacy.release.slug,
                    selected_release_id=legacy.release.id,
                    selected_revision=legacy.release.revision,
                    lifecycle="published",
                    generation=1,
                    updated_at=installed_at,
                )
            )
        service = _service(database, tmp_path)

        assert [entry.release for entry in await service.list_catalog()] == [
            system_release
        ]
        assert await service.get_by_revision(legacy.release.slug, 1) is None
        assert await service.get_selection(legacy.release.slug) is None
        async with database.engine.connect() as connection:
            stored_selections = await connection.scalar(
                select(func.count())
                .select_from(schema.plugin_release_selections)
                .where(
                    schema.plugin_release_selections.c.slug == legacy.release.slug
                )
            )
        assert stored_selections == 1
    finally:
        await database.dispose()
