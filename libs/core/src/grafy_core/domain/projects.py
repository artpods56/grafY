"""The Project aggregate: identity, checkpoints, filing and browser reads (ADR 0020).

A Project is the Workspace-owned object that a collaboration room is opened on.
It holds named Graphs; its content is its ``ProjectDocument`` and the append-only
checkpoints of that document. Nothing here does I/O: these are the entities the
application layer loads and stores.

The Project itself carries no document and no revision counter. The head of the
collaborative sequence lives in ``grafy_core.domain.collaboration.ProjectHead``
and the durable revisions in ``ProjectCheckpoint``, so a read model never has to
agree with a counter this object does not own.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from grafy_core.domain.identity import WorkspaceKind
from grafy_core.kernel.project import ProjectDocument

PROJECT_NAME_MAX_LENGTH = 160


def _utc_now() -> datetime:
    return datetime.now(UTC)


def validated_project_name(value: str) -> str:
    """Strip and range-check a Project name, the one rule every name follows."""
    name = value.strip()
    if name == "":
        raise ValueError("Project name must not be blank")
    if len(name) > PROJECT_NAME_MAX_LENGTH:
        raise ValueError(
            f"Project name must be at most {PROJECT_NAME_MAX_LENGTH} characters"
        )
    return name


def _validated_folder_name(value: str) -> str:
    name = value.strip()
    if name == "":
        raise ValueError("Project folder name must not be blank")
    if len(name) > PROJECT_NAME_MAX_LENGTH:
        raise ValueError(
            f"Project folder name must be at most {PROJECT_NAME_MAX_LENGTH} characters"
        )
    return name


@dataclass
class Project:
    """A Project: who owns it and what it is called. Its content is checkpointed."""

    workspace_id: UUID
    name: str
    created_by_user_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.name = validated_project_name(self.name)
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Project timestamps must be timezone-aware")

    def rename(self, name: str, *, updated_at: datetime | None = None) -> None:
        replacement_time = updated_at or _utc_now()
        if replacement_time.tzinfo is None:
            raise ValueError("Project timestamps must be timezone-aware")
        self.name = validated_project_name(name)
        self.updated_at = replacement_time


@dataclass(frozen=True, slots=True)
class ProjectCheckpoint:
    """One immutable revision of a Project document."""

    workspace_id: UUID
    project_id: UUID
    revision: int
    name: str
    document: ProjectDocument
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validated_project_name(self.name))
        if self.revision < 1:
            raise ValueError("Project checkpoint revision must be at least 1")
        if self.created_at.tzinfo is None:
            raise ValueError("Project checkpoint timestamp must be timezone-aware")


@dataclass
class ProjectFolder:
    workspace_id: UUID
    name: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.name = _validated_folder_name(self.name)
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Project folder timestamps must be timezone-aware")

    def rename(self, name: str, *, updated_at: datetime | None = None) -> None:
        replacement_time = updated_at or _utc_now()
        if replacement_time.tzinfo is None:
            raise ValueError("Project folder timestamps must be timezone-aware")
        self.name = _validated_folder_name(name)
        self.updated_at = replacement_time


@dataclass
class UserProjectState:
    """One user's own view of one Project: star and last opened."""

    workspace_id: UUID
    project_id: UUID
    user_id: UUID
    starred: bool = False
    last_opened_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.last_opened_at is not None and self.last_opened_at.tzinfo is None:
            raise ValueError("Project last-opened timestamp must be timezone-aware")

    def set_starred(self, starred: bool) -> None:
        self.starred = starred

    def record_open(self, *, opened_at: datetime | None = None) -> None:
        opened_time = opened_at or _utc_now()
        if opened_time.tzinfo is None:
            raise ValueError("Project last-opened timestamp must be timezone-aware")
        if self.last_opened_at is None or opened_time > self.last_opened_at:
            self.last_opened_at = opened_time


@dataclass
class ProjectOrganization:
    """Where a Project is filed in a Workspace, and whether it is archived."""

    workspace_id: UUID
    project_id: UUID
    folder_id: UUID | None = None
    archived_at: datetime | None = None
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None:
            raise ValueError("Project organization timestamp must be timezone-aware")
        if self.archived_at is not None and self.archived_at.tzinfo is None:
            raise ValueError("Project archive timestamp must be timezone-aware")

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def assign_folder(
        self,
        folder_id: UUID | None,
        *,
        updated_at: datetime | None = None,
    ) -> None:
        replacement_time = updated_at or _utc_now()
        if replacement_time.tzinfo is None:
            raise ValueError("Project organization timestamp must be timezone-aware")
        self.folder_id = folder_id
        self.updated_at = replacement_time

    def archive(self, *, archived_at: datetime | None = None) -> None:
        archive_time = archived_at or _utc_now()
        if archive_time.tzinfo is None:
            raise ValueError("Project archive timestamp must be timezone-aware")
        if self.archived_at is None:
            self.archived_at = archive_time
            self.updated_at = archive_time

    def restore(self, *, restored_at: datetime | None = None) -> None:
        restore_time = restored_at or _utc_now()
        if restore_time.tzinfo is None:
            raise ValueError("Project restore timestamp must be timezone-aware")
        if self.archived_at is not None:
            self.archived_at = None
            self.updated_at = restore_time


@dataclass(frozen=True, slots=True)
class ProjectBrowserLocation:
    id: UUID
    slug: str
    name: str
    kind: WorkspaceKind


@dataclass(frozen=True, slots=True)
class ProjectBrowserFolder:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class ProjectBrowserCreator:
    id: UUID
    display_name: str | None


@dataclass(frozen=True, slots=True)
class ProjectBrowserDraft:
    """The head of a Project as the browser list shows it."""

    name: str
    head_sequence: int
    checkpoint_sequence: int
    checkpoint_revision: int
    updated_at: datetime
    graph_count: int
    node_count: int
    edge_count: int


@dataclass(frozen=True, slots=True)
class ProjectBrowserItem:
    id: UUID
    draft: ProjectBrowserDraft
    location: ProjectBrowserLocation
    folder: ProjectBrowserFolder | None
    archived_at: datetime | None
    starred: bool
    last_opened_at: datetime | None
    organization_updated_at: datetime | None
    creator: ProjectBrowserCreator | None

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


__all__ = [
    "PROJECT_NAME_MAX_LENGTH",
    "Project",
    "ProjectBrowserCreator",
    "ProjectBrowserDraft",
    "ProjectBrowserFolder",
    "ProjectBrowserItem",
    "ProjectBrowserLocation",
    "ProjectCheckpoint",
    "ProjectFolder",
    "ProjectOrganization",
    "UserProjectState",
    "validated_project_name",
]
