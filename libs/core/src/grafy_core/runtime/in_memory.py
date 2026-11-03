"""Dictionary-backed adapters for the single-process workbench and the tests.

The contracts these classes keep are the ones the SQL adapters keep, and they are
what makes them usable as stand-ins:

* **Task isolation.** One unit of work is entered by one task at a time; a nested
  entry fails rather than sharing a transaction.
* **Clone in, copy out.** A transaction works on a deep clone of the store, and
  entities are cloned again on the way in and out, so a mutated domain object never
  writes itself into committed state behind the caller's back.
* **Rollback.** A commit publishes the working clone; a rollback, or any exception
  out of ``async with``, throws it away.
* **Workspace scoping.** Every read carries ``workspace_id``, so a row of another
  Workspace is indistinguishable from one that was never there.

Where the SQL adapter turns a primary-key violation into ``ConcurrentWriteError``
(an appended checkpoint revision, a command receipt, a checkpoint mapping) this one
raises the same error on the same key. What it cannot imitate is a real row lock:
``lock_head`` is an ordinary read, and the unit of work's transaction lock is what
serialises writers here.
"""

from asyncio import Lock
from collections.abc import Collection, Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType, TracebackType
from typing import (
    TYPE_CHECKING,
    Callable,
    Self,
    final,
    override,
)
from uuid import UUID

if TYPE_CHECKING:
    from grafy_core.domain.artifact_outputs import ArtifactOutputValue
    from grafy_core.domain.uploads import Upload
    from grafy_core.ports.uploads import UploadRepositoryPort

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
)
from grafy_core.domain.collaboration import (
    ProjectCheckpointMapping,
    ProjectCommandReceipt,
    ProjectHead,
)
from grafy_core.domain.errors import (
    ConcurrentWriteError,
    LibraryFolderNameConflictError,
    ObjectAlreadyExistsError,
    ProjectFolderNameConflictError,
)
from grafy_core.domain.library import LibraryFolder
from grafy_core.domain.projects import (
    Project,
    ProjectBrowserCreator,
    ProjectBrowserDraft,
    ProjectBrowserFolder,
    ProjectBrowserItem,
    ProjectBrowserLocation,
    ProjectCheckpoint,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.domain.runs import Run, RunStatus
from grafy_core.domain.uploads import UploadStatus
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import (
    FailureRecord,
    InstancePointer,
    StoredResult,
)
from grafy_core.ports.agent_conversations import (
    AgentConversationAppendError,
    AgentConversationRepositoryPort,
)
from grafy_core.ports.artifacts import ArtifactRepositoryPort, UnitOfWorkPort
from grafy_core.ports.collaboration import CollaborationRepositoryPort
from grafy_core.ports.library_folders import LibraryFolderRepositoryPort
from grafy_core.ports.projects import ProjectRepositoryPort
from grafy_core.ports.runs import ResultStoreRepositoryPort, RunRepositoryPort


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
    agent_conversation_events: dict[
        tuple[UUID, UUID, int], AgentConversationEvent
    ] = field(default_factory=dict[tuple[UUID, UUID, int], AgentConversationEvent])
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
        self.node_results = _clone(other.node_results)
        self.pointers = _clone(other.pointers)
        self.workspace_locations = _clone(other.workspace_locations)
        self.workspace_members = _clone(other.workspace_members)
        self.user_display_names = _clone(other.user_display_names)


def _stored_outputs(
    outputs: Mapping[str, ArtifactOutputValue],
) -> dict[str, ArtifactOutputValue]:
    return {port: value.model_copy(deep=True) for port, value in outputs.items()}


def _result_view(result: StoredResult) -> StoredResult:
    """Hand out a result that cannot be edited in place.

    The stored row keeps a plain dict because a mapping proxy cannot be
    deep-copied, and the store clones itself at every transaction boundary.
    """

    return StoredResult(
        fingerprint=result.fingerprint,
        outputs=MappingProxyType(dict(result.outputs)),
        created_at=result.created_at,
    )


def _outputs_reference(
    outputs: Mapping[str, ArtifactOutputValue], artifact_id: UUID
) -> bool:
    """Whether a stored output names ``artifact_id`` as content.

    Only the typed refs count: an id that appears in free metadata text is not a
    reference, exactly as the SQL adapter decides.
    """

    for value in outputs.values():
        if isinstance(value, ArtifactRefSequence):
            if any(ref.artifact_id == artifact_id for ref in value.item_refs):
                return True
        elif isinstance(value, ArtifactRef) and value.artifact_id == artifact_id:
            return True
    return False


@final
class InMemoryArtifactRepository(ArtifactRepositoryPort):
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add(self, artifact: ArtifactObject) -> None:
        if artifact.id in self._store.artifacts:
            raise ObjectAlreadyExistsError(f"Artifact already exists: {artifact.id}")
        self._store.artifacts[artifact.id] = artifact

    @override
    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        artifact = self._store.artifacts.get(artifact_id)
        if artifact is None or artifact.workspace_id != workspace_id:
            return None
        return artifact

    @override
    async def get_many(
        self,
        workspace_id: UUID,
        artifact_ids: Collection[UUID],
    ) -> dict[UUID, ArtifactObject]:
        return {
            artifact_id: artifact
            for artifact_id in artifact_ids
            if (artifact := self._store.artifacts.get(artifact_id)) is not None
            and artifact.workspace_id == workspace_id
        }

    @override
    async def remove(self, workspace_id: UUID, artifact: ArtifactObject) -> None:
        if artifact.workspace_id != workspace_id:
            return
        stored = self._store.artifacts.get(artifact.id)
        if stored is not None and stored.workspace_id == workspace_id:
            self._store.artifacts.pop(artifact.id, None)

    @override
    async def list_by_type(
        self,
        workspace_id: UUID,
        key: ArtifactTypeKey,
    ) -> list[ArtifactObject]:
        return [
            artifact
            for artifact in self._store.artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.artifact_type == key.id
            and artifact.schema_version == key.schema_version
        ]

    @override
    async def list_library(self, workspace_id: UUID) -> list[ArtifactObject]:
        return [
            artifact
            for artifact in self._store.artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.library_provenance is not None
        ]

    @override
    async def count_artifacts_sharing_object(
        self,
        workspace_id: UUID,
        *,
        bucket: str,
        object_key: str,
        except_artifact_id: UUID,
    ) -> int:
        return sum(
            1
            for artifact in self._store.artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.id != except_artifact_id
            and artifact.bucket == bucket
            and artifact.object_key == object_key
        )


@final
class InMemoryLibraryFolderRepository(LibraryFolderRepositoryPort):
    """The Library folder tree held in the shared in-memory store.

    Folders are handed out as copies and written back whole, which is what the
    SQL repository does with its detached dataclass. Placement rows cascade away
    with their artifact in SQL through a foreign key; nothing here reaches into
    the artifact repository to imitate that.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    def _find_sibling(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        name_key: str,
        *,
        except_folder_id: UUID | None = None,
    ) -> LibraryFolder | None:
        for folder in self._store.library_folders.values():
            if folder.workspace_id != workspace_id:
                continue
            if folder.parent_id != parent_id or folder.name_key != name_key:
                continue
            if except_folder_id is not None and folder.id == except_folder_id:
                continue
            return folder
        return None

    @override
    async def add(self, folder: LibraryFolder) -> None:
        if (
            self._find_sibling(
                folder.workspace_id,
                folder.parent_id,
                folder.name_key,
            )
            is not None
        ):
            raise LibraryFolderNameConflictError(
                workspace_id=folder.workspace_id,
                parent_id=folder.parent_id,
                name=folder.name,
            )
        self._store.library_folders[folder.id] = replace(folder)

    @override
    async def get(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> LibraryFolder | None:
        folder = self._store.library_folders.get(folder_id)
        if folder is None or folder.workspace_id != workspace_id:
            return None
        return replace(folder)

    @override
    async def get_by_name(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        name_key: str,
    ) -> LibraryFolder | None:
        folder = self._find_sibling(workspace_id, parent_id, name_key)
        return None if folder is None else replace(folder)

    @override
    async def list(self, workspace_id: UUID) -> list[LibraryFolder]:
        folders = [
            replace(folder)
            for folder in self._store.library_folders.values()
            if folder.workspace_id == workspace_id
        ]
        folders.sort(key=lambda folder: (folder.name_key, str(folder.id)))
        return folders

    @override
    async def save(self, folder: LibraryFolder) -> None:
        if (
            self._find_sibling(
                folder.workspace_id,
                folder.parent_id,
                folder.name_key,
                except_folder_id=folder.id,
            )
            is not None
        ):
            raise LibraryFolderNameConflictError(
                workspace_id=folder.workspace_id,
                parent_id=folder.parent_id,
                name=folder.name,
            )
        self._store.library_folders[folder.id] = replace(folder)

    @override
    async def remove(self, folder: LibraryFolder) -> None:
        _ = self._store.library_folders.pop(folder.id, None)

    @override
    async def count_children(self, workspace_id: UUID, folder_id: UUID) -> int:
        return sum(
            1
            for folder in self._store.library_folders.values()
            if folder.workspace_id == workspace_id and folder.parent_id == folder_id
        )

    @override
    async def placements(self, workspace_id: UUID) -> dict[UUID, UUID]:
        return {
            artifact_id: folder_id
            for (placement_workspace, artifact_id), folder_id in (
                self._store.library_placements.items()
            )
            if placement_workspace == workspace_id
        }

    @override
    async def count_placements(self, workspace_id: UUID, folder_id: UUID) -> int:
        return sum(
            1
            for (placement_workspace, _), placed_folder in (
                self._store.library_placements.items()
            )
            if placement_workspace == workspace_id and placed_folder == folder_id
        )

    @override
    async def place(
        self,
        workspace_id: UUID,
        artifact_ids: list[UUID],
        folder_id: UUID | None,
    ) -> None:
        for artifact_id in artifact_ids:
            key = (workspace_id, artifact_id)
            _ = self._store.library_placements.pop(key, None)
            if folder_id is not None:
                self._store.library_placements[key] = folder_id


@final
class InMemoryUploadRepository:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def add(self, upload: "Upload") -> None:
        key = (upload.workspace_id, upload.upload_id)
        if key in self._store.uploads:
            raise ObjectAlreadyExistsError(
                f"Upload already exists: {upload.workspace_id}/{upload.upload_id}"
            )
        self._store.uploads[key] = _clone(upload)

    async def get(self, workspace_id: UUID, upload_id: UUID) -> "Upload | None":
        upload = self._store.uploads.get((workspace_id, upload_id))
        return None if upload is None else _clone(upload)

    async def list_for_workspace(self, workspace_id: UUID) -> list["Upload"]:
        uploads = [
            _clone(upload)
            for (stored_workspace_id, _), upload in self._store.uploads.items()
            if stored_workspace_id == workspace_id
        ]
        uploads.sort(key=lambda upload: (upload.created_at, str(upload.upload_id)))
        return uploads

    async def finalize_if_pending(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        *,
        actual_size: int,
        sha256: str,
        artifact_type: str,
        artifact_schema_version: int,
        artifact_id: UUID,
        completed_at: datetime,
        not_older_than: datetime,
    ) -> "Upload | None":
        upload = self._store.uploads.get((workspace_id, upload_id))
        if (
            upload is None
            or upload.status is not UploadStatus.PENDING
            or upload.created_at < not_older_than
        ):
            return None
        upload.status = UploadStatus.READY
        upload.actual_size = actual_size
        upload.sha256 = sha256
        upload.artifact_type = artifact_type
        upload.artifact_schema_version = artifact_schema_version
        upload.artifact_id = artifact_id
        upload.completed_at = completed_at
        return _clone(upload)

    async def mark_terminal_if_pending(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        *,
        status: UploadStatus,
    ) -> "Upload | None":
        if status not in {UploadStatus.FAILED, UploadStatus.EXPIRED}:
            raise ValueError(
                f"Upload terminal transition requires failed or expired; got {status}"
            )
        upload = self._store.uploads.get((workspace_id, upload_id))
        if upload is None or upload.status is not UploadStatus.PENDING:
            return None
        upload.status = status
        return _clone(upload)

    async def list_cleanup_candidates(
        self,
        *,
        pending_before: datetime,
        terminal_before: datetime,
        limit: int = 500,
    ) -> list["Upload"]:
        candidates: list[Upload] = []
        for upload in self._store.uploads.values():
            if (
                upload.status is UploadStatus.PENDING
                and upload.created_at < pending_before
            ):
                candidates.append(_clone(upload))
            elif (
                upload.status in {UploadStatus.FAILED, UploadStatus.EXPIRED}
                and upload.created_at < terminal_before
            ):
                candidates.append(_clone(upload))
        candidates.sort(key=lambda item: (item.created_at, str(item.upload_id)))
        return candidates[:limit]

    async def delete_terminal(self, workspace_id: UUID, upload_id: UUID) -> bool:
        upload = self._store.uploads.get((workspace_id, upload_id))
        if upload is None or upload.status not in {
            UploadStatus.FAILED,
            UploadStatus.EXPIRED,
        }:
            return False
        del self._store.uploads[(workspace_id, upload_id)]
        return True


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


@final
class InMemoryCollaborationRepository(CollaborationRepositoryPort):
    """The Project head, its command receipts, and its checkpoint mappings.

    Receipts and mappings are append-only and raise ``ConcurrentWriteError`` on a
    repeated key, the same way the SQL adapter turns its primary-key violation.
    The head is handed out as a copy: the service mutates what it read and writes
    it back with ``save_head``, and a copy never leaks an uncommitted change into
    the store.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add_head(self, head: ProjectHead) -> None:
        key = (head.workspace_id, head.project_id)
        if key in self._store.project_heads:
            raise ObjectAlreadyExistsError(f"Project head already exists: {key[1]}")
        self._store.project_heads[key] = _clone(head)

    @override
    async def get_head(
        self, workspace_id: UUID, project_id: UUID
    ) -> ProjectHead | None:
        head = self._store.project_heads.get((workspace_id, project_id))
        return None if head is None else _clone(head)

    @override
    async def lock_head(
        self, workspace_id: UUID, project_id: UUID
    ) -> ProjectHead | None:
        # One in-process transaction runs at a time: the unit of work's
        # transaction lock is this store's row lock.
        return await self.get_head(workspace_id, project_id)

    @override
    async def save_head(self, head: ProjectHead) -> None:
        key = (head.workspace_id, head.project_id)
        if key not in self._store.project_heads:
            return
        self._store.project_heads[key] = _clone(head)

    @override
    async def remove_head(self, workspace_id: UUID, project_id: UUID) -> None:
        _ = self._store.project_heads.pop((workspace_id, project_id), None)

    @override
    async def get_receipt(
        self, workspace_id: UUID, project_id: UUID, command_id: UUID
    ) -> ProjectCommandReceipt | None:
        return self._store.project_command_receipts.get(
            (workspace_id, project_id, command_id)
        )

    @override
    async def add_receipt(self, receipt: ProjectCommandReceipt) -> None:
        key = (receipt.workspace_id, receipt.project_id, receipt.command_id)
        if key in self._store.project_command_receipts:
            raise ConcurrentWriteError(
                f"Project command receipt already recorded: {receipt.project_id}"
                f"/{receipt.command_id}"
            )
        self._store.project_command_receipts[key] = receipt

    @override
    async def get_checkpoint_mapping(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        room_epoch: UUID,
        collaboration_sequence: int,
    ) -> ProjectCheckpointMapping | None:
        return self._store.project_checkpoint_mappings.get(
            (workspace_id, project_id, room_epoch, collaboration_sequence)
        )

    @override
    async def add_checkpoint_mapping(self, mapping: ProjectCheckpointMapping) -> None:
        key = (
            mapping.workspace_id,
            mapping.project_id,
            mapping.room_epoch,
            mapping.collaboration_sequence,
        )
        if key in self._store.project_checkpoint_mappings:
            raise ConcurrentWriteError(
                f"Project checkpoint mapping already recorded: {mapping.project_id}"
                f"/{mapping.room_epoch}/{mapping.collaboration_sequence}"
            )
        self._store.project_checkpoint_mappings[key] = mapping


@final
class InMemoryRunRepository(RunRepositoryPort):
    """Run bookkeeping. The results a Run caused belong to instances, not to it."""

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    def _owned(self, workspace_id: UUID, project_id: UUID, run_id: UUID) -> Run | None:
        run = self._store.runs.get(run_id)
        if (
            run is None
            or run.workspace_id != workspace_id
            or run.project_id != project_id
        ):
            return None
        return run

    @override
    async def add(self, run: Run) -> None:
        if run.id in self._store.runs:
            raise ObjectAlreadyExistsError(f"Run already exists: {run.id}")
        self._store.runs[run.id] = replace(run)

    @override
    async def get(
        self, workspace_id: UUID, project_id: UUID, run_id: UUID
    ) -> Run | None:
        run = self._owned(workspace_id, project_id, run_id)
        return None if run is None else replace(run)

    @override
    async def save(self, run: Run) -> None:
        # A transition writes status, finish stamp and error, and nothing else.
        stored = self._owned(run.workspace_id, run.project_id, run.id)
        if stored is None:
            return
        stored.status = run.status
        stored.finished_at = run.finished_at
        stored.error = run.error

    @override
    async def list_for_project(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[Run]:
        runs = [
            replace(run)
            for run in self._store.runs.values()
            if run.workspace_id == workspace_id
            and run.project_id == project_id
            and (not active_only or run.status is RunStatus.RUNNING)
        ]
        return _newest_first(
            runs, stamp=lambda run: run.created_at, ident=lambda run: run.id
        )[:limit]

    @override
    async def interrupt_unfinished(self, *, at: datetime, error: str) -> list[Run]:
        unfinished = [
            run for run in self._store.runs.values() if run.status is RunStatus.RUNNING
        ]
        for run in unfinished:
            run.status = RunStatus.INTERRUPTED
            run.finished_at = at
            run.error = error
        return [replace(run) for run in unfinished]


@final
class InMemoryResultStoreRepository(ResultStoreRepositoryPort):
    """Append-once results plus the one mutable pointer per node instance.

    Results are keyed by ``(workspace_id, fingerprint)`` so the same fingerprint in
    two Workspaces holds two rows, and a stored output payload is copied in and out
    so nothing can rewrite an appended result.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def artifact_is_referenced(
        self, workspace_id: UUID, artifact_id: UUID
    ) -> bool:
        return any(
            _outputs_reference(row.outputs, artifact_id)
            for (result_workspace, _), row in self._store.node_results.items()
            if result_workspace == workspace_id
        )

    @override
    async def get_result(
        self, workspace_id: UUID, fingerprint: str
    ) -> StoredResult | None:
        row = self._store.node_results.get((workspace_id, fingerprint))
        if row is None:
            return None
        return _result_view(row)

    @override
    async def put_result_if_absent(
        self,
        workspace_id: UUID,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
        *,
        created_at: datetime,
    ) -> StoredResult:
        key = (workspace_id, fingerprint)
        row = self._store.node_results.get(key)
        if row is None:
            row = StoredResult(
                fingerprint=fingerprint,
                outputs=_stored_outputs(outputs),
                created_at=created_at,
            )
            self._store.node_results[key] = row
        # Whatever happened, the row that is there is the answer: a fingerprint
        # that already had a result keeps it unchanged.
        return _result_view(row)

    @override
    async def get_pointer(
        self, workspace_id: UUID, instance: InstanceKey
    ) -> InstancePointer | None:
        return self._store.pointers.get((workspace_id, instance))

    @override
    async def list_pointers(
        self, workspace_id: UUID, project_id: UUID
    ) -> Mapping[InstanceKey, InstancePointer]:
        return {
            instance: pointer
            for (pointer_workspace, instance), pointer in self._store.pointers.items()
            if pointer_workspace == workspace_id
            and instance.project_id == str(project_id)
        }

    @override
    async def set_success_pointer(
        self, workspace_id: UUID, instance: InstanceKey, fingerprint: str
    ) -> None:
        self._store.pointers[(workspace_id, instance)] = InstancePointer(
            last_result_fingerprint=fingerprint, last_failure=None
        )

    @override
    async def set_failure_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
        failure: FailureRecord,
    ) -> None:
        # The previous result pointer is deliberately kept: a failure replaces the
        # failure and leaves the instance's last result where it was.
        previous = self._store.pointers.get((workspace_id, instance))
        self._store.pointers[(workspace_id, instance)] = InstancePointer(
            last_result_fingerprint=(
                None if previous is None else previous.last_result_fingerprint
            ),
            last_failure=failure,
        )


class InMemoryAgentConversationRepository(AgentConversationRepositoryPort):
    """Append-only Agent history over the cloned store.

    The conversation row is the sequence authority: an append only lands on the sequence
    the stored row is waiting for, and the row moves on with it. Frozen values are
    returned as stored - there is nothing for a caller to mutate behind the clone.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add(self, conversation: AgentConversation) -> None:
        key = (conversation.workspace_id, conversation.id)
        if key in self._store.agent_conversations:
            raise ConcurrentWriteError(
                f"Agent conversation already exists: {conversation.id}"
            )
        self._store.agent_conversations[key] = conversation

    @override
    async def get(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation | None:
        return self._store.agent_conversations.get((workspace_id, conversation_id))

    @override
    async def lock(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation | None:
        # No row lock to imitate: the unit of work's transaction lock serialises writers.
        return await self.get(workspace_id, conversation_id)

    @override
    async def list_for_agent(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> list[AgentConversation]:
        rows = [
            conversation
            for conversation in self._store.agent_conversations.values()
            if conversation.workspace_id == workspace_id
            and conversation.project_id == project_id
            and conversation.graph_id == graph_id
            and conversation.agent_id == agent_id
        ]
        return _newest_first(
            rows,
            stamp=lambda conversation: conversation.created_at,
            ident=lambda conversation: conversation.id,
        )

    @override
    async def append(self, event: AgentConversationEvent) -> None:
        key = (event.workspace_id, event.conversation_id)
        conversation = self._store.agent_conversations.get(key)
        if conversation is None:
            raise AgentConversationAppendError(
                f"Agent conversation does not exist: {event.conversation_id}"
            )
        if conversation.next_sequence != event.sequence:
            raise AgentConversationAppendError(
                f"Agent conversation {event.conversation_id} is at sequence "
                f"{conversation.next_sequence}, not {event.sequence}"
            )
        event_key = (event.workspace_id, event.conversation_id, event.sequence)
        if event_key in self._store.agent_conversation_events:
            raise ConcurrentWriteError(
                f"Agent conversation event already stored: {event_key}"
            )
        self._store.agent_conversation_events[event_key] = event
        self._store.agent_conversations[key] = conversation.appended(
            at=event.created_at
        )

    @override
    async def list_events(
        self,
        workspace_id: UUID,
        conversation_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentConversationEvent]:
        rows = [
            event
            for key, event in self._store.agent_conversation_events.items()
            if key[0] == workspace_id
            and key[1] == conversation_id
            and key[2] > after_sequence
        ]
        rows.sort(key=lambda event: event.sequence)
        return rows if limit is None else rows[:limit]


@dataclass(frozen=True, slots=True)
class _InMemoryUnitOfWorkState:
    working_store: InMemoryDataStore
    artifacts: ArtifactRepositoryPort
    uploads: "UploadRepositoryPort"
    library_folders: "LibraryFolderRepositoryPort"
    projects: ProjectRepositoryPort
    collaboration: CollaborationRepositoryPort
    runs: RunRepositoryPort
    results: ResultStoreRepositoryPort
    agent_conversations: AgentConversationRepositoryPort


class InMemoryUnitOfWork(UnitOfWorkPort):
    def __init__(self, store: InMemoryDataStore | None = None) -> None:
        self._store = store or InMemoryDataStore()
        self._transaction_lock = Lock()
        self._state: ContextVar[_InMemoryUnitOfWorkState | None] = ContextVar(
            "grafy_in_memory_unit_of_work_state",
            default=None,
        )
        self.commit_count = 0
        self.rollback_count = 0

    @property
    @override
    def artifacts(self) -> ArtifactRepositoryPort:
        return self._entered_state().artifacts

    @property
    def uploads(self) -> "UploadRepositoryPort":
        return self._entered_state().uploads

    @property
    def library_folders(self) -> "LibraryFolderRepositoryPort":
        return self._entered_state().library_folders

    @property
    @override
    def projects(self) -> ProjectRepositoryPort:
        return self._entered_state().projects

    @property
    @override
    def collaboration(self) -> CollaborationRepositoryPort:
        return self._entered_state().collaboration

    @property
    @override
    def runs(self) -> RunRepositoryPort:
        return self._entered_state().runs

    @property
    @override
    def results(self) -> ResultStoreRepositoryPort:
        return self._entered_state().results

    @property
    def agent_conversations(self) -> AgentConversationRepositoryPort:
        return self._entered_state().agent_conversations

    @override
    async def __aenter__(self) -> Self:
        if self._state.get() is not None:
            raise RuntimeError("Unit of work is already entered in this task")

        await self._transaction_lock.acquire()
        try:
            working_store = self._store.clone()
            self._state.set(
                _InMemoryUnitOfWorkState(
                    working_store=working_store,
                    artifacts=InMemoryArtifactRepository(working_store),
                    uploads=InMemoryUploadRepository(working_store),
                    library_folders=InMemoryLibraryFolderRepository(working_store),
                    projects=InMemoryProjectRepository(working_store),
                    collaboration=InMemoryCollaborationRepository(working_store),
                    runs=InMemoryRunRepository(working_store),
                    results=InMemoryResultStoreRepository(working_store),
                    agent_conversations=InMemoryAgentConversationRepository(
                        working_store
                    ),
                )
            )
        except BaseException:
            self._transaction_lock.release()
            raise
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        state = self._state.get()
        if state is None:
            return
        try:
            if exc_type is not None:
                await self.rollback()
        finally:
            self._state.set(None)
            self._transaction_lock.release()

    @override
    async def commit(self) -> None:
        state = self._entered_state()
        self._store.replace_with(state.working_store)
        self.commit_count += 1

    @override
    async def rollback(self) -> None:
        state = self._entered_state()
        state.working_store.replace_with(self._store)
        self.rollback_count += 1

    def _entered_state(self) -> _InMemoryUnitOfWorkState:
        state = self._state.get()
        if state is None:
            raise RuntimeError("Unit of work is not entered")
        return state
