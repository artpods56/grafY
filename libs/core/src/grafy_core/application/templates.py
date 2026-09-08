from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from grafy_core.application.graph_creation import stage_checkpointed_graph
from grafy_core.application.identity import authorize_workspace, authorize_workspaces
from grafy_core.domain.collaboration import (
    sanitize_document_for_cross_workspace_copy,
)
from grafy_core.domain.errors import CollaborationCommandRejectedError, NotFoundError
from grafy_core.domain.identity import ActorContext, WorkspaceCapability
from grafy_core.domain.saved_graphs import (
    GraphOrganization,
    SavedGraph,
    SavedGraphDocument,
)
from grafy_core.domain.templates import (
    Template,
    TemplateCopyRejectedError,
    TemplateUnavailableError,
)
from grafy_core.ports.templates import TemplateUnitOfWorkPort


@dataclass(frozen=True, slots=True)
class TemplateInstantiation:
    template_id: UUID
    source_workspace_id: UUID
    destination_workspace_id: UUID
    graph: SavedGraph
    folder_id: UUID | None


class TemplateService:
    """Create and instantiate immutable graph-copy sources."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], TemplateUnitOfWorkPort],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def create_from_graph_revision(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        source_graph_id: UUID,
        source_revision: int,
        name: str,
        description: str | None,
    ) -> Template:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.CREATE_TEMPLATE,
            )
            revision = await unit_of_work.graphs.get_revision(
                workspace_id,
                source_graph_id,
                source_revision,
            )
            if revision is None:
                raise NotFoundError(
                    "Saved graph revision",
                    f"{source_graph_id}@{source_revision}",
                )
            try:
                snapshot_document = sanitize_document_for_cross_workspace_copy(
                    revision.document
                )
            except CollaborationCommandRejectedError as exc:
                raise TemplateCopyRejectedError(
                    reason_code=exc.error_code,
                    diagnostic_message=str(exc),
                ) from exc
            template = Template(
                workspace_id=workspace_id,
                source_graph_id=source_graph_id,
                source_revision=source_revision,
                source_graph_name=revision.name,
                snapshot_document=snapshot_document,
                name=name,
                description=description,
                created_by_user_id=actor.user_id,
            )
            await unit_of_work.templates.add(template)
            await unit_of_work.commit()
            return template

    async def list(
        self,
        workspace_id: UUID,
        *,
        query: str | None = None,
        include_archived: bool = False,
    ) -> list[Template]:
        normalized_query = query.strip() if query is not None else None
        if normalized_query == "":
            normalized_query = None
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.templates.list(
                workspace_id,
                query=normalized_query,
                include_archived=include_archived,
            )

    async def get(self, workspace_id: UUID, template_id: UUID) -> Template:
        async with self._unit_of_work_factory() as unit_of_work:
            template = await unit_of_work.templates.get(workspace_id, template_id)
        if template is None:
            raise NotFoundError("Template", str(template_id))
        return template

    async def update_metadata(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        template_id: UUID,
        name: str,
        description: str | None,
    ) -> Template:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.CREATE_TEMPLATE,
            )
            template = await unit_of_work.templates.get(workspace_id, template_id)
            if template is None:
                raise NotFoundError("Template", str(template_id))
            template.update_metadata(name=name, description=description)
            await unit_of_work.commit()
            return template

    async def archive(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        template_id: UUID,
    ) -> Template:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.MANAGE_TEMPLATE_LIBRARY,
            )
            template = await unit_of_work.templates.get(workspace_id, template_id)
            if template is None:
                raise NotFoundError("Template", str(template_id))
            template.archive()
            await unit_of_work.commit()
            return template

    async def instantiate(
        self,
        *,
        actor: ActorContext,
        source_workspace_id: UUID,
        template_id: UUID,
        destination_workspace_id: UUID,
        name: str,
        folder_id: UUID | None,
    ) -> TemplateInstantiation:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspaces(
                unit_of_work.identity,
                actor=actor,
                requirements=(
                    (source_workspace_id, WorkspaceCapability.VIEW_GRAPH),
                    (destination_workspace_id, WorkspaceCapability.CREATE_GRAPH),
                ),
            )
            template = await unit_of_work.templates.get(
                source_workspace_id,
                template_id,
            )
            if template is None:
                raise NotFoundError("Template", str(template_id))
            if not template.is_available:
                raise TemplateUnavailableError("Archived templates cannot be used")
            if folder_id is not None:
                folder = await unit_of_work.graphs.get_folder(
                    destination_workspace_id,
                    folder_id,
                )
                if folder is None:
                    raise NotFoundError("Graph folder", str(folder_id))

            independent_document = SavedGraphDocument.model_validate(
                template.snapshot_document.model_dump(mode="json")
            )
            graph = SavedGraph(
                workspace_id=destination_workspace_id,
                created_by_user_id=actor.user_id,
                name=name,
                document=independent_document,
            )
            await stage_checkpointed_graph(
                graph,
                graphs=unit_of_work.graphs,
                collaboration=unit_of_work.collaboration,
            )

            if folder_id is not None:
                await unit_of_work.graphs.save_organization(
                    GraphOrganization(
                        workspace_id=destination_workspace_id,
                        graph_id=graph.id,
                        folder_id=folder_id,
                    )
                )
            await unit_of_work.commit()
            return TemplateInstantiation(
                template_id=template.id,
                source_workspace_id=source_workspace_id,
                destination_workspace_id=destination_workspace_id,
                graph=graph,
                folder_id=folder_id,
            )


__all__ = ["TemplateInstantiation", "TemplateService"]
