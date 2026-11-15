from collections.abc import Collection
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Self
from uuid import UUID

if TYPE_CHECKING:
    from grafy_core.domain.uploads import Upload

from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
)
from grafy_core.domain.agent_turns import AgentTurn
from grafy_core.domain.collaboration import (
    ProjectCheckpointMapping,
    ProjectCommandReceipt,
    ProjectHead,
)
from grafy_core.domain.library import LibraryFolder
from grafy_core.domain.projects import (
    Project,
    ProjectBrowserLocation,
    ProjectCheckpoint,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.domain.runs import Run
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import InstancePointer, StoredResult


def _clone[T](value: T) -> T:
    return deepcopy(value)


def _newest_first[T](
    rows: Collection[T], *, stamp: Callable[[T], datetime], ident: Callable[[T], UUID]
) -> list[T]:
    """Order like ``ORDER BY <stamp> DESC, id ASC``.

    Python's sort is stable, so ordering by id first and then by the timestamp
    descending leaves ids ascending inside one timestamp.
    """

    return sorted(
        sorted(rows, key=lambda row: str(ident(row))), key=stamp, reverse=True
    )


@dataclass(slots=True)
class InMemoryDataStore:
    artifacts: dict[UUID, ArtifactObject] = field(
        default_factory=dict[UUID, ArtifactObject]
    )
    uploads: dict[tuple[UUID, UUID], "Upload"] = field(
        default_factory=dict[tuple[UUID, UUID], "Upload"]
    )
    library_folders: dict[UUID, LibraryFolder] = field(
        default_factory=dict[UUID, LibraryFolder]
    )
    # (workspace_id, artifact_id) → folder_id. An artifact with no key sits at
    # the Library root, exactly like the SQL placement table.
    library_placements: dict[tuple[UUID, UUID], UUID] = field(
        default_factory=dict[tuple[UUID, UUID], UUID]
    )
    projects: dict[UUID, Project] = field(default_factory=dict[UUID, Project])
    # (workspace_id, project_id, revision). The composite key is the append-only
    # guard: a repeated revision is a lost race, never an update.
    project_checkpoints: dict[tuple[UUID, UUID, int], ProjectCheckpoint] = field(
        default_factory=dict[tuple[UUID, UUID, int], ProjectCheckpoint]
    )
    project_folders: dict[UUID, ProjectFolder] = field(
        default_factory=dict[UUID, ProjectFolder]
    )
    project_organizations: dict[tuple[UUID, UUID], ProjectOrganization] = field(
        default_factory=dict[tuple[UUID, UUID], ProjectOrganization]
    )
    user_project_states: dict[tuple[UUID, UUID, UUID], UserProjectState] = field(
        default_factory=dict[tuple[UUID, UUID, UUID], UserProjectState]
    )
    project_heads: dict[tuple[UUID, UUID], ProjectHead] = field(
        default_factory=dict[tuple[UUID, UUID], ProjectHead]
    )
    project_command_receipts: dict[tuple[UUID, UUID, UUID], ProjectCommandReceipt] = (
        field(default_factory=dict[tuple[UUID, UUID, UUID], ProjectCommandReceipt])
    )
    project_checkpoint_mappings: dict[
        tuple[UUID, UUID, UUID, int], ProjectCheckpointMapping
    ] = field(
        default_factory=dict[tuple[UUID, UUID, UUID, int], ProjectCheckpointMapping]
    )
    runs: dict[UUID, Run] = field(default_factory=dict[UUID, Run])
    # (workspace_id, conversation_id). The conversation row carries the sequence its
    # next event takes, exactly like the SQL table, so append races the same way here.
    agent_conversations: dict[tuple[UUID, UUID], AgentConversation] = field(
        default_factory=dict[tuple[UUID, UUID], AgentConversation]
    )
    # (workspace_id, conversation_id, sequence). An event is never edited in place and
    # never evicted: the sequence is the address of history.
    agent_conversation_events: dict[tuple[UUID, UUID, int], AgentConversationEvent] = (
        field(default_factory=dict[tuple[UUID, UUID, int], AgentConversationEvent])
    )
    # (turn.id). A send's receipt: keyed for a client turn id by the repository, which is
    # where "one turn at a time per conversation" and "this send was already admitted" are
    # decided, exactly as the partial unique index decides them in SQL.
    agent_turns: dict[UUID, AgentTurn] = field(default_factory=dict[UUID, AgentTurn])
    # (workspace_id, fingerprint). Two Workspaces never share a fingerprint's result.
    node_results: dict[tuple[UUID, str], StoredResult] = field(
        default_factory=dict[tuple[UUID, str], StoredResult]
    )
    pointers: dict[tuple[UUID, InstanceKey], InstancePointer] = field(
        default_factory=dict[tuple[UUID, InstanceKey], InstancePointer]
    )
    # The browser read joins identity in: which Workspaces a user can see, what
    # each is called, and what its users are called. This store holds no User or
    # Workspace aggregate, so a test states those three things outright. A user
    # with no membership entry sees no Projects, which is what a non-member sees
    # through the SQL adapter.
    workspace_locations: dict[UUID, ProjectBrowserLocation] = field(
        default_factory=dict[UUID, ProjectBrowserLocation]
    )
    workspace_members: dict[UUID, set[UUID]] = field(
        default_factory=dict[UUID, set[UUID]]
    )
    user_display_names: dict[UUID, str] = field(default_factory=dict[UUID, str])

    def clone(self) -> Self:
        return _clone(self)

    def replace_with(self, other: Self) -> None:
        self.artifacts = _clone(other.artifacts)
        self.uploads = _clone(other.uploads)
        self.library_folders = _clone(other.library_folders)
        self.library_placements = _clone(other.library_placements)
        self.projects = _clone(other.projects)
        self.project_checkpoints = _clone(other.project_checkpoints)
        self.project_folders = _clone(other.project_folders)
        self.project_organizations = _clone(other.project_organizations)
        self.user_project_states = _clone(other.user_project_states)
        self.project_heads = _clone(other.project_heads)
        self.project_command_receipts = _clone(other.project_command_receipts)
        self.project_checkpoint_mappings = _clone(other.project_checkpoint_mappings)
        self.runs = _clone(other.runs)
        self.agent_conversations = _clone(other.agent_conversations)
        self.agent_conversation_events = _clone(other.agent_conversation_events)
        self.agent_turns = _clone(other.agent_turns)
        self.node_results = _clone(other.node_results)
        self.pointers = _clone(other.pointers)
        self.workspace_locations = _clone(other.workspace_locations)
        self.workspace_members = _clone(other.workspace_members)
        self.user_display_names = _clone(other.user_display_names)
