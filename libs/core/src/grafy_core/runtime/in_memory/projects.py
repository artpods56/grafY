from dataclasses import replace
from datetime import UTC, datetime
from typing import final, override
from uuid import UUID

from grafy_core.domain.errors import (
    ConcurrentWriteError,
    ObjectAlreadyExistsError,
    ProjectFolderNameConflictError,
)
from grafy_core.domain.projects import (
    Project,
    ProjectBrowserCreator,
    ProjectBrowserDraft,
    ProjectBrowserFolder,
    ProjectBrowserItem,
    ProjectCheckpoint,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.ports.projects import ProjectRepositoryPort

from grafy_core.runtime.in_memory.store import InMemoryDataStore, _newest_first


@final
class InMemoryProjectRepository(ProjectRepositoryPort):
    """Projects, their append-only checkpoints, filing, and the browser read.

    Every read is scoped by Workspace, so a Project of another Workspace is
    indistinguishable from one that was never there. Projects, folders and
    organizations are handed out as copies and written back field by field, which
    is what the SQL adapter does with its rows; checkpoints are appended and never
    touched again.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    def _owned(self, workspace_id: UUID, project_id: UUID) -> Project | None:
        project = self._store.projects.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            return None
        return project

    @override
    async def add(self, project: Project) -> None:
        if self._owned(project.workspace_id, project.id) is not None:
            raise ObjectAlreadyExistsError(f"Project already exists: {project.id}")
        self._store.projects[project.id] = replace(project)

    @override
    async def get(self, workspace_id: UUID, project_id: UUID) -> Project | None:
        project = self._owned(workspace_id, project_id)
        return None if project is None else replace(project)

    @override
    async def save(self, project: Project) -> None:
        # Name and updated_at are the only columns an update writes.
        stored = self._owned(project.workspace_id, project.id)
        if stored is None:
            return
        stored.name = project.name
        stored.updated_at = project.updated_at

    @override
    async def remove(self, workspace_id: UUID, project: Project) -> None:
        if self._owned(workspace_id, project.id) is None:
            return
        _ = self._store.projects.pop(project.id, None)

    @override
    async def list(self, workspace_id: UUID) -> list[Project]:
        return _newest_first(
            [
                replace(project)
                for project in self._store.projects.values()
                if project.workspace_id == workspace_id
            ],
            stamp=lambda project: project.updated_at,
            ident=lambda project: project.id,
        )

    @override
    async def list_accessible(
        self,
        user_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> list[ProjectBrowserItem]:
        member_of = {
            stored_workspace
            for stored_workspace, members in self._store.workspace_members.items()
            if user_id in members
        }
        # A Project is listed off its head, and only where the user's Workspace is
        # known: no head is no row, exactly as the browser's inner join.
        listed = [
            head
            for (
                head_workspace,
                head_project,
            ), head in self._store.project_heads.items()
            if head_project in self._store.projects
            and head_workspace in member_of
            and head_workspace in self._store.workspace_locations
            and (workspace_id is None or head_workspace == workspace_id)
        ]
        items: list[ProjectBrowserItem] = []
        for head in _newest_first(
            listed,
            stamp=lambda head: head.updated_at,
            ident=lambda head: head.project_id,
        ):
            project = self._store.projects[head.project_id]
            document = head.document
            organization = self._store.project_organizations.get(
                (head.workspace_id, head.project_id)
            )
            state = self._store.user_project_states.get(
                (head.workspace_id, head.project_id, user_id)
            )
            folder = (
                None
                if organization is None or organization.folder_id is None
                else self._store.project_folders.get(organization.folder_id)
            )
            display_name = (
                None
                if project.created_by_user_id is None
                else self._store.user_display_names.get(project.created_by_user_id)
            )
            items.append(
                ProjectBrowserItem(
                    id=head.project_id,
                    draft=ProjectBrowserDraft(
                        name=head.name,
                        head_sequence=head.collaboration_sequence,
                        checkpoint_sequence=head.checkpoint_sequence,
                        checkpoint_revision=head.checkpoint_revision,
                        updated_at=head.updated_at,
                        graph_count=len(document.graphs),
                        node_count=sum(
                            len(graph.document.nodes) for graph in document.graphs
                        ),
                        edge_count=sum(
                            len(graph.document.edges) for graph in document.graphs
                        ),
                    ),
                    location=self._store.workspace_locations[head.workspace_id],
                    folder=(
                        None
                        if folder is None
                        else ProjectBrowserFolder(id=folder.id, name=folder.name)
                    ),
                    archived_at=None
                    if organization is None
                    else organization.archived_at,
                    starred=False if state is None else state.starred,
                    last_opened_at=None if state is None else state.last_opened_at,
                    organization_updated_at=(
                        None if organization is None else organization.updated_at
                    ),
                    creator=(
                        None
                        if project.created_by_user_id is None or display_name is None
                        else ProjectBrowserCreator(
                            id=project.created_by_user_id,
                            display_name=display_name,
                        )
                    ),
                )
            )
        return items

    # --- Append-only checkpoints -------------------------------------------------

    @override
    async def add_checkpoint(self, checkpoint: ProjectCheckpoint) -> None:
        key = (checkpoint.workspace_id, checkpoint.project_id, checkpoint.revision)
        if key in self._store.project_checkpoints:
            raise ConcurrentWriteError(
                f"Project checkpoint already exists: {checkpoint.project_id}"
                f"/r{checkpoint.revision}"
            )
        self._store.project_checkpoints[key] = checkpoint

    @override
    async def get_checkpoint(
        self,
        workspace_id: UUID,
        project_id: UUID,
        revision: int,
    ) -> ProjectCheckpoint | None:
        return self._store.project_checkpoints.get((workspace_id, project_id, revision))

    @override
    async def list_checkpoints(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> list[ProjectCheckpoint]:
        return [
            checkpoint
            for (checkpoint_workspace, checkpoint_project, _), checkpoint in sorted(
                self._store.project_checkpoints.items(),
                key=lambda entry: entry[0][2],
            )
            if checkpoint_workspace == workspace_id and checkpoint_project == project_id
        ]

    # --- Filing: folders ---------------------------------------------------------

    def _folder_by_name(
        self, workspace_id: UUID, name: str, *, except_folder_id: UUID | None = None
    ) -> ProjectFolder | None:
        for folder in self._store.project_folders.values():
            if folder.workspace_id != workspace_id or folder.name != name:
                continue
            if except_folder_id is not None and folder.id == except_folder_id:
                continue
            return folder
        return None

    @override
    async def add_folder(self, folder: ProjectFolder) -> None:
        if self._folder_by_name(folder.workspace_id, folder.name) is not None:
            raise ProjectFolderNameConflictError(
                workspace_id=folder.workspace_id, name=folder.name
            )
        self._store.project_folders[folder.id] = replace(folder)

    @override
    async def get_folder(
        self, workspace_id: UUID, folder_id: UUID
    ) -> ProjectFolder | None:
        folder = self._store.project_folders.get(folder_id)
        if folder is None or folder.workspace_id != workspace_id:
            return None
        return replace(folder)

    @override
    async def get_folder_by_name(
        self, workspace_id: UUID, name: str
    ) -> ProjectFolder | None:
        folder = self._folder_by_name(workspace_id, name)
        return None if folder is None else replace(folder)

    @override
    async def list_folders(self, workspace_id: UUID) -> list[ProjectFolder]:
        folders = [
            replace(folder)
            for folder in self._store.project_folders.values()
            if folder.workspace_id == workspace_id
        ]
        folders.sort(key=lambda folder: (folder.name, str(folder.id)))
        return folders

    @override
    async def save_folder(self, folder: ProjectFolder) -> None:
        if (
            self._folder_by_name(
                folder.workspace_id, folder.name, except_folder_id=folder.id
            )
            is not None
        ):
            raise ProjectFolderNameConflictError(
                workspace_id=folder.workspace_id, name=folder.name
            )
        stored = await self.get_folder(folder.workspace_id, folder.id)
        if stored is None:
            return
        self._store.project_folders[folder.id] = replace(folder)

    @override
    async def unfile_projects_in_folder(
        self, workspace_id: UUID, folder_id: UUID
    ) -> None:
        for (
            organization_workspace,
            _,
        ), organization in self._store.project_organizations.items():
            if (
                organization_workspace == workspace_id
                and organization.folder_id == folder_id
            ):
                organization.assign_folder(None, updated_at=datetime.now(UTC))

    @override
    async def remove_folder(self, folder: ProjectFolder) -> None:
        stored = await self.get_folder(folder.workspace_id, folder.id)
        if stored is None:
            return
        _ = self._store.project_folders.pop(folder.id, None)

    # --- Filing: organization and per-user state ---------------------------------

    @override
    async def get_organization(
        self, *, workspace_id: UUID, project_id: UUID
    ) -> ProjectOrganization | None:
        organization = self._store.project_organizations.get((workspace_id, project_id))
        return None if organization is None else replace(organization)

    @override
    async def save_organization(self, organization: ProjectOrganization) -> None:
        self._store.project_organizations[
            (organization.workspace_id, organization.project_id)
        ] = replace(organization)

    @override
    async def get_user_state(
        self, *, workspace_id: UUID, project_id: UUID, user_id: UUID
    ) -> UserProjectState | None:
        state = self._store.user_project_states.get((workspace_id, project_id, user_id))
        return None if state is None else replace(state)

    @override
    async def save_user_state(self, state: UserProjectState) -> None:
        self._store.user_project_states[
            (state.workspace_id, state.project_id, state.user_id)
        ] = replace(state)

    @override
    async def titles_referencing_artifact(
        self, workspace_id: UUID, artifact_id: UUID
    ) -> dict[UUID, str]:
        # Like the SQL adapter, the identity is matched as text inside the
        # serialized document, and both the live head and every retained
        # checkpoint count: a restored checkpoint must not point at an artifact
        # that has been deleted.
        needle = str(artifact_id)
        referencing: set[UUID] = set()
        for (document_workspace, project_id), head in self._store.project_heads.items():
            if document_workspace == workspace_id and needle in str(head.document):
                referencing.add(project_id)
        for (
            document_workspace,
            project_id,
            _,
        ), checkpoint in self._store.project_checkpoints.items():
            if document_workspace == workspace_id and needle in str(
                checkpoint.document
            ):
                referencing.add(project_id)
        return {
            project_id: project.name
            for project_id, project in self._store.projects.items()
            if project.workspace_id == workspace_id and project_id in referencing
        }
