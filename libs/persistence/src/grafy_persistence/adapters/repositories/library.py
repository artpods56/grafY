from typing import override
from uuid import UUID
from sqlalchemy import (
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from grafy_core.domain.errors import LibraryFolderNameConflictError
from grafy_core.domain.library import LibraryFolder
from grafy_core.domain.module_library import (
    Module,
    ModulePublicationState,
    ModuleRelease,
)
from grafy_core.domain.templates import Template, TemplateState
from grafy_core.ports.library_folders import LibraryFolderRepositoryPort
from grafy_core.ports.module_library import ModuleLibraryRepositoryPort
from grafy_core.ports.templates import TemplateRepositoryPort
from grafy_persistence import schema


class SqlModuleLibraryRepository(ModuleLibraryRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, module: Module) -> None:
        self._session.add(module)
        await self._session.flush()

    @override
    async def add_release(self, release: ModuleRelease) -> None:
        self._session.add(release)
        await self._session.flush()

    @override
    async def get(self, workspace_id: UUID, module_id: UUID) -> Module | None:
        return await self._session.scalar(
            select(Module).where(
                schema.modules.c.workspace_id == workspace_id,
                schema.modules.c.id == module_id,
            )
        )

    @override
    async def get_by_source_graph(
        self,
        workspace_id: UUID,
        source_graph_id: UUID,
    ) -> Module | None:
        return await self._session.scalar(
            select(Module).where(
                schema.modules.c.workspace_id == workspace_id,
                schema.modules.c.source_graph_id == source_graph_id,
            )
        )

    @override
    async def get_release(
        self,
        workspace_id: UUID,
        module_id: UUID,
        revision: int,
    ) -> ModuleRelease | None:
        return await self._session.get(
            ModuleRelease,
            (workspace_id, module_id, revision),
        )

    @override
    async def list_library(self, workspace_id: UUID) -> list[Module]:
        result = await self._session.scalars(
            select(Module)
            .where(
                schema.modules.c.workspace_id == workspace_id,
                schema.modules.c.publication_state.in_(
                    (
                        ModulePublicationState.PUBLISHED,
                        ModulePublicationState.DEPRECATED,
                    )
                ),
            )
            .order_by(
                schema.modules.c.name.asc(),
                schema.modules.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def list_releases(
        self,
        workspace_id: UUID,
        module_id: UUID,
    ) -> list[ModuleRelease]:
        result = await self._session.scalars(
            select(ModuleRelease)
            .where(
                schema.module_releases.c.workspace_id == workspace_id,
                schema.module_releases.c.module_id == module_id,
            )
            .order_by(schema.module_releases.c.revision.desc())
        )
        return list(result)


class SqlTemplateRepository(TemplateRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, template: Template) -> None:
        self._session.add(template)
        await self._session.flush()

    @override
    async def get(
        self,
        workspace_id: UUID,
        template_id: UUID,
    ) -> Template | None:
        return await self._session.scalar(
            select(Template).where(
                schema.templates.c.workspace_id == workspace_id,
                schema.templates.c.id == template_id,
            )
        )

    @override
    async def list(
        self,
        workspace_id: UUID,
        *,
        query: str | None,
        include_archived: bool,
    ) -> list[Template]:
        statement = select(Template).where(
            schema.templates.c.workspace_id == workspace_id
        )
        if not include_archived:
            statement = statement.where(
                schema.templates.c.state == TemplateState.ACTIVE
            )
        if query is not None:
            pattern = f"%{query.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(schema.templates.c.name).like(pattern),
                    func.lower(schema.templates.c.description).like(pattern),
                    func.lower(schema.templates.c.source_graph_name).like(pattern),
                )
            )
        result = await self._session.scalars(
            statement.order_by(
                schema.templates.c.name.asc(),
                schema.templates.c.id.asc(),
            )
        )
        return list(result)


def _is_unique_violation(exc: IntegrityError) -> bool:
    """Whether an IntegrityError came from a unique index on either backend."""
    original = exc.orig
    return (
        getattr(original, "sqlstate", None) == "23505"
        or getattr(original, "pgcode", None) == "23505"
        or "UNIQUE constraint failed" in str(original)
    )


def _folder_from_row(row: Row) -> LibraryFolder:
    return LibraryFolder(
        workspace_id=row.workspace_id,
        name=row.name,
        parent_id=row.parent_id,
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlLibraryFolderRepository(LibraryFolderRepositoryPort):
    """The Library folder tree and its artifact placements, in plain Core.

    ``LibraryFolder`` stays a domain dataclass: every statement here names its
    columns and builds the folder itself, so nothing persists a derived
    ``name_key`` the domain did not produce.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, folder: LibraryFolder) -> None:
        try:
            await self._session.execute(
                insert(schema.library_folders).values(
                    id=folder.id,
                    workspace_id=folder.workspace_id,
                    parent_id=folder.parent_id,
                    name=folder.name,
                    name_key=folder.name_key,
                    created_at=folder.created_at,
                    updated_at=folder.updated_at,
                )
            )
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise LibraryFolderNameConflictError(
                workspace_id=folder.workspace_id,
                parent_id=folder.parent_id,
                name=folder.name,
            ) from exc

    @override
    async def get(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> LibraryFolder | None:
        row = await self._session.execute(
            select(schema.library_folders)
            .where(
                schema.library_folders.c.workspace_id == workspace_id,
                schema.library_folders.c.id == folder_id,
            )
            .limit(1)
        )
        found = row.first()
        return None if found is None else _folder_from_row(found)

    @override
    async def get_by_name(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        name_key: str,
    ) -> LibraryFolder | None:
        parent_clause = (
            schema.library_folders.c.parent_id.is_(None)
            if parent_id is None
            else schema.library_folders.c.parent_id == parent_id
        )
        row = await self._session.execute(
            select(schema.library_folders)
            .where(
                schema.library_folders.c.workspace_id == workspace_id,
                schema.library_folders.c.name_key == name_key,
                parent_clause,
            )
            .limit(1)
        )
        found = row.first()
        return None if found is None else _folder_from_row(found)

    @override
    async def list(self, workspace_id: UUID) -> list[LibraryFolder]:
        result = await self._session.execute(
            select(schema.library_folders)
            .where(schema.library_folders.c.workspace_id == workspace_id)
            .order_by(
                schema.library_folders.c.name_key.asc(),
                schema.library_folders.c.id.asc(),
            )
        )
        return [_folder_from_row(row) for row in result]

    @override
    async def save(self, folder: LibraryFolder) -> None:
        try:
            await self._session.execute(
                update(schema.library_folders)
                .where(
                    schema.library_folders.c.workspace_id == folder.workspace_id,
                    schema.library_folders.c.id == folder.id,
                )
                .values(
                    name=folder.name,
                    name_key=folder.name_key,
                    parent_id=folder.parent_id,
                    updated_at=folder.updated_at,
                )
            )
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise LibraryFolderNameConflictError(
                workspace_id=folder.workspace_id,
                parent_id=folder.parent_id,
                name=folder.name,
            ) from exc

    @override
    async def remove(self, folder: LibraryFolder) -> None:
        await self._session.execute(
            delete(schema.library_folders).where(
                schema.library_folders.c.workspace_id == folder.workspace_id,
                schema.library_folders.c.id == folder.id,
            )
        )

    @override
    async def count_children(self, workspace_id: UUID, folder_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(schema.library_folders)
            .where(
                schema.library_folders.c.workspace_id == workspace_id,
                schema.library_folders.c.parent_id == folder_id,
            )
        )
        return result.scalar_one()

    @override
    async def placements(self, workspace_id: UUID) -> dict[UUID, UUID]:
        result = await self._session.execute(
            select(
                schema.library_artifact_placements.c.artifact_id,
                schema.library_artifact_placements.c.folder_id,
            ).where(
                schema.library_artifact_placements.c.workspace_id == workspace_id
            )
        )
        return {row.artifact_id: row.folder_id for row in result}

    @override
    async def count_placements(self, workspace_id: UUID, folder_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(schema.library_artifact_placements)
            .where(
                schema.library_artifact_placements.c.workspace_id == workspace_id,
                schema.library_artifact_placements.c.folder_id == folder_id,
            )
        )
        return result.scalar_one()

    @override
    async def place(
        self,
        workspace_id: UUID,
        artifact_ids: list[UUID],
        folder_id: UUID | None,
    ) -> None:
        if not artifact_ids:
            return
        await self._session.execute(
            delete(schema.library_artifact_placements).where(
                schema.library_artifact_placements.c.workspace_id == workspace_id,
                schema.library_artifact_placements.c.artifact_id.in_(artifact_ids),
            )
        )
        if folder_id is None:
            return
        await self._session.execute(
            insert(schema.library_artifact_placements).values(
                [
                    {
                        "workspace_id": workspace_id,
                        "artifact_id": artifact_id,
                        "folder_id": folder_id,
                    }
                    for artifact_id in artifact_ids
                ]
            )
        )
