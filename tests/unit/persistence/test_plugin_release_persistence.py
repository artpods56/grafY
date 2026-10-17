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
SYSTEM_NAMESPACE = PluginReleaseNamespace()


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
    *,
    execution_policy: PluginExecutionPolicy = PluginExecutionPolicy.HOST_ELIGIBLE,
) -> InstalledPluginRelease:
    installation = PluginInstallation.from_release(
        release,
        namespace=SYSTEM_NAMESPACE,
        execution_policy=execution_policy,
        installed_by_platform_actor="test:system",
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
async def test_one_release_carries_exactly_one_system_installation(
    database: Database,
) -> None:
    release = _release(1, "1")
    system = _installed(release)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, release, system)
        await unit_of_work.plugin_releases.add_selection(
            PluginReleaseSelection.from_release(system)
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        resolved = await unit_of_work.plugin_releases.get_by_revision(
            SYSTEM_NAMESPACE,
            "notes",
            1,
        )
        assert resolved == system
        assert await unit_of_work.plugin_releases.list_current(SYSTEM_NAMESPACE) == [
            resolved
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
    first = _installed(first_release)
    second = _installed(second_release)
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
                SYSTEM_NAMESPACE,
                "notes",
                1,
            )
            == first
        )
        assert await unit_of_work.plugin_releases.list_current(SYSTEM_NAMESPACE) == [
            second
        ]


@pytest.mark.asyncio
async def test_revocation_denies_one_release_without_revoking_its_family(
    database: Database,
) -> None:
    withdrawn = _release(1, "1")
    current = _release(2, "2")
    revoked = _installed(withdrawn)
    retained = _installed(current)
    revocation = PluginReleaseRevocation.from_release(
        revoked,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_platform_actor="test:system",
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, withdrawn, revoked)
        await _persist(unit_of_work, current, retained)
        await unit_of_work.plugin_releases.add_revocation(revocation)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert (
            await unit_of_work.plugin_releases.get_revocation_by_installation_id(
                revoked.installation.id
            )
            == revocation
        )
        assert (
            await unit_of_work.plugin_releases.get_revocation_by_installation_id(
                retained.installation.id
            )
            is None
        )


@pytest.mark.asyncio
async def test_installation_table_enforces_platform_actor_provenance(
    database: Database,
) -> None:
    release = _release(1, "1")
    system = _installed(release)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, release, system)
        await unit_of_work.commit()

    async with database.sessions() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                schema.plugin_installations.update()
                .where(
                    schema.plugin_installations.c.id == system.installation.id,
                )
                .values(installed_by_platform_actor=None)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_retained_catalog_queries_follow_installations(
    database: Database,
) -> None:
    alpha = _release(1, "1", slug="alpha")
    beta = _release(1, "2", slug="beta")

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await _persist(unit_of_work, alpha, _installed(alpha))
        await _persist(unit_of_work, beta, _installed(beta))
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.plugin_releases.list_catalogs(SYSTEM_NAMESPACE) == [
            alpha.catalog,
            beta.catalog,
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("family_count", [0, 1, 5])
async def test_catalog_reads_selected_admission_state_in_one_query(
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
            retired = _installed(old)
            selected = _installed(current)
            unselected = _installed(_release(1, "3", slug=f"{slug}.unselected"))
            await _persist(unit_of_work, old, retired)
            await _persist(unit_of_work, current, selected)
            await _persist(unit_of_work, unselected.release, unselected)
            selection = PluginReleaseSelection.from_release(selected)
            selection.lifecycle = PluginFamilyLifecycle.WITHDRAWN
            await unit_of_work.plugin_releases.add_selection(selection)
            revocation = None
            if index % 2 == 0:
                revocation = PluginReleaseRevocation.from_release(
                    selected,
                    reason=PluginReleaseRevocationReason.SECURITY,
                    revoked_by_platform_actor="test:system",
                )
                await unit_of_work.plugin_releases.add_revocation(revocation)
            expected.append(PluginCatalogRelease(selected, selection, revocation))
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
        actual = await service.list_catalog()
    finally:
        event.remove(
            database.engine.sync_engine, "before_cursor_execute", record_statement
        )

    assert actual == sorted(
        expected, key=lambda entry: entry.release.release.slug
    )
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")
    assert all(
        entry.release.installation.scope is PluginReleaseScope.SYSTEM
        for entry in actual
    )


def test_catalog_rejects_selection_for_another_installed_revision() -> None:
    first = _installed(_release(1, "1"))
    second = _installed(_release(2, "2"))
    with pytest.raises(PluginReleaseError, match="Catalog selection does not identify"):
        PluginCatalogRelease(first, PluginReleaseSelection.from_release(second), None)


def test_catalog_rejects_revocation_for_another_installation() -> None:
    release = _release(1, "1")
    local = _installed(release)
    foreign = InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=SYSTEM_NAMESPACE,
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_platform_actor="test:other",
        ),
    )
    revocation = PluginReleaseRevocation.from_release(
        foreign,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_platform_actor="test:system",
    )
    with pytest.raises(
        PluginReleaseError, match="Catalog revocation does not identify"
    ):
        PluginCatalogRelease(
            local, PluginReleaseSelection.from_release(local), revocation
        )


def test_plugin_release_repository_port_keeps_append_only_release_and_install_methods() -> (
    None
):
    assert hasattr(PluginReleaseRepositoryPort, "add")
    assert hasattr(PluginReleaseRepositoryPort, "add_installation")
    assert not hasattr(PluginReleaseRepositoryPort, "update")
    assert not hasattr(PluginReleaseRepositoryPort, "delete")
