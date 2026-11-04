from datetime import datetime
from typing import ClassVar
from uuid import UUID

from grafy_core.domain.collaboration import (
    ProjectHead,
    CommandReceiptOutcome,
    ProjectCommand,
    ProjectCommandReceipt,
)
from grafy_core.domain.identity import WorkspaceKind
from grafy_core.domain.projects import (
    Project,
    ProjectBrowserItem,
    ProjectCheckpoint,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.kernel.project import ProjectDocument
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ProjectApiModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )


class CreateProjectRequest(ProjectApiModel):
    name: str = Field(min_length=1, max_length=160)
    graph_id: str = Field(default="main", min_length=1)
    graph_name: str = Field(default="Main", min_length=1)
    project_id: UUID | None = None
    command_id: UUID | None = None

    @field_validator("name", "graph_name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_replay_pair(self) -> "CreateProjectRequest":
        """A replayable creation needs the id a retry would find the receipt under."""

        if self.command_id is not None and self.project_id is None:
            raise ValueError(
                "command_id is only accepted together with an explicit project_id"
            )
        return self


class ProjectResponse(ProjectApiModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_project(cls, project: Project) -> "ProjectResponse":
        return cls.model_validate(project, from_attributes=True)


def project_browser_updated_at(item: ProjectBrowserItem) -> datetime:
    """Freshness shared by every graph discovery surface for one graph."""

    updated_at = item.draft.updated_at
    if (
        item.organization_updated_at is not None
        and item.organization_updated_at > updated_at
    ):
        return item.organization_updated_at
    return updated_at


class ProjectSummaryResponse(ProjectApiModel):
    """Authoritative summary shared by every graph discovery surface.

    Counts and ``updated_at`` describe the collaborative draft head (what the
    canvas shows). ``revision`` is the durable checkpoint revision used by
    lifecycle writes, and ``draft_pending`` labels a head that is ahead of that
    checkpoint. Located lists reuse this model and add workspace metadata.
    """

    id: UUID
    name: str
    revision: int
    graph_count: int
    node_count: int
    edge_count: int
    updated_at: datetime
    draft_pending: bool

    @staticmethod
    def from_browser_item(item: ProjectBrowserItem) -> "ProjectSummaryResponse":
        return ProjectSummaryResponse(
            id=item.id,
            name=item.draft.name,
            revision=item.draft.checkpoint_revision,
            graph_count=item.draft.graph_count,
            node_count=item.draft.node_count,
            edge_count=item.draft.edge_count,
            updated_at=project_browser_updated_at(item),
            draft_pending=item.draft.head_sequence > item.draft.checkpoint_sequence,
        )


class ProjectListResponse(ProjectApiModel):
    projects: list[ProjectSummaryResponse]

    @classmethod
    def from_items(cls, items: list[ProjectBrowserItem]) -> "ProjectListResponse":
        return cls(
            projects=[ProjectSummaryResponse.from_browser_item(item) for item in items]
        )


class ProjectFolderWriteRequest(ProjectApiModel):
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ProjectFolderResponse(ProjectApiModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_folder(cls, folder: ProjectFolder) -> "ProjectFolderResponse":
        return cls(
            id=folder.id,
            name=folder.name,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )


class ProjectFolderListResponse(ProjectApiModel):
    folders: list[ProjectFolderResponse]

    @classmethod
    def from_folders(cls, folders: list[ProjectFolder]) -> "ProjectFolderListResponse":
        return cls(
            folders=[ProjectFolderResponse.from_folder(folder) for folder in folders]
        )


class AssignProjectFolderRequest(ProjectApiModel):
    folder_id: UUID | None


class ProjectOrganizationResponse(ProjectApiModel):
    folder_id: UUID | None
    archived: bool
    archived_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_organization(
        cls,
        organization: ProjectOrganization,
    ) -> "ProjectOrganizationResponse":
        return cls(
            folder_id=organization.folder_id,
            archived=organization.is_archived,
            archived_at=organization.archived_at,
            updated_at=organization.updated_at,
        )


class UserProjectStateResponse(ProjectApiModel):
    starred: bool
    last_opened_at: datetime | None

    @classmethod
    def from_state(cls, state: UserProjectState) -> "UserProjectStateResponse":
        return cls(
            starred=state.starred,
            last_opened_at=state.last_opened_at,
        )


class ProjectBrowserLocationResponse(ProjectApiModel):
    id: UUID
    slug: str
    name: str
    kind: WorkspaceKind


class ProjectBrowserFolderResponse(ProjectApiModel):
    id: UUID
    name: str


class ProjectBrowserCreatorResponse(ProjectApiModel):
    id: UUID
    display_name: str | None


class ProjectBrowserItemResponse(ProjectSummaryResponse):
    """The shared discovery summary plus workspace location and per-user state."""

    location: ProjectBrowserLocationResponse
    folder: ProjectBrowserFolderResponse | None
    archived: bool
    archived_at: datetime | None
    starred: bool
    last_opened_at: datetime | None
    creator: ProjectBrowserCreatorResponse | None

    @classmethod
    def from_item(cls, item: ProjectBrowserItem) -> "ProjectBrowserItemResponse":
        summary = ProjectSummaryResponse.from_browser_item(item)
        return cls(
            **summary.model_dump(),
            location=ProjectBrowserLocationResponse(
                id=item.location.id,
                slug=item.location.slug,
                name=item.location.name,
                kind=item.location.kind,
            ),
            folder=(
                None
                if item.folder is None
                else ProjectBrowserFolderResponse(
                    id=item.folder.id,
                    name=item.folder.name,
                )
            ),
            archived=item.is_archived,
            archived_at=item.archived_at,
            starred=item.starred,
            last_opened_at=item.last_opened_at,
            creator=(
                None
                if item.creator is None
                else ProjectBrowserCreatorResponse(
                    id=item.creator.id,
                    display_name=item.creator.display_name,
                )
            ),
        )


class ProjectBrowserListResponse(ProjectApiModel):
    projects: list[ProjectBrowserItemResponse]

    @classmethod
    def from_items(
        cls, items: list[ProjectBrowserItem]
    ) -> "ProjectBrowserListResponse":
        return cls(
            projects=[ProjectBrowserItemResponse.from_item(item) for item in items]
        )


class ProjectHeadResponse(ProjectApiModel):
    """Collaboration metadata paired with the canonical Project document."""

    project_id: UUID
    room_epoch: UUID
    collaboration_sequence: int
    checkpoint_sequence: int
    checkpoint_revision: int
    name: str
    updated_at: datetime
    document: ProjectDocument

    @classmethod
    def from_head(cls, head: ProjectHead) -> "ProjectHeadResponse":
        return cls.model_validate(head, from_attributes=True)


class SubmitProjectCommandRequest(ProjectApiModel):
    command_id: UUID
    room_epoch: UUID
    observed_sequence: int = Field(ge=0)
    commands: tuple[ProjectCommand, ...] = Field(min_length=1)


class ProjectCommandReceiptResponse(ProjectApiModel):
    command_id: UUID
    outcome: CommandReceiptOutcome
    accepted_sequence: int
    room_epoch: UUID
    deduplicated: bool

    @classmethod
    def from_receipt(
        cls,
        receipt: ProjectCommandReceipt,
    ) -> "ProjectCommandReceiptResponse":
        return cls(
            command_id=receipt.command_id,
            outcome=receipt.outcome,
            accepted_sequence=receipt.accepted_sequence,
            room_epoch=receipt.room_epoch,
            deduplicated=receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY,
        )


class SubmitProjectCommandResponse(ProjectApiModel):
    head: ProjectHeadResponse
    receipt: ProjectCommandReceiptResponse


class CheckpointProjectRequest(ProjectApiModel):
    expected_room_epoch: UUID
    expected_sequence: int = Field(ge=0)


class CheckpointProjectResponse(ProjectApiModel):
    head: ProjectHeadResponse
    checkpoint_revision: int


class ProjectCheckpointSummaryResponse(ProjectApiModel):
    """One retained checkpoint without its document."""

    revision: int
    name: str
    created_at: datetime

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: ProjectCheckpoint,
    ) -> "ProjectCheckpointSummaryResponse":
        return cls(
            revision=checkpoint.revision,
            name=checkpoint.name,
            created_at=checkpoint.created_at,
        )


class ProjectCheckpointListResponse(ProjectApiModel):
    checkpoints: list[ProjectCheckpointSummaryResponse]

    @classmethod
    def from_checkpoints(
        cls, checkpoints: list[ProjectCheckpoint]
    ) -> "ProjectCheckpointListResponse":
        return cls(
            checkpoints=[
                ProjectCheckpointSummaryResponse.from_checkpoint(checkpoint)
                for checkpoint in checkpoints
            ]
        )


class ProjectCheckpointResponse(ProjectCheckpointSummaryResponse):
    """One retained checkpoint with the exact document it froze."""

    document: ProjectDocument

    @classmethod
    def from_checkpoint(  # type: ignore[override]
        cls,
        checkpoint: ProjectCheckpoint,
    ) -> "ProjectCheckpointResponse":
        return cls(
            revision=checkpoint.revision,
            name=checkpoint.name,
            created_at=checkpoint.created_at,
            document=checkpoint.document,
        )


class CopyExactHeadRequest(ProjectApiModel):
    source_workspace_id: UUID
    source_project_id: UUID
    project_id: UUID
    expected_room_epoch: UUID
    expected_sequence: int = Field(ge=0)
    command_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
