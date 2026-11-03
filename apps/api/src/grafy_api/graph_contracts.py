from datetime import datetime
from typing import ClassVar
from uuid import UUID

from grafy_core.domain.collaboration import (
    CollaborativeGraphHead,
    CommandReceiptOutcome,
    GraphCommand,
    GraphCommandReceipt,
)
from grafy_core.domain.identity import WorkspaceKind
from grafy_core.domain.graph_documents import (
    GraphBrowserItem,
    GraphFolder,
    GraphOrganization,
    SavedGraph,
    GraphDocument,
    UserGraphState,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class SavedGraphApiModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )


class SavedGraphWriteRequest(SavedGraphApiModel):
    name: str = Field(min_length=1, max_length=160)
    document: GraphDocument

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CreateSavedGraphRequest(SavedGraphWriteRequest):
    pass


class UpdateSavedGraphRequest(SavedGraphWriteRequest):
    expected_revision: int = Field(ge=1)


class SavedGraphResponse(SavedGraphApiModel):
    id: UUID
    name: str
    revision: int
    created_at: datetime
    updated_at: datetime
    document: GraphDocument

    @classmethod
    def from_graph(cls, graph: SavedGraph) -> "SavedGraphResponse":
        return cls(
            id=graph.id,
            name=graph.name,
            revision=graph.revision,
            created_at=graph.created_at,
            updated_at=graph.updated_at,
            document=graph.document,
        )


def graph_browser_updated_at(item: GraphBrowserItem) -> datetime:
    """Freshness shared by every graph discovery surface for one graph."""

    updated_at = item.draft.updated_at
    if (
        item.organization_updated_at is not None
        and item.organization_updated_at > updated_at
    ):
        return item.organization_updated_at
    return updated_at


class SavedGraphSummaryResponse(SavedGraphApiModel):
    """Authoritative summary shared by every graph discovery surface.

    Counts and ``updated_at`` describe the collaborative draft head (what the
    canvas shows). ``revision`` is the durable checkpoint revision used by
    lifecycle writes, and ``draft_pending`` labels a head that is ahead of that
    checkpoint. Located lists reuse this model and add workspace metadata.
    """

    id: UUID
    name: str
    revision: int
    node_count: int
    edge_count: int
    updated_at: datetime
    draft_pending: bool

    @staticmethod
    def from_browser_item(item: GraphBrowserItem) -> "SavedGraphSummaryResponse":
        return SavedGraphSummaryResponse(
            id=item.id,
            name=item.draft.name,
            revision=item.draft.checkpoint_revision,
            node_count=item.draft.node_count,
            edge_count=item.draft.edge_count,
            updated_at=graph_browser_updated_at(item),
            draft_pending=item.draft.head_sequence > item.draft.checkpoint_sequence,
        )


class SavedGraphListResponse(SavedGraphApiModel):
    graphs: list[SavedGraphSummaryResponse]

    @classmethod
    def from_items(cls, items: list[GraphBrowserItem]) -> "SavedGraphListResponse":
        return cls(
            graphs=[SavedGraphSummaryResponse.from_browser_item(item) for item in items]
        )


class GraphFolderWriteRequest(SavedGraphApiModel):
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class GraphFolderResponse(SavedGraphApiModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_folder(cls, folder: GraphFolder) -> "GraphFolderResponse":
        return cls(
            id=folder.id,
            name=folder.name,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )


class GraphFolderListResponse(SavedGraphApiModel):
    folders: list[GraphFolderResponse]

    @classmethod
    def from_folders(cls, folders: list[GraphFolder]) -> "GraphFolderListResponse":
        return cls(
            folders=[GraphFolderResponse.from_folder(folder) for folder in folders]
        )


class AssignGraphFolderRequest(SavedGraphApiModel):
    folder_id: UUID | None


class GraphOrganizationResponse(SavedGraphApiModel):
    folder_id: UUID | None
    archived: bool
    archived_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_organization(
        cls,
        organization: GraphOrganization,
    ) -> "GraphOrganizationResponse":
        return cls(
            folder_id=organization.folder_id,
            archived=organization.is_archived,
            archived_at=organization.archived_at,
            updated_at=organization.updated_at,
        )


class UserGraphStateResponse(SavedGraphApiModel):
    starred: bool
    last_opened_at: datetime | None

    @classmethod
    def from_state(cls, state: UserGraphState) -> "UserGraphStateResponse":
        return cls(
            starred=state.starred,
            last_opened_at=state.last_opened_at,
        )


class GraphBrowserLocationResponse(SavedGraphApiModel):
    id: UUID
    slug: str
    name: str
    kind: WorkspaceKind


class GraphBrowserFolderResponse(SavedGraphApiModel):
    id: UUID
    name: str


class GraphBrowserCreatorResponse(SavedGraphApiModel):
    id: UUID
    display_name: str | None


class GraphBrowserItemResponse(SavedGraphSummaryResponse):
    """The shared discovery summary plus workspace location and per-user state."""

    location: GraphBrowserLocationResponse
    folder: GraphBrowserFolderResponse | None
    archived: bool
    archived_at: datetime | None
    starred: bool
    last_opened_at: datetime | None
    creator: GraphBrowserCreatorResponse | None

    @classmethod
    def from_item(cls, item: GraphBrowserItem) -> "GraphBrowserItemResponse":
        summary = SavedGraphSummaryResponse.from_browser_item(item)
        return cls(
            **summary.model_dump(),
            location=GraphBrowserLocationResponse(
                id=item.location.id,
                slug=item.location.slug,
                name=item.location.name,
                kind=item.location.kind,
            ),
            folder=(
                None
                if item.folder is None
                else GraphBrowserFolderResponse(
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
                else GraphBrowserCreatorResponse(
                    id=item.creator.id,
                    display_name=item.creator.display_name,
                )
            ),
        )


class GraphBrowserListResponse(SavedGraphApiModel):
    graphs: list[GraphBrowserItemResponse]

    @classmethod
    def from_items(cls, items: list[GraphBrowserItem]) -> "GraphBrowserListResponse":
        return cls(graphs=[GraphBrowserItemResponse.from_item(item) for item in items])


class CollaborativeHeadResponse(SavedGraphApiModel):
    """Collaboration metadata paired with the canonical saved graph document."""

    graph_id: UUID
    room_epoch: UUID
    collaboration_sequence: int
    checkpoint_sequence: int
    checkpoint_revision: int
    name: str
    updated_at: datetime
    document: GraphDocument

    @classmethod
    def from_head(cls, head: CollaborativeGraphHead) -> "CollaborativeHeadResponse":
        return cls.model_validate(head, from_attributes=True)


class SubmitGraphCommandRequest(SavedGraphApiModel):
    command_id: UUID
    room_epoch: UUID
    observed_sequence: int = Field(ge=0)
    command: GraphCommand


class GraphCommandReceiptResponse(SavedGraphApiModel):
    command_id: UUID
    outcome: CommandReceiptOutcome
    accepted_sequence: int
    room_epoch: UUID
    deduplicated: bool

    @classmethod
    def from_receipt(
        cls,
        receipt: GraphCommandReceipt,
    ) -> "GraphCommandReceiptResponse":
        return cls(
            command_id=receipt.command_id,
            outcome=receipt.outcome,
            accepted_sequence=receipt.accepted_sequence,
            room_epoch=receipt.room_epoch,
            deduplicated=receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY,
        )


class SubmitGraphCommandResponse(SavedGraphApiModel):
    head: CollaborativeHeadResponse
    receipt: GraphCommandReceiptResponse


class CheckpointGraphRequest(SavedGraphApiModel):
    expected_room_epoch: UUID
    expected_sequence: int = Field(ge=0)


class CheckpointGraphResponse(SavedGraphApiModel):
    head: CollaborativeHeadResponse
    saved_revision: int


class CopyExactHeadRequest(SavedGraphApiModel):
    source_workspace_id: UUID
    source_graph_id: UUID
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
