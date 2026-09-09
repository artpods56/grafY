from typing import cast, override
from uuid import UUID
from sqlalchemy import (
    and_,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.schema import Table
from grafy_core.domain.plugin_catalog import PluginCatalogRelease
from grafy_core.domain.plugin_releases import PluginReleaseScope
from grafy_core.domain.errors import (
    ConcurrentWriteError,
)
from grafy_core.domain.execution_history import (
    ActiveGraphExecution,
)
from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    PluginRelease,
    PluginReleaseError,
    PluginReleaseNamespace,
    PluginRuntimeArtifact,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationError,
)
from grafy_core.domain.plugin_selection import (
    PluginReleaseSelection,
    PluginReleaseSelectionError,
)
from grafy_core.ports.plugin_releases import PluginReleaseRepositoryPort
from grafy_persistence import schema


class SqlPluginReleaseRepository(PluginReleaseRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def lock_system_revocation(self) -> tuple[ActiveGraphExecution, ...]:
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "postgresql":
            # Match cutover lock order. Execution inserts and status updates take
            # conflicting row-exclusive table locks automatically.
            await self._session.execute(
                text(
                    "LOCK TABLE plugin_release_revocations IN SHARE ROW EXCLUSIVE MODE"
                )
            )
            await self._session.execute(
                text("LOCK TABLE graph_executions IN SHARE ROW EXCLUSIVE MODE")
            )
        elif dialect_name == "sqlite":
            if self._session.in_transaction():
                raise PluginReleaseRevocationError(
                    "System Plugin revocation fence requires a fresh transaction"
                )
            await self._session.execute(text("BEGIN IMMEDIATE"))
        else:
            raise PluginReleaseRevocationError(
                "System Plugin revocation requires an execution admission fence; "
                f"database dialect {dialect_name!r} is unsupported"
            )
        executions = schema.graph_executions
        rows = await self._session.execute(
            select(executions.c.execution_id, executions.c.status)
            .where(executions.c.status.in_(("queued", "running", "cancelling")))
            .order_by(executions.c.created_at.asc(), executions.c.execution_id.asc())
        )
        return tuple(
            ActiveGraphExecution(execution_id=execution_id, status=status)
            for execution_id, status in rows
        )

    @override
    async def add(self, release: PluginRelease) -> None:
        self._session.add(release)
        await self._session.flush()

    @override
    async def add_installation(self, installation: PluginInstallation) -> None:
        await self._require_installation_release(installation)
        self._session.add(installation)
        await self._session.flush()

    @override
    async def get_by_source_digest(
        self,
        slug: str,
        source_digest: str,
    ) -> PluginRelease | None:
        return await self._session.scalar(
            select(PluginRelease)
            .where(
                schema.plugin_releases.c.slug == slug,
                schema.plugin_releases.c.source_digest == source_digest,
            )
            .order_by(schema.plugin_releases.c.revision.desc())
        )

    @override
    async def get_by_descriptor_digest(
        self,
        slug: str,
        descriptor_digest: str,
    ) -> PluginRelease | None:
        return await self._session.scalar(
            select(PluginRelease).where(
                schema.plugin_releases.c.slug == slug,
                schema.plugin_releases.c.descriptor_digest == descriptor_digest,
            )
        )

    @override
    async def get_by_revision(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
        revision: int,
    ) -> InstalledPluginRelease | None:
        row = (
            await self._session.execute(
                select(PluginRelease, PluginInstallation)
                .join(
                    PluginInstallation,
                    schema.plugin_installations.c.release_id
                    == schema.plugin_releases.c.id,
                )
                .where(
                    *self._namespace_conditions(
                        schema.plugin_installations,
                        namespace,
                    ),
                    schema.plugin_releases.c.slug == slug,
                    schema.plugin_releases.c.revision == revision,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return InstalledPluginRelease(release=row[0], installation=row[1])

    @override
    async def get_revocation_by_installation_id(
        self,
        installation_id: UUID,
    ) -> PluginReleaseRevocation | None:
        return await self._session.get(PluginReleaseRevocation, installation_id)

    @override
    async def add_revocation(
        self,
        revocation: PluginReleaseRevocation,
    ) -> PluginReleaseRevocation:
        await self._require_revoked_release(revocation)
        existing = await self.get_revocation_by_installation_id(
            revocation.installation_id
        )
        if existing is not None:
            if existing.has_same_intent(revocation):
                return existing
            raise PluginReleaseRevocationError(
                "Plugin release revocation already exists with different immutable "
                f"intent for {revocation.scope.value}:"
                f"{revocation.workspace_id}:{revocation.slug}@"
                f"{revocation.revision} ({revocation.installation_id})"
            )
        self._session.add(revocation)
        await self._session.flush()
        return revocation

    @override
    async def next_revision(
        self,
        slug: str,
    ) -> int:
        await self._session.execute(
            select(schema.plugin_releases.c.id)
            .where(schema.plugin_releases.c.slug == slug)
            .with_for_update()
        )
        latest = await self._session.scalar(
            select(func.max(schema.plugin_releases.c.revision)).where(
                schema.plugin_releases.c.slug == slug,
            )
        )
        return 1 if latest is None else int(latest) + 1

    @override
    async def family_exists(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
    ) -> bool:
        release_id = await self._session.scalar(
            select(schema.plugin_installations.c.id)
            .where(
                *self._namespace_conditions(schema.plugin_installations, namespace),
                schema.plugin_installations.c.slug == slug,
            )
            .limit(1)
        )
        return release_id is not None

    @override
    async def workspace_family_exists(self, slug: str) -> bool:
        release_id = await self._session.scalar(
            select(schema.plugin_installations.c.id)
            .where(
                schema.plugin_installations.c.scope == "workspace",
                schema.plugin_installations.c.slug == slug,
            )
            .limit(1)
        )
        return release_id is not None

    @override
    async def list_workspace_catalogs(self) -> list[PluginCatalogManifest]:
        result = await self._session.scalars(
            select(schema.plugin_releases.c.catalog)
            .join(
                schema.plugin_installations,
                schema.plugin_installations.c.release_id == schema.plugin_releases.c.id,
            )
            .where(schema.plugin_installations.c.scope == "workspace")
            .order_by(
                schema.plugin_installations.c.workspace_id.asc(),
                schema.plugin_releases.c.slug.asc(),
                schema.plugin_releases.c.revision.asc(),
            )
        )
        return list(result)

    @override
    async def list_catalogs(
        self,
        namespace: PluginReleaseNamespace,
    ) -> list[PluginCatalogManifest]:
        result = await self._session.scalars(
            select(schema.plugin_releases.c.catalog)
            .join(
                schema.plugin_installations,
                schema.plugin_installations.c.release_id == schema.plugin_releases.c.id,
            )
            .where(*self._namespace_conditions(schema.plugin_installations, namespace))
            .order_by(
                schema.plugin_releases.c.slug.asc(),
                schema.plugin_releases.c.revision.asc(),
            )
        )
        return list(result)

    @override
    async def list_catalog(self, workspace_id: UUID) -> list[PluginCatalogRelease]:
        releases = schema.plugin_releases
        selections = schema.plugin_release_selections
        installations = schema.plugin_installations
        rows = await self._session.execute(
            select(
                PluginRelease,
                PluginInstallation,
                PluginReleaseSelection,
                PluginReleaseRevocation,
            )
            .select_from(PluginReleaseSelection)
            .join(PluginRelease, selections.c.selected_release_id == releases.c.id)
            .join(
                PluginInstallation,
                and_(
                    installations.c.release_id == releases.c.id,
                    installations.c.scope == selections.c.scope,
                    installations.c.workspace_id.is_not_distinct_from(
                        selections.c.workspace_id
                    ),
                ),
            )
            .outerjoin(
                PluginReleaseRevocation,
                schema.plugin_release_revocations.c.installation_id
                == installations.c.id,
            )
            .where(
                or_(
                    and_(
                        selections.c.scope == PluginReleaseScope.SYSTEM,
                        selections.c.workspace_id.is_(None),
                    ),
                    and_(
                        selections.c.scope == PluginReleaseScope.WORKSPACE,
                        selections.c.workspace_id == workspace_id,
                    ),
                )
            )
            .order_by(selections.c.scope.asc(), releases.c.slug.asc())
        )
        return [
            PluginCatalogRelease(
                release=InstalledPluginRelease(
                    release=release, installation=installation
                ),
                selection=selection,
                revocation=revocation,
            )
            for release, installation, selection, revocation in rows
        ]

    @override
    async def list_current(
        self,
        namespace: PluginReleaseNamespace,
    ) -> list[InstalledPluginRelease]:
        releases = schema.plugin_releases
        selections = schema.plugin_release_selections
        rows = await self._session.execute(
            select(PluginRelease, PluginInstallation)
            .join(
                selections,
                selections.c.selected_release_id == releases.c.id,
            )
            .join(
                PluginInstallation,
                and_(
                    schema.plugin_installations.c.release_id == releases.c.id,
                    schema.plugin_installations.c.scope == selections.c.scope,
                    schema.plugin_installations.c.workspace_id.is_not_distinct_from(
                        selections.c.workspace_id
                    ),
                ),
            )
            .where(*self._namespace_conditions(selections, namespace))
            .order_by(releases.c.slug.asc())
        )
        return [
            InstalledPluginRelease(release=release, installation=installation)
            for release, installation in rows
        ]

    @override
    async def get_selection(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
    ) -> PluginReleaseSelection | None:
        return await self._session.scalar(
            select(PluginReleaseSelection).where(
                *self._namespace_conditions(
                    schema.plugin_release_selections,
                    namespace,
                ),
                schema.plugin_release_selections.c.slug == slug,
            )
        )

    @override
    async def add_selection(
        self,
        selection: PluginReleaseSelection,
    ) -> None:
        await self._require_selected_release(selection)
        self._session.add(selection)
        await self._session.flush()

    @override
    async def update_selection(
        self,
        selection: PluginReleaseSelection,
        *,
        expected_generation: int,
    ) -> None:
        if isinstance(expected_generation, bool) or expected_generation < 1:
            raise ValueError("Expected Plugin selection generation must be positive")
        if selection.generation <= expected_generation:
            raise ValueError(
                "Updated Plugin selection generation must exceed the expected "
                "generation"
            )
        await self._require_selected_release(selection)
        table = schema.plugin_release_selections
        with self._session.no_autoflush:
            result = cast(
                CursorResult[tuple[object, ...]],
                await self._session.execute(
                    update(table)
                    .where(
                        table.c.id == selection.id,
                        *self._namespace_conditions(table, selection.namespace),
                        table.c.slug == selection.slug,
                        table.c.generation == expected_generation,
                    )
                    .values(
                        selected_release_id=selection.selected_release_id,
                        selected_revision=selection.selected_revision,
                        lifecycle=selection.lifecycle,
                        generation=selection.generation,
                        updated_at=selection.updated_at,
                        updated_by_actor=selection.updated_by_actor,
                    )
                ),
            )
        if result.rowcount != 1:
            raise ConcurrentWriteError(
                "Plugin release selection changed concurrently for "
                f"{selection.namespace.scope.value} family {selection.slug!r}; "
                f"expected generation {expected_generation}"
            )
        if selection in self._session.sync_session:
            await self._session.refresh(selection)

    @override
    async def list_runtime_artifacts(self) -> list[PluginRuntimeArtifact]:
        result = await self._session.scalars(
            select(PluginRelease).where(
                schema.plugin_releases.c.runtime_artifact.is_not(None)
            )
        )
        artifacts: list[PluginRuntimeArtifact] = []
        for release in result:
            if release.runtime_artifact is not None:
                artifacts.append(release.runtime_artifact)
        return artifacts

    @staticmethod
    def _namespace_conditions(
        table: Table,
        namespace: PluginReleaseNamespace,
    ) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
        owner_condition = (
            table.c.workspace_id.is_(None)
            if namespace.workspace_id is None
            else table.c.workspace_id == namespace.workspace_id
        )
        return table.c.scope == namespace.scope, owner_condition

    async def _require_selected_release(
        self,
        selection: PluginReleaseSelection,
    ) -> None:
        with self._session.no_autoflush:
            row = (
                await self._session.execute(
                    select(PluginRelease, PluginInstallation)
                    .join(
                        PluginInstallation,
                        schema.plugin_installations.c.release_id
                        == schema.plugin_releases.c.id,
                    )
                    .where(
                        schema.plugin_releases.c.id == selection.selected_release_id,
                        *self._namespace_conditions(
                            schema.plugin_installations,
                            selection.namespace,
                        ),
                    )
                )
            ).one_or_none()
        if row is None:
            raise PluginReleaseSelectionError(
                f"Selected Plugin release {selection.selected_release_id} is not "
                "installed in the selection namespace"
            )
        release = InstalledPluginRelease(release=row[0], installation=row[1])
        if (
            release.namespace != selection.namespace
            or release.slug != selection.slug
            or release.revision != selection.selected_revision
        ):
            raise PluginReleaseSelectionError(
                "Selected Plugin release identity does not match selection family "
                f"{selection.namespace.scope.value}:{selection.slug}:"
                f"{selection.selected_revision}"
            )

    async def _require_revoked_release(
        self,
        revocation: PluginReleaseRevocation,
    ) -> None:
        with self._session.no_autoflush:
            row = (
                await self._session.execute(
                    select(PluginRelease, PluginInstallation)
                    .join(
                        PluginInstallation,
                        schema.plugin_installations.c.release_id
                        == schema.plugin_releases.c.id,
                    )
                    .where(
                        schema.plugin_installations.c.id == revocation.installation_id
                    )
                )
            ).one_or_none()
        if row is None:
            raise PluginReleaseRevocationError(
                f"Revoked Plugin installation {revocation.installation_id} does not exist"
            )
        release = InstalledPluginRelease(release=row[0], installation=row[1])
        if (
            release.namespace != revocation.namespace
            or release.slug != revocation.slug
            or release.revision != revocation.revision
        ):
            raise PluginReleaseRevocationError(
                "Revoked Plugin release identity does not match exact release "
                f"{revocation.scope.value}:{revocation.workspace_id}:"
                f"{revocation.slug}@{revocation.revision} "
                f"({revocation.installation_id})"
            )

    async def _require_installation_release(
        self,
        installation: PluginInstallation,
    ) -> None:
        with self._session.no_autoflush:
            release = await self._session.get(PluginRelease, installation.release_id)
        if release is None:
            raise PluginReleaseError(
                f"Installed Plugin release {installation.release_id} does not exist"
            )
        InstalledPluginRelease(release=release, installation=installation)
