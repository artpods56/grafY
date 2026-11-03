"""Project browser, filing, archive, star and open operations (ADR 0020).

A Project is the Workspace-owned object the browser lists and the room opens on.
Everything here is about that object's life outside the document: where it is filed,
whether it is archived, whether the acting user starred it, and when they last opened
it. The document itself, its head and its checkpoints belong to
:mod:`grafy_core.application.collaboration`; this service only reads the Project row
and the organization and per-user-state rows that hang off it.

Every operation is Workspace-scoped: a Project of another Workspace is indistinguishable
from a missing one, and every mutation is authorized against a Workspace capability
before it touches a row. Each mutation has its inverse: create/delete folder, file and
unfile, archive and restore, star and unstar.
"""

from __future__ import annotations
# Late annotations: this service names an operation ``list``, and inside the class
# body that method would otherwise shadow the builtin in the annotations below it.

from collections.abc import Callable
from uuid import UUID

from grafy_core.application.identity import authorize_workspace
from grafy_core.domain.errors import (
    NotFoundError,
    ProjectFolderNameConflictError,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceCapability,
)
from grafy_core.domain.projects import (
    Project,
    ProjectBrowserItem,
    ProjectCheckpoint,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_core.ports.projects import ProjectUnitOfWorkPort


class ProjectService:
    """Ownership, filing and per-user view of Projects inside one Workspace."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], ProjectUnitOfWorkPort],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def get(self, *, workspace_id: UUID, project_id: UUID) -> Project:
        """The Project identity row, or ``NotFoundError`` outside its Workspace."""

        async with self._unit_of_work_factory() as unit_of_work:
            project = await unit_of_work.projects.get(workspace_id, project_id)
        if project is None:
            raise NotFoundError("Project", str(project_id))
        return project

    async def list(self, *, workspace_id: UUID) -> list[Project]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.projects.list(workspace_id)

    async def list_accessible(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID | None = None,
    ) -> list[ProjectBrowserItem]:
        """The browser listing for one user, across Workspaces or inside one.

        Membership is the boundary: the repository returns only Projects in
        Workspaces the user can see, and each item carries its own location.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.projects.list_accessible(
                actor.user_id,
                workspace_id=workspace_id,
            )

    async def get_checkpoint(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        revision: int,
    ) -> ProjectCheckpoint:
        async with self._unit_of_work_factory() as unit_of_work:
            if await unit_of_work.projects.get(workspace_id, project_id) is None:
                raise NotFoundError("Project", str(project_id))
            checkpoint = await unit_of_work.projects.get_checkpoint(
                workspace_id,
                project_id,
                revision,
            )
        if checkpoint is None:
            raise NotFoundError("Project checkpoint", f"{project_id}@{revision}")
        return checkpoint

    async def list_checkpoints(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
    ) -> list[ProjectCheckpoint]:
        async with self._unit_of_work_factory() as unit_of_work:
            if await unit_of_work.projects.get(workspace_id, project_id) is None:
                raise NotFoundError("Project", str(project_id))
            return await unit_of_work.projects.list_checkpoints(
                workspace_id,
                project_id,
            )

    async def titles_referencing_artifact(
        self,
        *,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> dict[UUID, str]:
        """Map each Project holding ``artifact_id`` to its name.

        The head and every retained checkpoint count as a reference, so restoring
        an old checkpoint cannot bring back a reference to deleted content.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.projects.titles_referencing_artifact(
                workspace_id,
                artifact_id,
            )

    async def create_folder(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        name: str,
    ) -> ProjectFolder:
        folder = ProjectFolder(workspace_id=workspace_id, name=name)
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_PROJECT,
            )
            existing = await unit_of_work.projects.get_folder_by_name(
                workspace_id,
                folder.name,
            )
            if existing is not None:
                raise ProjectFolderNameConflictError(
                    workspace_id=workspace_id,
                    name=folder.name,
                )
            await unit_of_work.projects.add_folder(folder)
            await self._audit(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="project.folder.create",
                resource_id=str(folder.id),
            )
            await unit_of_work.commit()
        return folder

    async def list_folders(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
    ) -> list[ProjectFolder]:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.VIEW_PROJECT,
            )
            return await unit_of_work.projects.list_folders(workspace_id)

    async def rename_folder(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        folder_id: UUID,
        name: str,
    ) -> ProjectFolder:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_PROJECT,
            )
            folder = await unit_of_work.projects.get_folder(workspace_id, folder_id)
            if folder is None:
                raise NotFoundError("Project folder", str(folder_id))
            normalized_name = ProjectFolder(
                workspace_id=workspace_id,
                name=name,
            ).name
            existing = await unit_of_work.projects.get_folder_by_name(
                workspace_id,
                normalized_name,
            )
            if existing is not None and existing.id != folder.id:
                raise ProjectFolderNameConflictError(
                    workspace_id=workspace_id,
                    name=normalized_name,
                )
            folder.rename(normalized_name)
            await unit_of_work.projects.save_folder(folder)
            await self._audit(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="project.folder.rename",
                resource_id=str(folder.id),
            )
            await unit_of_work.commit()
        return folder

    async def delete_folder(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> None:
        """Remove a folder. The Projects it held stay, and become Unfiled."""

        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_PROJECT,
            )
            folder = await unit_of_work.projects.get_folder(workspace_id, folder_id)
            if folder is None:
                raise NotFoundError("Project folder", str(folder_id))
            await unit_of_work.projects.unfile_projects_in_folder(
                workspace_id,
                folder_id,
            )
            await unit_of_work.projects.remove_folder(folder)
            await self._audit(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="project.folder.delete",
                resource_id=str(folder.id),
            )
            await unit_of_work.commit()

    async def assign_folder(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        folder_id: UUID | None,
    ) -> ProjectOrganization:
        """File a Project, or unfile it by passing ``folder_id=None``."""

        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_PROJECT,
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            if folder_id is not None:
                folder = await unit_of_work.projects.get_folder(
                    workspace_id,
                    folder_id,
                )
                if folder is None:
                    raise NotFoundError("Project folder", str(folder_id))
            organization = await self._organization_or_new(
                unit_of_work,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            organization.assign_folder(folder_id)
            await unit_of_work.projects.save_organization(organization)
            await self._audit(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="project.folder.assign",
                resource_id=str(project_id),
            )
            await unit_of_work.commit()
        return organization

    async def archive(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectOrganization:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_PROJECT,
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            organization = await self._organization_or_new(
                unit_of_work,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            organization.archive()
            await unit_of_work.projects.save_organization(organization)
            await self._audit(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="project.archive",
                resource_id=str(project_id),
            )
            await unit_of_work.commit()
        return organization

    async def restore(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectOrganization:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_PROJECT,
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            organization = await self._organization_or_new(
                unit_of_work,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            organization.restore()
            await unit_of_work.projects.save_organization(organization)
            await self._audit(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="project.restore",
                resource_id=str(project_id),
            )
            await unit_of_work.commit()
        return organization

    async def set_starred(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        starred: bool,
    ) -> UserProjectState:
        """Star or unstar a Project for the acting user only. Never grants access."""

        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.VIEW_PROJECT,
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            state = await self._user_state_or_new(
                unit_of_work,
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=actor.user_id,
            )
            state.set_starred(starred)
            await unit_of_work.projects.save_user_state(state)
            await unit_of_work.commit()
        return state

    async def record_open(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
    ) -> UserProjectState:
        """Note that the acting user opened this Project, keeping the newest stamp."""

        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.VIEW_PROJECT,
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            state = await self._user_state_or_new(
                unit_of_work,
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=actor.user_id,
            )
            state.record_open()
            await unit_of_work.projects.save_user_state(state)
            await unit_of_work.commit()
        return state

    async def _project_or_raise(
        self,
        unit_of_work: ProjectUnitOfWorkPort,
        workspace_id: UUID,
        project_id: UUID,
    ) -> Project:
        project = await unit_of_work.projects.get(workspace_id, project_id)
        if project is None:
            raise NotFoundError("Project", str(project_id))
        return project

    async def _organization_or_new(
        self,
        unit_of_work: ProjectUnitOfWorkPort,
        *,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectOrganization:
        organization = await unit_of_work.projects.get_organization(
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if organization is None:
            organization = ProjectOrganization(
                workspace_id=workspace_id,
                project_id=project_id,
            )
        return organization

    async def _user_state_or_new(
        self,
        unit_of_work: ProjectUnitOfWorkPort,
        *,
        workspace_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> UserProjectState:
        state = await unit_of_work.projects.get_user_state(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
        )
        if state is None:
            state = UserProjectState(
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
            )
        return state

    async def _audit(
        self,
        unit_of_work: ProjectUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        operation: str,
        resource_id: str,
        resource_type: str = "project",
    ) -> None:
        """Metadata-only shared state changed, so the shared change is auditable."""

        await unit_of_work.security_audit.add(
            SecurityAuditEvent(
                actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                user_id=actor.user_id,
                credential_reference=actor.credential_reference,
                workspace_id=workspace_id,
                operation=operation,
                outcome=SecurityAuditOutcome.SUCCESS,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )


__all__ = ["ProjectService"]
