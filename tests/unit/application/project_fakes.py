"""In-memory Project and Collaboration units of work for focused service tests.

These are not the runtime fakes in ``grafy_core.runtime.in_memory``: a service test has
to hold two transactions open at once and see what a real transaction does.

* reads come from the transaction's own snapshot, so a write is invisible to anybody
  else until ``commit()``, and a transaction that raises publishes nothing;
* ``commit()`` applies only the keys this transaction wrote, so a stale transaction
  cannot overwrite committed state it never read;
* ``lock_head`` takes a per-project row lock held until the transaction ends and
  re-reads the row once it holds it, which is what ``SELECT ... FOR UPDATE`` under read
  committed does - the second writer sees the first one's head and is refused;
* a commit whose read head has since moved, or that appends a checkpoint revision, head
  or receipt the committed store already holds, raises ``ConcurrentWriteError``;
* ``store.gate(name)`` parks a transaction inside one repository call on an
  ``asyncio.Event``, so interleavings are driven by events, never by sleeps.

Workspace scoping lives in the repositories the way a ``WHERE workspace_id = ...``
puts it: a row of another Workspace reads as missing.
"""

import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from types import TracebackType
from typing import Self, cast
from uuid import UUID

from pydantic import BaseModel

from grafy_core.domain.collaboration import (
    ProjectCheckpointMapping,
    ProjectCommandReceipt,
    ProjectHead,
)
from grafy_core.domain.errors import ConcurrentWriteError
from grafy_core.domain.identity import (
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
)
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
from grafy_core.domain.security_audit import SecurityAuditEvent
from grafy_core.kernel.project import ProjectDocument
from grafy_core.ports.identity import (
    IdentityRepositoryPort,
    SecurityAuditRepositoryPort,
)
from grafy_core.ports.node_secrets import NodeSecretRepositoryPort

COLLECTIONS: tuple[str, ...] = (
    "projects",
    "checkpoints",
    "folders",
    "organizations",
    "user_states",
    "heads",
    "receipts",
    "mappings",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clone[T](value: T) -> T:
    """Copy one stored row.

    The documents inside are frozen pydantic values, so a per-row copy is enough:
    a transaction that mutates a head or an organization mutates its own row, never
    the committed one. ``copy.deepcopy`` cannot do this - a Graph document holds
    mappingproxies for frozen node config, which do not pickle.
    """

    if isinstance(value, BaseModel):
        return cast("T", value.model_copy(deep=True))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return cast("T", dataclasses.replace(value))
    return value


def _clone_table[K, V](source: dict[K, V]) -> dict[K, V]:
    return {key: _clone(value) for key, value in source.items()}


class Gate:
    """A rendezvous inside a repository call.

    A test registers a gate with the number of transactions that must arrive before any
    of them goes on, so an interleaving is set up by events rather than by sleeps.
    ``released`` tells a test when the arrivals it expected have turned up.
    """

    def __init__(self, parties: int) -> None:
        self.parties = parties
        self.arrived = 0
        self.released = asyncio.Event()

    async def pass_here(self) -> None:
        self.arrived += 1
        if self.arrived >= self.parties:
            self.released.set()
        await self.released.wait()


class IdentityDirectory:
    """The users, workspaces and memberships the services authorize against."""

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.workspaces: dict[UUID, Workspace] = {}
        self.memberships: dict[tuple[UUID, UUID], WorkspaceMembership] = {}

    def add_user(self, user: User) -> User:
        self.users[user.id] = user
        return user

    def add_workspace(self, workspace: Workspace) -> Workspace:
        self.workspaces[workspace.id] = workspace
        return workspace

    def grant(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        role: WorkspaceRole,
    ) -> WorkspaceMembership:
        membership = WorkspaceMembership(
            workspace_id=workspace_id, user_id=user_id, role=role
        )
        self.memberships[(workspace_id, user_id)] = membership
        return membership

    def revoke(self, *, workspace_id: UUID, user_id: UUID) -> None:
        self.memberships[(workspace_id, user_id)].revoked_at = _utc_now()

    def disable_user(self, user_id: UUID) -> None:
        self.users[user_id].active = False

    def is_member(self, workspace_id: UUID, user_id: UUID) -> bool:
        membership = self.memberships.get((workspace_id, user_id))
        return membership is not None and membership.is_active


class FakeIdentityRepository:
    def __init__(self, directory: IdentityDirectory) -> None:
        self.directory = directory
        self.locked_workspaces: list[UUID] = []

    async def lock_workspace_for_membership_mutation(
        self,
        workspace_id: UUID,
    ) -> Workspace | None:
        self.locked_workspaces.append(workspace_id)
        return self.directory.workspaces.get(workspace_id)

    async def get_user(self, user_id: UUID) -> User | None:
        return self.directory.users.get(user_id)

    async def get_membership(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMembership | None:
        return self.directory.memberships.get((workspace_id, user_id))


class FakeNodeSecretRepository:
    """Present because the ports carry it; the Project services must never call it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list_for_graph(self, *args: object, **kwargs: object) -> list[object]:
        self.calls.append("list_for_graph")
        return []

    async def remove(self, *args: object, **kwargs: object) -> None:
        self.calls.append("remove")


class ProjectStore:
    """Committed state shared by every transaction over one fake database."""

    def __init__(self, directory: IdentityDirectory) -> None:
        self.directory = directory
        self.projects: dict[UUID, Project] = {}
        self.checkpoints: dict[tuple[UUID, int], ProjectCheckpoint] = {}
        self.folders: dict[UUID, ProjectFolder] = {}
        self.organizations: dict[tuple[UUID, UUID], ProjectOrganization] = {}
        self.user_states: dict[tuple[UUID, UUID, UUID], UserProjectState] = {}
        self.locations: dict[UUID, ProjectBrowserLocation] = {}
        self.heads: dict[tuple[UUID, UUID], ProjectHead] = {}
        self.receipts: dict[tuple[UUID, UUID, UUID], ProjectCommandReceipt] = {}
        self.mappings: dict[tuple[UUID, UUID, UUID, int], ProjectCheckpointMapping] = {}
        self.audit: list[SecurityAuditEvent] = []
        self.gates: dict[str, Gate] = {}
        self.row_locks: dict[tuple[UUID, UUID], asyncio.Lock] = {}

    def gate(self, name: str, *, parties: int = 1) -> Gate:
        gate = self.gates.get(name)
        if gate is None:
            gate = Gate(parties)
            self.gates[name] = gate
        return gate

    async def pass_gate(self, name: str) -> None:
        gate = self.gates.get(name)
        if gate is not None:
            await gate.pass_here()

    def row_lock(self, key: tuple[UUID, UUID]) -> asyncio.Lock:
        lock = self.row_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self.row_locks[key] = lock
        return lock

    def seed_location(self, workspace: Workspace) -> ProjectBrowserLocation:
        location = ProjectBrowserLocation(
            id=workspace.id,
            slug=workspace.slug,
            name=workspace.name,
            kind=workspace.kind,
        )
        self.locations[workspace.id] = location
        return location

    def seed_project(
        self,
        *,
        workspace_id: UUID,
        name: str,
        document: ProjectDocument,
        room_epoch: UUID | None = None,
        created_by_user_id: UUID | None = None,
        revision: int = 1,
    ) -> tuple[Project, ProjectHead]:
        """Write Project, its checkpoint and its head straight to committed state."""

        project = Project(
            workspace_id=workspace_id,
            name=name,
            created_by_user_id=created_by_user_id,
        )
        head = ProjectHead.for_existing_project(
            workspace_id=workspace_id,
            project_id=project.id,
            name=name,
            document=document,
            checkpoint_revision=revision,
            room_epoch=room_epoch,
        )
        self.projects[project.id] = project
        self.checkpoints[(project.id, revision)] = ProjectCheckpoint(
            workspace_id=workspace_id,
            project_id=project.id,
            revision=revision,
            name=name,
            document=document,
            created_at=head.updated_at,
        )
        self.heads[(workspace_id, project.id)] = head
        self.mappings[(workspace_id, project.id, head.room_epoch, 0)] = (
            ProjectCheckpointMapping(
                workspace_id=workspace_id,
                project_id=project.id,
                room_epoch=head.room_epoch,
                collaboration_sequence=0,
                checkpoint_revision=revision,
            )
        )
        return project, head

    def head_for(self, workspace_id: UUID, project_id: UUID) -> ProjectHead:
        return self.heads[(workspace_id, project_id)]

    def seed_folder(self, folder: ProjectFolder) -> ProjectFolder:
        self.folders[folder.id] = folder
        return folder

    def seed_organization(
        self, organization: ProjectOrganization
    ) -> ProjectOrganization:
        key = (organization.workspace_id, organization.project_id)
        self.organizations[key] = organization
        return organization

    def audit_for(self, operation: str) -> list[SecurityAuditEvent]:
        return [event for event in self.audit if event.operation == operation]


def _head_version(head: ProjectHead | None) -> tuple[object, ...] | None:
    if head is None:
        return None
    return (
        head.room_epoch,
        head.collaboration_sequence,
        head.checkpoint_sequence,
        head.checkpoint_revision,
    )


class ProjectTransaction:
    """One transaction's working copy of the store, plus the premises it commits on."""

    projects: dict[UUID, Project]
    checkpoints: dict[tuple[UUID, int], ProjectCheckpoint]
    folders: dict[UUID, ProjectFolder]
    organizations: dict[tuple[UUID, UUID], ProjectOrganization]
    user_states: dict[tuple[UUID, UUID, UUID], UserProjectState]
    heads: dict[tuple[UUID, UUID], ProjectHead]
    receipts: dict[tuple[UUID, UUID, UUID], ProjectCommandReceipt]
    mappings: dict[tuple[UUID, UUID, UUID, int], ProjectCheckpointMapping]

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.head_premises: dict[tuple[UUID, UUID], tuple[object, ...] | None] = {}
        self.appended_checkpoints: set[tuple[UUID, int]] = set()
        self.appended_receipts: set[tuple[UUID, UUID, UUID]] = set()
        self.added_heads: set[tuple[UUID, UUID]] = set()
        self.written: dict[str, set[object]] = {name: set() for name in COLLECTIONS}
        self.deleted: dict[str, set[object]] = {name: set() for name in COLLECTIONS}
        self.staged_audit: list[SecurityAuditEvent] = []
        self.held_locks: list[asyncio.Lock] = []
        self.begin()

    def begin(self) -> None:
        self.projects = _clone_table(self.store.projects)
        self.checkpoints = _clone_table(self.store.checkpoints)
        self.folders = _clone_table(self.store.folders)
        self.organizations = _clone_table(self.store.organizations)
        self.user_states = _clone_table(self.store.user_states)
        self.heads = _clone_table(self.store.heads)
        self.receipts = _clone_table(self.store.receipts)
        self.mappings = _clone_table(self.store.mappings)
        self.audit: list[SecurityAuditEvent] = list(self.store.audit)
        for name in COLLECTIONS:
            self.written[name] = set()
            self.deleted[name] = set()
        self.staged_audit = []

    def rollback(self) -> None:
        self.begin()
        self.head_premises.clear()
        self.appended_checkpoints.clear()
        self.appended_receipts.clear()
        self.added_heads.clear()

    def table(self, name: str) -> dict[object, object]:
        return cast("dict[object, object]", getattr(self, name))

    def put(self, name: str, key: object, value: object) -> None:
        self.table(name)[key] = value
        self.written[name].add(key)
        self.deleted[name].discard(key)

    def drop(self, name: str, key: object) -> None:
        self.table(name).pop(key, None)
        self.deleted[name].add(key)
        self.written[name].discard(key)

    def read(self, name: str, key: object) -> object | None:
        """One row as a fresh statement would see it.

        A write this transaction made wins; anything else is re-read from the
        committed store. That is what a new statement reads under read committed after
        this transaction waited for a row lock, and it is how a retry comes to see the
        receipt the first submission committed while it was blocked.
        """

        table = self.table(name)
        if key in self.written[name]:
            return table.get(key)
        if key in self.deleted[name]:
            return None
        committed = cast("dict[object, object]", getattr(self.store, name)).get(key)
        if committed is None:
            table.pop(key, None)
            return None
        fresh = _clone(committed)
        table[key] = fresh
        return fresh

    def commit(self) -> None:
        store = self.store
        for key, premise in self.head_premises.items():
            if _head_version(store.heads.get(key)) != premise:
                raise ConcurrentWriteError("Project head moved before commit")
        for key in self.appended_checkpoints:
            if key in store.checkpoints:
                raise ConcurrentWriteError("Project checkpoint revision exists")
        for key in self.added_heads:
            if key in store.heads:
                raise ConcurrentWriteError("Project head exists")
        for key in self.appended_receipts:
            if key in store.receipts:
                raise ConcurrentWriteError("Command receipt exists")
        for name in COLLECTIONS:
            table = getattr(store, name)
            for key in self.deleted[name]:
                table.pop(key, None)
            for key in self.written[name]:
                table[key] = _clone(self.table(name)[key])
        store.audit.extend(self.staged_audit)
        for name in COLLECTIONS:
            self.written[name] = set()
            self.deleted[name] = set()
        self.staged_audit = []


class FakeProjectRepository:
    def __init__(self, transaction: ProjectTransaction) -> None:
        self._transaction = transaction

    @property
    def _store(self) -> ProjectStore:
        return self._transaction.store

    async def add(self, project: Project) -> None:
        self._transaction.put("projects", project.id, project)

    async def get(self, workspace_id: UUID, project_id: UUID) -> Project | None:
        project = cast("Project | None", self._transaction.read("projects", project_id))
        if project is None or project.workspace_id != workspace_id:
            return None
        return project

    async def save(self, project: Project) -> None:
        if await self.get(project.workspace_id, project.id) is not None:
            self._transaction.put("projects", project.id, project)

    async def remove(self, workspace_id: UUID, project: Project) -> None:
        if project.workspace_id != workspace_id:
            return
        transaction = self._transaction
        transaction.drop("projects", project.id)
        for key in [key for key in transaction.checkpoints if key[0] == project.id]:
            transaction.drop("checkpoints", key)
        for key, organization in list(transaction.organizations.items()):
            if (
                organization.workspace_id == workspace_id
                and organization.project_id == project.id
            ):
                transaction.drop("organizations", key)
        for key, state in list(transaction.user_states.items()):
            if state.workspace_id == workspace_id and state.project_id == project.id:
                transaction.drop("user_states", key)

    async def list(self, workspace_id: UUID) -> list[Project]:
        return sorted(
            (
                project
                for project in self._transaction.projects.values()
                if project.workspace_id == workspace_id
            ),
            key=lambda project: project.name,
        )

    async def list_accessible(
        self,
        user_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> list[ProjectBrowserItem]:
        transaction = self._transaction
        items: list[ProjectBrowserItem] = []
        for project in transaction.projects.values():
            if workspace_id is not None and project.workspace_id != workspace_id:
                continue
            if not self._store.directory.is_member(project.workspace_id, user_id):
                continue
            head = transaction.heads.get((project.workspace_id, project.id))
            if head is None:
                continue
            organization = transaction.organizations.get(
                (project.workspace_id, project.id)
            )
            state = transaction.user_states.get(
                (project.workspace_id, project.id, user_id)
            )
            folder = (
                None
                if organization is None or organization.folder_id is None
                else transaction.folders.get(organization.folder_id)
            )
            creator = (
                None
                if project.created_by_user_id is None
                else self._store.directory.users.get(project.created_by_user_id)
            )
            items.append(
                ProjectBrowserItem(
                    id=project.id,
                    draft=ProjectBrowserDraft(
                        name=head.name,
                        head_sequence=head.collaboration_sequence,
                        checkpoint_sequence=head.checkpoint_sequence,
                        checkpoint_revision=head.checkpoint_revision,
                        updated_at=head.updated_at,
                        graph_count=len(head.document.graphs),
                        node_count=sum(
                            len(graph.document.nodes) for graph in head.document.graphs
                        ),
                        edge_count=sum(
                            len(graph.document.edges) for graph in head.document.graphs
                        ),
                    ),
                    location=self._store.locations[project.workspace_id],
                    folder=(
                        None
                        if folder is None
                        else ProjectBrowserFolder(id=folder.id, name=folder.name)
                    ),
                    archived_at=(
                        None if organization is None else organization.archived_at
                    ),
                    starred=False if state is None else state.starred,
                    last_opened_at=None if state is None else state.last_opened_at,
                    organization_updated_at=(
                        None if organization is None else organization.updated_at
                    ),
                    creator=(
                        None
                        if creator is None
                        else ProjectBrowserCreator(
                            id=creator.id, display_name=creator.display_name
                        )
                    ),
                )
            )
        return sorted(items, key=lambda item: item.draft.name.casefold())

    async def add_checkpoint(self, checkpoint: ProjectCheckpoint) -> None:
        await self._store.pass_gate("add_checkpoint")
        key = (checkpoint.project_id, checkpoint.revision)
        if key in self._transaction.checkpoints:
            raise ConcurrentWriteError("Project checkpoint revision exists")
        self._transaction.put("checkpoints", key, checkpoint)
        self._transaction.appended_checkpoints.add(key)

    async def get_checkpoint(
        self,
        workspace_id: UUID,
        project_id: UUID,
        revision: int,
    ) -> ProjectCheckpoint | None:
        checkpoint = cast(
            "ProjectCheckpoint | None",
            self._transaction.read("checkpoints", (project_id, revision)),
        )
        if checkpoint is None or checkpoint.workspace_id != workspace_id:
            return None
        return checkpoint

    async def list_checkpoints(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> list[ProjectCheckpoint]:
        transaction = self._transaction
        return [
            transaction.checkpoints[key]
            for key in sorted(transaction.checkpoints)
            if key[0] == project_id
            and transaction.checkpoints[key].workspace_id == workspace_id
        ]

    async def add_folder(self, folder: ProjectFolder) -> None:
        self._transaction.put("folders", folder.id, folder)

    async def get_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> ProjectFolder | None:
        folder = cast(
            "ProjectFolder | None", self._transaction.read("folders", folder_id)
        )
        if folder is None or folder.workspace_id != workspace_id:
            return None
        return folder

    async def get_folder_by_name(
        self,
        workspace_id: UUID,
        name: str,
    ) -> ProjectFolder | None:
        for folder in self._transaction.folders.values():
            if folder.workspace_id == workspace_id and folder.name == name:
                return folder
        return None

    async def list_folders(self, workspace_id: UUID) -> list[ProjectFolder]:
        return sorted(
            (
                folder
                for folder in self._transaction.folders.values()
                if folder.workspace_id == workspace_id
            ),
            key=lambda folder: folder.name,
        )

    async def save_folder(self, folder: ProjectFolder) -> None:
        self._transaction.put("folders", folder.id, folder)

    async def unfile_projects_in_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> None:
        for key, organization in self._transaction.organizations.items():
            if (
                organization.workspace_id == workspace_id
                and organization.folder_id == folder_id
            ):
                organization.assign_folder(None)
                self._transaction.put("organizations", key, organization)

    async def remove_folder(self, folder: ProjectFolder) -> None:
        self._transaction.drop("folders", folder.id)

    async def get_organization(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectOrganization | None:
        return cast(
            "ProjectOrganization | None",
            self._transaction.read("organizations", (workspace_id, project_id)),
        )

    async def save_organization(self, organization: ProjectOrganization) -> None:
        key = (organization.workspace_id, organization.project_id)
        self._transaction.put("organizations", key, organization)

    async def get_user_state(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> UserProjectState | None:
        return cast(
            "UserProjectState | None",
            self._transaction.read("user_states", (workspace_id, project_id, user_id)),
        )

    async def save_user_state(self, state: UserProjectState) -> None:
        key = (state.workspace_id, state.project_id, state.user_id)
        self._transaction.put("user_states", key, state)

    async def titles_referencing_artifact(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> dict[UUID, str]:
        needle = str(artifact_id)
        titles: dict[UUID, str] = {}
        for project in self._transaction.projects.values():
            if project.workspace_id != workspace_id:
                continue
            documents = [*self._documents_of(workspace_id, project.id)]
            if any(
                needle in json.dumps(document.model_dump(mode="json"))
                for document in documents
            ):
                titles[project.id] = project.name
        return titles

    def _documents_of(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> list[ProjectDocument]:
        transaction = self._transaction
        documents: list[ProjectDocument] = []
        head = transaction.heads.get((workspace_id, project_id))
        if head is not None:
            documents.append(head.document)
        documents.extend(
            checkpoint.document
            for key, checkpoint in transaction.checkpoints.items()
            if key[0] == project_id
        )
        return documents


class FakeCollaborationRepository:
    def __init__(self, transaction: ProjectTransaction) -> None:
        self._transaction = transaction

    @property
    def _store(self) -> ProjectStore:
        return self._transaction.store

    async def add_head(self, head: ProjectHead) -> None:
        key = (head.workspace_id, head.project_id)
        if key in self._transaction.heads:
            raise ConcurrentWriteError("Project head exists")
        self._transaction.put("heads", key, head)
        self._transaction.added_heads.add(key)

    async def get_head(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectHead | None:
        key = (workspace_id, project_id)
        transaction = self._transaction
        if key not in transaction.head_premises:
            transaction.head_premises[key] = _head_version(self._store.heads.get(key))
        return cast("ProjectHead | None", transaction.read("heads", key))

    async def lock_head(
        self, workspace_id: UUID, project_id: UUID
    ) -> ProjectHead | None:
        await self._store.pass_gate("lock_head")
        key = (workspace_id, project_id)
        transaction = self._transaction
        lock = self._store.row_lock(key)
        await lock.acquire()
        transaction.held_locks.append(lock)
        # What SELECT ... FOR UPDATE returns is the row as it stands now, not the row
        # this transaction read before it waited for the lock, and the premise the
        # commit is checked against is that row too.
        head = cast("ProjectHead | None", transaction.read("heads", key))
        transaction.head_premises[key] = _head_version(self._store.heads.get(key))
        return head

    async def save_head(self, head: ProjectHead) -> None:
        self._transaction.put("heads", (head.workspace_id, head.project_id), head)

    async def remove_head(self, workspace_id: UUID, project_id: UUID) -> None:
        self._transaction.drop("heads", (workspace_id, project_id))

    async def get_receipt(
        self,
        workspace_id: UUID,
        project_id: UUID,
        command_id: UUID,
    ) -> ProjectCommandReceipt | None:
        return cast(
            "ProjectCommandReceipt | None",
            self._transaction.read("receipts", (workspace_id, project_id, command_id)),
        )

    async def add_receipt(self, receipt: ProjectCommandReceipt) -> None:
        key = (receipt.workspace_id, receipt.project_id, receipt.command_id)
        if key in self._transaction.receipts:
            raise ConcurrentWriteError("Command receipt exists")
        self._transaction.put("receipts", key, receipt)
        self._transaction.appended_receipts.add(key)

    async def get_checkpoint_mapping(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        room_epoch: UUID,
        collaboration_sequence: int,
    ) -> ProjectCheckpointMapping | None:
        return cast(
            "ProjectCheckpointMapping | None",
            self._transaction.read(
                "mappings",
                (workspace_id, project_id, room_epoch, collaboration_sequence),
            ),
        )

    async def add_checkpoint_mapping(self, mapping: ProjectCheckpointMapping) -> None:
        key = (
            mapping.workspace_id,
            mapping.project_id,
            mapping.room_epoch,
            mapping.collaboration_sequence,
        )
        self._transaction.put("mappings", key, mapping)


class FakeSecurityAuditRepository:
    def __init__(self, transaction: ProjectTransaction) -> None:
        self._transaction = transaction

    async def add(self, event: SecurityAuditEvent) -> None:
        self._transaction.staged_audit.append(event)


class ProjectTestUnitOfWork:
    """One transaction that satisfies the Project and the Collaboration port both.

    The three repositories a Project service has no business calling are carried behind
    their port types as partial doubles: each implements only the one method a service
    would reach if it strayed into that owner's table, and ``secret_calls`` reports
    whether any of them was reached at all.
    """

    def __init__(self, store: ProjectStore) -> None:
        self.transaction = ProjectTransaction(store)
        self.projects = FakeProjectRepository(self.transaction)
        self.collaboration = FakeCollaborationRepository(self.transaction)
        self._node_secrets = FakeNodeSecretRepository()
        self._identity = FakeIdentityRepository(store.directory)
        self._security_audit = FakeSecurityAuditRepository(self.transaction)
        self.commit_count = 0
        self.rollback_count = 0
        self.committed = False

    @property
    def node_secrets(self) -> NodeSecretRepositoryPort:
        return cast("NodeSecretRepositoryPort", self._node_secrets)

    @property
    def identity(self) -> IdentityRepositoryPort:
        return cast("IdentityRepositoryPort", self._identity)

    @property
    def security_audit(self) -> SecurityAuditRepositoryPort:
        return cast("SecurityAuditRepositoryPort", self._security_audit)

    @property
    def secret_calls(self) -> list[str]:
        """Every call the secret double recorded - empty for any correct Project flow."""

        return self._node_secrets.calls

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if exc_type is not None:
            await self.rollback()
        self.release_locks()

    def release_locks(self) -> None:
        while self.transaction.held_locks:
            lock = self.transaction.held_locks.pop()
            if lock.locked():
                lock.release()

    async def commit(self) -> None:
        self.commit_count += 1
        self.transaction.commit()
        self.committed = True

    async def rollback(self) -> None:
        if self.committed:
            return
        self.rollback_count += 1
        self.transaction.rollback()


class ProjectUnitOfWorkFactory:
    """Hands out transactions over one store and remembers the ones it handed out."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.opened: list[ProjectTestUnitOfWork] = []

    def __call__(self) -> ProjectTestUnitOfWork:
        unit_of_work = ProjectTestUnitOfWork(self.store)
        self.opened.append(unit_of_work)
        return unit_of_work

    @property
    def last(self) -> ProjectTestUnitOfWork:
        return self.opened[-1]

    @property
    def secrets_touched(self) -> bool:
        return any(unit_of_work.secret_calls for unit_of_work in self.opened)


def new_member(
    directory: IdentityDirectory,
    *,
    display_name: str,
    slug: str,
    role: WorkspaceRole = WorkspaceRole.OWNER,
    kind: WorkspaceKind = WorkspaceKind.SHARED,
) -> tuple[Workspace, User]:
    """A Workspace, a member holding ``role``, and the browser location listing needs."""

    user = directory.add_user(User(display_name=display_name))
    workspace = directory.add_workspace(
        Workspace(
            slug=slug,
            name=display_name,
            kind=kind,
            personal_owner_user_id=user.id if kind is WorkspaceKind.PERSONAL else None,
        )
    )
    directory.grant(workspace_id=workspace.id, user_id=user.id, role=role)
    return workspace, user


__all__ = [
    "COLLECTIONS",
    "FakeCollaborationRepository",
    "FakeIdentityRepository",
    "FakeNodeSecretRepository",
    "FakeProjectRepository",
    "FakeSecurityAuditRepository",
    "Gate",
    "IdentityDirectory",
    "ProjectStore",
    "ProjectTestUnitOfWork",
    "ProjectUnitOfWorkFactory",
    "new_member",
]
