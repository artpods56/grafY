from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.plugin_catalog import PluginCatalogRelease
from grafy_core.domain.plugin_releases import PluginReleaseError
from grafy_core.domain.plugin_selection import PluginFamilyLifecycle
from grafy_storage import LocalFileObjectStore

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
    PluginReleaseScope,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationReason,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.ports.plugin_releases import PluginReleaseRepositoryPort
from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000851")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000852")
USER_ID = UUID("00000000-0000-0000-0000-000000000853")
WORKSPACE_NAMESPACE = PluginReleaseNamespace(
    scope=PluginReleaseScope.WORKSPACE,
    workspace_id=WORKSPACE_ID,
)
OTHER_WORKSPACE_NAMESPACE = PluginReleaseNamespace(
    scope=PluginReleaseScope.WORKSPACE,
    workspace_id=OTHER_WORKSPACE_ID,
)
SYSTEM_NAMESPACE = PluginReleaseNamespace(
    scope=PluginReleaseScope.SYSTEM,
    workspace_id=None,
)


def _release(revision: int, marker: str, *, slug: str = "notes") -> PluginRelease:
    catalog = PluginCatalogManifest(
        slug=slug,
        title=slug.title(),
        nodes=(
            PluginNodeContract(
                operator_id=f"{slug}.echo",
                operator_version=1,
                title="Echo",
                description="Echo text",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest()
    return PluginRelease(
        slug=slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/{slug}/{marker}.tar.gz",
        source_digest=marker * 64,
        lock_digest="9" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
    )


def _installed(
    release: PluginRelease,
    namespace: PluginReleaseNamespace,
) -> InstalledPluginRelease:
    system = namespace.scope is PluginReleaseScope.SYSTEM
    installation = PluginInstallation.from_release(
        release,
        namespace=namespace,
        execution_policy=(
            PluginExecutionPolicy.HOST_ELIGIBLE
            if system
            else PluginExecutionPolicy.ISOLATED_ONLY
        ),
        installed_by_user_id=None if system else USER_ID,
        installed_by_platform_actor="test:system" if system else None,
    )
    return InstalledPluginRelease(release=release, installation=installation)


async def _persist(
    unit_of_work: SqlAlchemyUnitOfWork,
    release: PluginRelease,
    *installed: InstalledPluginRelease,
) -> None:
    await unit_of_work.plugin_releases.add(release)
    for resolved in installed:
        await unit_of_work.plugin_releases.add_installation(resolved.installation)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = create_database(
        f"sqlite+aiosqlite:///{tmp_path / 'plugin-releases.sqlite3'}"
    )
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_user(
            User(id=USER_ID, email="publisher@example.test", display_name="Publisher")
        )
        for workspace_id, slug in (
            (WORKSPACE_ID, "plugins"),
            (OTHER_WORKSPACE_ID, "other-plugins"),
        ):
            await unit_of_work.identity.add_workspace(
                Workspace(
                    id=workspace_id,
                    slug=slug,
                    name=slug.title(),
                    kind=WorkspaceKind.SHARED,
                )
            )
        await unit_of_work.commit()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_one_release_can_be_installed_system_and_workspace(
    database: Database,
) -> None:
    release = _release(1, "1")
    system = _installed(release, SYSTEM_NAMESPACE)
    workspace = _installed(release, WORKSPACE_NAMESPACE)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, release, system, workspace)
        await unit_of_work.plugin_releases.add_selection(
            PluginReleaseSelection.from_release(system)
        )
        await unit_of_work.plugin_releases.add_selection(
            PluginReleaseSelection.from_release(workspace)
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        resolved_system = await unit_of_work.plugin_releases.get_by_revision(
            SYSTEM_NAMESPACE,
            "notes",
            1,
        )
        resolved_workspace = await unit_of_work.plugin_releases.get_by_revision(
            WORKSPACE_NAMESPACE,
            "notes",
            1,
        )
        assert resolved_system is not None
        assert resolved_workspace is not None
        assert resolved_system.release.id == resolved_workspace.release.id == release.id
        assert resolved_system.installation_id != resolved_workspace.installation_id
        assert await unit_of_work.plugin_releases.list_current(SYSTEM_NAMESPACE) == [
            resolved_system
        ]
        assert await unit_of_work.plugin_releases.list_current(WORKSPACE_NAMESPACE) == [
            resolved_workspace
        ]


@pytest.mark.asyncio
async def test_release_revision_and_descriptor_identity_are_scope_neutral(
    database: Database,
) -> None:
    first = _release(1, "1")
    duplicate_revision = _release(1, "2")

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.plugin_releases.add(first)
        assert await unit_of_work.plugin_releases.next_revision("notes") == 2
        assert (
            await unit_of_work.plugin_releases.get_by_descriptor_digest(
                "notes",
                first.descriptor.digest,
            )
            == first
        )
        with pytest.raises(IntegrityError):
            await unit_of_work.plugin_releases.add(duplicate_revision)


@pytest.mark.asyncio
async def test_historical_installation_resolves_after_selection_moves(
    database: Database,
) -> None:
    first_release = _release(1, "1")
    second_release = _release(2, "2")
    first = _installed(first_release, WORKSPACE_NAMESPACE)
    second = _installed(second_release, WORKSPACE_NAMESPACE)
    selection = PluginReleaseSelection.from_release(first)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, first_release, first)
        await unit_of_work.plugin_releases.add(second_release)
        await unit_of_work.plugin_releases.add_installation(second.installation)
        await unit_of_work.plugin_releases.add_selection(selection)
        await unit_of_work.commit()

    expected_generation = selection.generation
    selection.select(second)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.plugin_releases.update_selection(
            selection,
            expected_generation=expected_generation,
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert (
            await unit_of_work.plugin_releases.get_by_revision(
                WORKSPACE_NAMESPACE,
                "notes",
                1,
            )
            == first
        )
        assert await unit_of_work.plugin_releases.list_current(WORKSPACE_NAMESPACE) == [
            second
        ]


@pytest.mark.asyncio
async def test_revocation_denies_one_installation_without_revoking_shared_release(
    database: Database,
) -> None:
    release = _release(1, "1")
    system = _installed(release, SYSTEM_NAMESPACE)
    workspace = _installed(release, WORKSPACE_NAMESPACE)
    revocation = PluginReleaseRevocation.from_release(
        workspace,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_user_id=USER_ID,
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, release, system, workspace)
        await unit_of_work.plugin_releases.add_revocation(revocation)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert (
            await unit_of_work.plugin_releases.get_revocation_by_installation_id(
                workspace.installation_id
            )
            == revocation
        )
        assert (
            await unit_of_work.plugin_releases.get_revocation_by_installation_id(
                system.installation_id
            )
            is None
        )


@pytest.mark.asyncio
async def test_installation_table_enforces_scope_policy(
    database: Database,
) -> None:
    release = _release(1, "1")
    workspace = _installed(release, WORKSPACE_NAMESPACE)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, release, workspace)
        await unit_of_work.commit()

    async with database.sessions() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                schema.plugin_installations.update()
                .where(schema.plugin_installations.c.id == workspace.installation_id)
                .values(execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_retained_catalog_queries_follow_installations(
    database: Database,
) -> None:
    shared_release = _release(1, "1", slug="alpha")
    workspace_only_release = _release(1, "2", slug="beta")
    system = _installed(shared_release, SYSTEM_NAMESPACE)
    workspace = _installed(shared_release, WORKSPACE_NAMESPACE)
    other_workspace = _installed(workspace_only_release, OTHER_WORKSPACE_NAMESPACE)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, shared_release, system, workspace)
        await _persist(unit_of_work, workspace_only_release, other_workspace)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.plugin_releases.list_catalogs(SYSTEM_NAMESPACE) == [
            shared_release.catalog
        ]
        assert await unit_of_work.plugin_releases.list_workspace_catalogs() == [
            shared_release.catalog,
            workspace_only_release.catalog,
        ]


def test_plugin_release_repository_port_keeps_append_only_release_and_install_methods() -> (
    None
):
    assert hasattr(PluginReleaseRepositoryPort, "add")
    assert hasattr(PluginReleaseRepositoryPort, "add_installation")
    assert not hasattr(PluginReleaseRepositoryPort, "update")
    assert not hasattr(PluginReleaseRepositoryPort, "delete")


@pytest.mark.asyncio
@pytest.mark.parametrize("family_count", [0, 1, 5])
async def test_catalog_reads_selected_scoped_admission_state_in_one_query(
    database: Database,
    tmp_path: Path,
    family_count: int,
) -> None:
    expected: list[PluginCatalogRelease] = []
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        for index in reversed(range(family_count)):
            slug = f"family-{index}"
            old = _release(1, "1", slug=slug)
            current = _release(2, "2", slug=slug)
            system = _installed(old, SYSTEM_NAMESPACE)
            local = _installed(current, WORKSPACE_NAMESPACE)
            foreign = _installed(current, OTHER_WORKSPACE_NAMESPACE)
            unselected = _installed(old, WORKSPACE_NAMESPACE)
            await _persist(unit_of_work, old, system, unselected)
            await _persist(unit_of_work, current, local, foreign)
            for installed in (system, local, foreign):
                selection = PluginReleaseSelection.from_release(installed)
                selection.lifecycle = PluginFamilyLifecycle.WITHDRAWN
                await unit_of_work.plugin_releases.add_selection(selection)
                revocation = None
                if installed is not local:
                    revocation = PluginReleaseRevocation.from_release(
                        installed,
                        reason=PluginReleaseRevocationReason.SECURITY,
                        revoked_by_platform_actor=(
                            "test:system" if installed is system else None
                        ),
                        revoked_by_user_id=(USER_ID if installed is foreign else None),
                    )
                    await unit_of_work.plugin_releases.add_revocation(revocation)
                if installed is not foreign:
                    expected.append(
                        PluginCatalogRelease(installed, selection, revocation)
                    )
        await unit_of_work.commit()

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "catalog-objects"),
        bucket="plugins",
    )
    event.listen(database.engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        actual = await service.list_catalog(WORKSPACE_ID)
    finally:
        event.remove(
            database.engine.sync_engine, "before_cursor_execute", record_statement
        )

    assert actual == sorted(
        expected, key=lambda entry: (entry.release.scope.value, entry.release.slug)
    )
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")
    assert all(entry.release.workspace_id in (None, WORKSPACE_ID) for entry in actual)
    assert all(
        entry.revocation is None
        for entry in actual
        if entry.release.scope is PluginReleaseScope.WORKSPACE
    )


def test_catalog_rejects_selection_for_another_installed_revision() -> None:
    first = _installed(_release(1, "1"), WORKSPACE_NAMESPACE)
    second = _installed(_release(2, "2"), WORKSPACE_NAMESPACE)
    with pytest.raises(PluginReleaseError, match="Catalog selection does not identify"):
        PluginCatalogRelease(first, PluginReleaseSelection.from_release(second), None)


def test_catalog_rejects_revocation_for_another_workspace_installation() -> None:
    release = _release(1, "1")
    local = _installed(release, WORKSPACE_NAMESPACE)
    foreign = _installed(release, OTHER_WORKSPACE_NAMESPACE)
    revocation = PluginReleaseRevocation.from_release(
        foreign,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_user_id=USER_ID,
    )
    with pytest.raises(
        PluginReleaseError, match="Catalog revocation does not identify"
    ):
        PluginCatalogRelease(
            local, PluginReleaseSelection.from_release(local), revocation
        )
