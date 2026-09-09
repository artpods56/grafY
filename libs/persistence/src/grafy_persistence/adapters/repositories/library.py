from typing import override
from uuid import UUID
from sqlalchemy import (
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from grafy_core.domain.module_library import (
    Module,
    ModulePublicationState,
    ModuleRelease,
)
from grafy_core.domain.templates import Template, TemplateState
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
    async def list_modules(self, workspace_id: UUID) -> list[Module]:
        result = await self._session.scalars(
            select(Module)
            .where(schema.modules.c.workspace_id == workspace_id)
            .order_by(
                schema.modules.c.updated_at.desc(),
                schema.modules.c.id.asc(),
            )
        )
        return list(result)

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
