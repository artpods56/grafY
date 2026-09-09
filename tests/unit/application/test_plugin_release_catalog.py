import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from typing_extensions import override

from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.identity import (
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PlatformPluginActor,
    PluginNodeContract,
    PluginRelease,
    PluginReleaseError,
    PluginReleaseHeadConflictError,
    PluginReleaseNamespace,
    PluginReleaseScope,
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
from grafy_core.ports.storage import SaveFileCommand, StoredFile
from grafy_storage import LocalFileObjectStore


FIRST_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000901")
SECOND_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000902")
PUBLISHER_USER_ID = UUID("00000000-4000-8000-0000-000000000903")
PLATFORM_ACTOR = PlatformPluginActor("ci:cross-scope")


def _release(
    namespace: PluginReleaseNamespace,
    slug: str,
) -> InstalledPluginRelease:
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
    is_system = namespace.scope is PluginReleaseScope.SYSTEM
    runtime_artifact = (
        PluginRuntimeArtifact(
            object_key=f"plugin-releases/system/{slug}/runtime.oci.tar",
            archive_digest="1" * 64,
            manifest_digest="2" * 64,
            config_digest="3" * 64,
        )
        if is_system
        else None
    )
    release = PluginRelease(
        slug=slug,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/{namespace.storage_path}/{slug}.tar.gz",
        source_digest="4" * 64,
        lock_digest="5" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=(
            None if runtime_artifact is None else runtime_artifact.manifest_digest
        ),
        runtime_artifact=runtime_artifact,
        published_by_user_id=None if is_system else PUBLISHER_USER_ID,
        published_by_platform_actor="test:catalog" if is_system else None,
    )
    installation = PluginInstallation.from_release(
        release,
        namespace=namespace,
        execution_policy=(
            PluginExecutionPolicy.HOST_ELIGIBLE
            if is_system
            else PluginExecutionPolicy.ISOLATED_ONLY
        ),
        installed_by_user_id=None if is_system else PUBLISHER_USER_ID,
        installed_by_platform_actor="test:catalog" if is_system else None,
    )
    return InstalledPluginRelease(release=release, installation=installation)


@pytest.mark.asyncio
async def test_catalog_shares_system_selection_and_isolates_workspace_releases(
    tmp_path: Path,
) -> None:
    database = create_database(
        f"sqlite+aiosqlite:///{tmp_path / 'release-catalog.sqlite3'}"
    )
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    first_namespace = PluginReleaseNamespace(
        scope=PluginReleaseScope.WORKSPACE,
        workspace_id=FIRST_WORKSPACE_ID,
    )
    second_namespace = PluginReleaseNamespace(
        scope=PluginReleaseScope.WORKSPACE,
        workspace_id=SECOND_WORKSPACE_ID,
    )
    system_namespace = PluginReleaseNamespace(
        scope=PluginReleaseScope.SYSTEM,
        workspace_id=None,
    )
    first_release = _release(first_namespace, "first-private")
    second_release = _release(second_namespace, "second-private")
    system_release = _release(system_namespace, "global-notes")

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_user(
            User(
                id=PUBLISHER_USER_ID,
                email="publisher@example.test",
                display_name="Publisher",
            )
        )
        await unit_of_work.identity.add_workspace(
            Workspace(
                id=FIRST_WORKSPACE_ID,
                slug="first",
                name="First workspace",
                kind=WorkspaceKind.SHARED,
            )
        )
        await unit_of_work.identity.add_workspace(
            Workspace(
                id=SECOND_WORKSPACE_ID,
                slug="second",
                name="Second workspace",
                kind=WorkspaceKind.SHARED,
            )
        )
        for release in (first_release, second_release, system_release):
            await unit_of_work.plugin_releases.add(release.release)
            await unit_of_work.plugin_releases.add_installation(release.installation)
            await unit_of_work.plugin_releases.add_selection(
                PluginReleaseSelection.from_release(release)
            )
        await unit_of_work.commit()

    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    try:
        assert await service.list_current(FIRST_WORKSPACE_ID) == [first_release]
        assert await service.list_current(SECOND_WORKSPACE_ID) == [second_release]

        first_system_selection = await service.get_selection(
            FIRST_WORKSPACE_ID,
            system_release.release.slug,
            scope=PluginReleaseScope.SYSTEM,
        )
        second_system_selection = await service.get_selection(
            SECOND_WORKSPACE_ID,
            system_release.release.slug,
            scope=PluginReleaseScope.SYSTEM,
        )
        assert first_system_selection == second_system_selection
        assert first_system_selection is not None
        assert first_system_selection.selected_release_id == system_release.release.id

        assert (
            await service.get_by_revision(
                FIRST_WORKSPACE_ID,
                second_release.release.slug,
                second_release.release.revision,
            )
            is None
        )
        assert (
            await service.get_by_revision(
                SECOND_WORKSPACE_ID,
                first_release.release.slug,
                first_release.release.revision,
            )
            is None
        )
    finally:
        await database.dispose()


def _identity_catalog(
    slug: str,
    *,
    node_id: str,
    artifact_id: str | None = None,
) -> PluginCatalogManifest:
    """A minimal catalog pinning one exact node (and optionally artifact) identity."""

    artifact_types = ()
    if artifact_id is not None:
        artifact_types = (
            PluginArtifactTypeContract(
                key=PluginArtifactTypeKey(id=artifact_id, schema_version=1),
                title="Identity fixture artifact",
            ),
        )
    return PluginCatalogManifest(
        slug=slug,
        title=f"{slug} fixture",
        nodes=(
            PluginNodeContract(
                operator_id=node_id,
                operator_version=1,
                title="Identity fixture",
                description="Cross-scope identity fixture",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
            ),
        ),
        artifact_types=artifact_types,
    )


async def _cross_scope_database(tmp_path: Path) -> Database:
    database = create_database(
        f"sqlite+aiosqlite:///{tmp_path / 'cross-scope.sqlite3'}"
    )
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_user(
            User(
                id=PUBLISHER_USER_ID,
                email="publisher@example.test",
                display_name="Publisher",
            )
        )
        for workspace_id, slug in (
            (FIRST_WORKSPACE_ID, "first"),
            (SECOND_WORKSPACE_ID, "second"),
        ):
            await unit_of_work.identity.add_workspace(
                Workspace(
                    id=workspace_id,
                    slug=slug,
                    name=f"{slug.title()} workspace",
                    kind=WorkspaceKind.SHARED,
                )
            )
            await unit_of_work.identity.add_membership(
                WorkspaceMembership(
                    workspace_id=workspace_id,
                    user_id=PUBLISHER_USER_ID,
                    role=WorkspaceRole.OWNER,
                )
            )
        await unit_of_work.commit()
    return database


async def _release_count(database: Database, slug: str) -> int:
    async with database.engine.connect() as connection:
        count = await connection.scalar(
            select(func.count())
            .select_from(schema.plugin_releases)
            .where(schema.plugin_releases.c.slug == slug)
        )
    assert count is not None
    return count


def _source_object_count(objects_dir: Path) -> int:
    return sum(1 for path in objects_dir.rglob("*") if path.is_file())


@pytest.mark.asyncio
async def test_workspace_publication_cannot_reuse_retained_system_identities(
    tmp_path: Path,
) -> None:
    database = await _cross_scope_database(tmp_path)
    objects = tmp_path / "objects"
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(objects),
        bucket="plugins",
    )
    try:
        await service.publish_system(
            catalog=_identity_catalog(
                "system-b",
                node_id="workspace-a.clash",
                artifact_id="workspace-a.data",
            ),
            capabilities=PluginCapabilityManifest(),
            source_archive=b"system-b-source",
            lock_digest="1" * 64,
            runtime_profile="python-uv",
            runtime_artifact=PluginRuntimeArtifact(
                object_key="plugin-releases/system/system-b/r1.oci.tar",
                archive_digest="2" * 64,
                manifest_digest="3" * 64,
                config_digest="4" * 64,
            ),
            execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
            platform_actor=PLATFORM_ACTOR,
            loader_target="grafy_plugin:PLUGIN",
        )

        with pytest.raises(
            PluginReleaseError,
            match=r"Workspace Plugin 'workspace-a' node workspace-a.clash@1 "
            r"conflicts with a retained System Plugin identity",
        ):
            await service.publish(
                workspace_id=FIRST_WORKSPACE_ID,
                catalog=_identity_catalog(
                    "workspace-a",
                    node_id="workspace-a.clash",
                ),
                capabilities=PluginCapabilityManifest(),
                source_archive=b"workspace-a-source",
                lock_digest="5" * 64,
                runtime_profile="python-uv",
                runtime_artifact=None,
                published_by_user_id=PUBLISHER_USER_ID,
                loader_target="grafy_plugin:PLUGIN",
            )
        with pytest.raises(
            PluginReleaseError,
            match=r"Workspace Plugin 'workspace-a' artifact type "
            r"workspace-a.data@1 conflicts with a retained System Plugin identity",
        ):
            await service.publish(
                workspace_id=FIRST_WORKSPACE_ID,
                catalog=_identity_catalog(
                    "workspace-a",
                    node_id="workspace-a.free",
                    artifact_id="workspace-a.data",
                ),
                capabilities=PluginCapabilityManifest(),
                source_archive=b"workspace-a-artifact-source",
                lock_digest="6" * 64,
                runtime_profile="python-uv",
                runtime_artifact=None,
                published_by_user_id=PUBLISHER_USER_ID,
                loader_target="grafy_plugin:PLUGIN",
            )

        assert await _release_count(database, "workspace-a") == 0
        assert await _release_count(database, "system-b") == 1
        assert _source_object_count(objects) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_system_publication_cannot_reuse_retained_workspace_identities(
    tmp_path: Path,
) -> None:
    database = await _cross_scope_database(tmp_path)
    objects = tmp_path / "objects"
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(objects),
        bucket="plugins",
    )
    try:
        await service.publish(
            workspace_id=SECOND_WORKSPACE_ID,
            catalog=_identity_catalog(
                "workspace-a",
                node_id="workspace-a.clash",
                artifact_id="workspace-a.data",
            ),
            capabilities=PluginCapabilityManifest(),
            source_archive=b"workspace-a-source",
            lock_digest="1" * 64,
            runtime_profile="python-uv",
            runtime_artifact=None,
            published_by_user_id=PUBLISHER_USER_ID,
            loader_target="grafy_plugin:PLUGIN",
        )

        async def _stage(
            clash: str,
            artifact_clash: str | None,
        ) -> InstalledPluginRelease:
            return await service.publish_system(
                catalog=_identity_catalog(
                    "system-b",
                    node_id=clash,
                    artifact_id=artifact_clash,
                ),
                capabilities=PluginCapabilityManifest(),
                source_archive=b"system-b-source",
                lock_digest="2" * 64,
                runtime_profile="python-uv",
                runtime_artifact=PluginRuntimeArtifact(
                    object_key="plugin-releases/system/system-b/r1.oci.tar",
                    archive_digest="3" * 64,
                    manifest_digest="4" * 64,
                    config_digest="5" * 64,
                ),
                execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
                platform_actor=PLATFORM_ACTOR,
                loader_target="grafy_plugin:PLUGIN",
            )

        with pytest.raises(
            PluginReleaseError,
            match=r"System Plugin 'system-b' node workspace-a.clash@1 "
            r"conflicts with a retained Workspace Plugin identity",
        ):
            await _stage("workspace-a.clash", None)
        with pytest.raises(
            PluginReleaseError,
            match=r"System Plugin 'system-b' artifact type workspace-a.data@1 "
            r"conflicts with a retained Workspace Plugin identity",
        ):
            await _stage("system-b.free", "workspace-a.data")

        assert await _release_count(database, "system-b") == 0
        assert await _release_count(database, "workspace-a") == 1
        assert _source_object_count(objects) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_historical_workspace_revision_identity_still_blocks_system_publication(
    tmp_path: Path,
) -> None:
    database = await _cross_scope_database(tmp_path)
    objects = tmp_path / "objects"
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(objects),
        bucket="plugins",
    )
    try:
        first = await service.publish(
            workspace_id=FIRST_WORKSPACE_ID,
            catalog=_identity_catalog(
                "workspace-a",
                node_id="workspace-a.historical",
            ),
            capabilities=PluginCapabilityManifest(),
            source_archive=b"workspace-a-first",
            lock_digest="1" * 64,
            runtime_profile="python-uv",
            runtime_artifact=None,
            published_by_user_id=PUBLISHER_USER_ID,
            loader_target="grafy_plugin:PLUGIN",
        )
        await service.publish(
            workspace_id=FIRST_WORKSPACE_ID,
            catalog=_identity_catalog(
                "workspace-a",
                node_id="workspace-a.current",
            ),
            capabilities=PluginCapabilityManifest(),
            source_archive=b"workspace-a-second",
            lock_digest="2" * 64,
            runtime_profile="python-uv",
            runtime_artifact=None,
            published_by_user_id=PUBLISHER_USER_ID,
            loader_target="grafy_plugin:PLUGIN",
        )
        assert first.release.revision == 1

        with pytest.raises(
            PluginReleaseError,
            match=r"System Plugin 'system-b' node workspace-a.historical@1 "
            r"conflicts with a retained Workspace Plugin identity",
        ):
            await service.publish_system(
                catalog=_identity_catalog(
                    "system-b",
                    node_id="workspace-a.historical",
                ),
                capabilities=PluginCapabilityManifest(),
                source_archive=b"system-b-source",
                lock_digest="3" * 64,
                runtime_profile="python-uv",
                runtime_artifact=PluginRuntimeArtifact(
                    object_key="plugin-releases/system/system-b/r1.oci.tar",
                    archive_digest="4" * 64,
                    manifest_digest="5" * 64,
                    config_digest="6" * 64,
                ),
                execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
                platform_actor=PLATFORM_ACTOR,
                loader_target="grafy_plugin:PLUGIN",
            )

        assert await _release_count(database, "system-b") == 0
        assert await _release_count(database, "workspace-a") == 2
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_non_colliding_cross_scope_publications_succeed(
    tmp_path: Path,
) -> None:
    database = await _cross_scope_database(tmp_path)
    objects = tmp_path / "objects"
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(objects),
        bucket="plugins",
    )
    try:
        system_release = await service.publish_system(
            catalog=_identity_catalog(
                "system-b",
                node_id="system-b.clash",
                artifact_id="system-b.data",
            ),
            capabilities=PluginCapabilityManifest(),
            source_archive=b"system-b-source",
            lock_digest="1" * 64,
            runtime_profile="python-uv",
            runtime_artifact=PluginRuntimeArtifact(
                object_key="plugin-releases/system/system-b/r1.oci.tar",
                archive_digest="2" * 64,
                manifest_digest="3" * 64,
                config_digest="4" * 64,
            ),
            execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
            platform_actor=PLATFORM_ACTOR,
            loader_target="grafy_plugin:PLUGIN",
        )
        workspace_release = await service.publish(
            workspace_id=FIRST_WORKSPACE_ID,
            catalog=_identity_catalog(
                "workspace-a",
                node_id="workspace-a.clash",
                artifact_id="workspace-a.data",
            ),
            capabilities=PluginCapabilityManifest(),
            source_archive=b"workspace-a-source",
            lock_digest="5" * 64,
            runtime_profile="python-uv",
            runtime_artifact=None,
            published_by_user_id=PUBLISHER_USER_ID,
            loader_target="grafy_plugin:PLUGIN",
        )

        assert system_release.release.revision == 1
        assert workspace_release.release.revision == 1
        assert await _release_count(database, "system-b") == 1
        assert await _release_count(database, "workspace-a") == 1
        assert _source_object_count(objects) == 2
    finally:
        await database.dispose()


class PausingPublicationStore(LocalFileObjectStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.started = asyncio.Event()
        self.resume = asyncio.Event()
        self.saved_paths: list[str] = []

    @override
    async def save(self, command: SaveFileCommand) -> StoredFile:
        self.started.set()
        await self.resume.wait()
        stored = await super().save(command)
        self.saved_paths.append(command.path)
        return stored


@pytest.mark.parametrize("base_revision", [0, 1])
async def test_reviewed_publications_serialize_before_reading_release_head(
    tmp_path: Path,
    base_revision: int,
) -> None:
    database = await _cross_scope_database(tmp_path)
    namespace = PluginReleaseNamespace(
        scope=PluginReleaseScope.WORKSPACE,
        workspace_id=FIRST_WORKSPACE_ID,
    )
    template = _release(namespace, "publication-race")
    storage = PausingPublicationStore(tmp_path / "objects")
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        storage,
        bucket="race",
    )
    if base_revision:
        storage.resume.set()
        await service.publish(
            workspace_id=FIRST_WORKSPACE_ID,
            catalog=template.release.catalog,
            capabilities=template.release.capabilities,
            source_archive=b"base",
            lock_digest=template.release.lock_digest,
            runtime_profile=template.release.runtime_profile,
            runtime_artifact=None,
            published_by_user_id=PUBLISHER_USER_ID,
            loader_target=template.release.loader_target,
            expected_base_revision=0,
        )
        storage.started.clear()
        storage.resume.clear()
        storage.saved_paths.clear()
    first = asyncio.create_task(
        service.publish(
            workspace_id=FIRST_WORKSPACE_ID,
            catalog=template.release.catalog,
            capabilities=template.release.capabilities,
            source_archive=b"first contender",
            lock_digest=template.release.lock_digest,
            runtime_profile=template.release.runtime_profile,
            runtime_artifact=None,
            published_by_user_id=PUBLISHER_USER_ID,
            loader_target=template.release.loader_target,
            expected_base_revision=base_revision,
        )
    )
    second_lock_attempted = asyncio.Event()

    def observe_lock_attempt(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        if statement == "BEGIN IMMEDIATE":
            second_lock_attempted.set()

    second = None
    try:
        await asyncio.wait_for(storage.started.wait(), timeout=10)
        event.listen(
            database.engine.sync_engine, "before_cursor_execute", observe_lock_attempt
        )
        second = asyncio.create_task(
            service.publish(
                workspace_id=FIRST_WORKSPACE_ID,
                catalog=template.release.catalog,
                capabilities=template.release.capabilities,
                source_archive=b"second contender",
                lock_digest=template.release.lock_digest,
                runtime_profile=template.release.runtime_profile,
                runtime_artifact=None,
                published_by_user_id=PUBLISHER_USER_ID,
                loader_target=template.release.loader_target,
                expected_base_revision=base_revision,
            )
        )
        await asyncio.wait_for(second_lock_attempted.wait(), timeout=10)
        storage.resume.set()
        accepted = await first
        with pytest.raises(PluginReleaseHeadConflictError) as raised:
            await second
        assert raised.value.workspace_id == FIRST_WORKSPACE_ID
        assert raised.value.slug == template.release.slug
        assert raised.value.expected_revision == base_revision
        assert raised.value.actual_revision == base_revision + 1
        assert accepted.release.revision == base_revision + 1
        assert await service.list_current(FIRST_WORKSPACE_ID) == [accepted]
        assert (
            await _release_count(database, template.release.slug) == base_revision + 1
        )
        assert len(storage.saved_paths) == 1
    finally:
        storage.resume.set()
        if second is not None:
            await asyncio.gather(second, return_exceptions=True)
        await asyncio.gather(first, return_exceptions=True)
        if event.contains(
            database.engine.sync_engine, "before_cursor_execute", observe_lock_attempt
        ):
            event.remove(
                database.engine.sync_engine,
                "before_cursor_execute",
                observe_lock_attempt,
            )
        await database.dispose()
