from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from grafy_core.domain.projects import (
    Project,
    ProjectBrowserItem,
    ProjectCheckpoint,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.ports.transactions import TransactionPort

if TYPE_CHECKING:
    from grafy_core.ports.identity import (
        IdentityRepositoryPort,
        SecurityAuditRepositoryPort,
    )
    from grafy_core.ports.node_secrets import NodeSecretRepositoryPort


class ProjectRepositoryPort(Protocol):
    """Project identity, append-only checkpoints, folders, organization, per-user state.

    Every method is scoped by Workspace: a Project of another Workspace is
    indistinguishable from a missing one.
    """

    async def add(self, project: Project) -> None: ...

    async def get(self, workspace_id: UUID, project_id: UUID) -> Project | None: ...

    async def save(self, project: Project) -> None:
        """Persist name and ``updated_at`` of an existing Project."""
        ...

    async def remove(self, workspace_id: UUID, project: Project) -> None: ...

    async def list(self, workspace_id: UUID) -> list[Project]: ...

    async def list_accessible(
        self,
        user_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> list[ProjectBrowserItem]: ...

    async def add_checkpoint(self, checkpoint: ProjectCheckpoint) -> None:
        """Append. A second checkpoint with the same revision raises ``ConcurrentWriteError``."""
        ...

    async def get_checkpoint(
        self,
        workspace_id: UUID,
        project_id: UUID,
        revision: int,
    ) -> ProjectCheckpoint | None: ...

    async def list_checkpoints(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> list[ProjectCheckpoint]:
        """Oldest first."""
        ...

    async def add_folder(self, folder: ProjectFolder) -> None: ...

    async def get_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> ProjectFolder | None: ...

    async def get_folder_by_name(
        self,
        workspace_id: UUID,
        name: str,
    ) -> ProjectFolder | None: ...

    async def list_folders(self, workspace_id: UUID) -> list[ProjectFolder]: ...

    async def save_folder(self, folder: ProjectFolder) -> None: ...

    async def unfile_projects_in_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> None: ...

    async def remove_folder(self, folder: ProjectFolder) -> None: ...

    async def get_organization(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectOrganization | None: ...

    async def save_organization(self, organization: ProjectOrganization) -> None: ...

    async def get_user_state(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> UserProjectState | None: ...

    async def save_user_state(self, state: UserProjectState) -> None: ...

    async def titles_referencing_artifact(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> dict[UUID, str]:
        """Map each Project holding ``artifact_id`` to its name.

        The head and every retained checkpoint count as a reference, so a
        restored checkpoint cannot point at an artifact that has been deleted.
        """
        ...


class ProjectUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def projects(self) -> ProjectRepositoryPort: ...

    @property
    def node_secrets(self) -> "NodeSecretRepositoryPort": ...

    @property
    def identity(self) -> "IdentityRepositoryPort": ...

    @property
    def security_audit(self) -> "SecurityAuditRepositoryPort": ...
