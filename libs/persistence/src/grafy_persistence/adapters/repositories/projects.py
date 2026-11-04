"""SQL adapters for the Project aggregate and its collaboration state (ADR 0020).

Both repositories are built on one supplied ``AsyncSession`` and speak Core SQL
against the Project schema: the Project carries no version column, so the durable
ordering the room depends on comes from the append-only checkpoint and receipt
tables and from ``lock_head``'s row lock, not from ORM optimistic locking.

Every statement is scoped by ``workspace_id`` together with the Project id, so a
Project of another Workspace is indistinguishable from one that was never there.
"""

from typing import cast, override
from uuid import UUID

from sqlalchemy import String, Select, and_, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.domain.collaboration import (
    ProjectCheckpointMapping,
    ProjectCommandReceipt,
    ProjectHead,
)
from grafy_core.domain.errors import (
    ConcurrentWriteError,
    ProjectFolderNameConflictError,
)
from grafy_core.domain.identity import WorkspaceKind, WorkspaceRole
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
from grafy_core.kernel.project import ProjectDocument
from grafy_core.ports.collaboration import CollaborationRepositoryPort
from grafy_core.ports.projects import ProjectRepositoryPort
from grafy_persistence import schema


def _project_from_row(row) -> Project:
    return Project(
        workspace_id=cast(UUID, row["workspace_id"]),
        name=cast(str, row["name"]),
        created_by_user_id=row["created_by_user_id"],
        id=cast(UUID, row["id"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqlProjectRepository(ProjectRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, project: Project) -> None:
        await self._session.execute(
            insert(schema.projects).values(
                id=project.id,
                workspace_id=project.workspace_id,
                created_by_user_id=project.created_by_user_id,
                name=project.name,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )

    @override
    async def get(self, workspace_id: UUID, project_id: UUID) -> Project | None:
        table = schema.projects
        row = (
            (
                await self._session.execute(
                    select(
                        table.c.id,
                        table.c.workspace_id,
                        table.c.created_by_user_id,
                        table.c.name,
                        table.c.created_at,
                        table.c.updated_at,
                    ).where(
                        table.c.workspace_id == workspace_id,
                        table.c.id == project_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _project_from_row(row)

    @override
    async def save(self, project: Project) -> None:
        await self._session.execute(
            update(schema.projects)
            .where(
                schema.projects.c.workspace_id == project.workspace_id,
                schema.projects.c.id == project.id,
            )
            .values(name=project.name, updated_at=project.updated_at)
        )

    @override
    async def remove(self, workspace_id: UUID, project: Project) -> None:
        await self._session.execute(
            delete(schema.projects).where(
                schema.projects.c.workspace_id == workspace_id,
                schema.projects.c.id == project.id,
            )
        )

    @override
    async def list(self, workspace_id: UUID) -> list[Project]:
        table = schema.projects
        rows = (
            (
                await self._session.execute(
                    select(
                        table.c.id,
                        table.c.workspace_id,
                        table.c.created_by_user_id,
                        table.c.name,
                        table.c.created_at,
                        table.c.updated_at,
                    )
                    .where(table.c.workspace_id == workspace_id)
                    .order_by(table.c.updated_at.desc(), table.c.id.asc())
                )
            )
            .mappings()
            .all()
        )
        return [_project_from_row(row) for row in rows]

    @override
    async def list_accessible(
        self,
        user_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> list[ProjectBrowserItem]:
        projects = schema.projects
        memberships = schema.workspace_memberships
        workspaces = schema.workspaces
        folders = schema.project_folders
        organizations = schema.project_organizations
        states = schema.user_project_states
        heads = schema.project_heads
        active_user = schema.users.alias("active_project_browser_user")
        creator = schema.users.alias("project_creator")
        query: Select = (
            select(
                projects.c.id,
                projects.c.workspace_id.label("project_workspace_id"),
                organizations.c.archived_at,
                organizations.c.updated_at.label("organization_updated_at"),
                heads.c.name.label("head_name"),
                heads.c.document.label("head_document"),
                heads.c.collaboration_sequence,
                heads.c.checkpoint_sequence,
                heads.c.checkpoint_revision,
                heads.c.updated_at.label("head_updated_at"),
                workspaces.c.id.label("workspace_id"),
                workspaces.c.slug.label("workspace_slug"),
                workspaces.c.name.label("workspace_name"),
                workspaces.c.kind.label("workspace_kind"),
                folders.c.id.label("folder_id"),
                folders.c.name.label("folder_name"),
                states.c.starred,
                states.c.last_opened_at,
                creator.c.id.label("creator_id"),
                creator.c.display_name.label("creator_display_name"),
            )
            .select_from(
                projects.join(
                    memberships,
                    and_(
                        memberships.c.workspace_id == projects.c.workspace_id,
                        memberships.c.user_id == user_id,
                        memberships.c.revoked_at.is_(None),
                        memberships.c.role.in_(
                            (
                                WorkspaceRole.VIEWER.value,
                                WorkspaceRole.EDITOR.value,
                                WorkspaceRole.OWNER.value,
                            )
                        ),
                    ),
                )
                .join(
                    active_user,
                    and_(
                        active_user.c.id == user_id,
                        active_user.c.active.is_(True),
                    ),
                )
                .join(workspaces, workspaces.c.id == projects.c.workspace_id)
                .join(
                    heads,
                    and_(
                        heads.c.workspace_id == projects.c.workspace_id,
                        heads.c.project_id == projects.c.id,
                    ),
                )
                .outerjoin(
                    organizations,
                    and_(
                        organizations.c.workspace_id == projects.c.workspace_id,
                        organizations.c.project_id == projects.c.id,
                    ),
                )
                .outerjoin(
                    folders,
                    and_(
                        folders.c.workspace_id == projects.c.workspace_id,
                        folders.c.id == organizations.c.folder_id,
                    ),
                )
                .outerjoin(
                    states,
                    and_(
                        states.c.workspace_id == projects.c.workspace_id,
                        states.c.project_id == projects.c.id,
                        states.c.user_id == user_id,
                    ),
                )
                .outerjoin(creator, creator.c.id == projects.c.created_by_user_id)
            )
            .order_by(
                heads.c.updated_at.desc(),
                projects.c.id.asc(),
            )
        )
        if workspace_id is not None:
            query = query.where(projects.c.workspace_id == workspace_id)
        rows = (await self._session.execute(query)).mappings()
        items: list[ProjectBrowserItem] = []
        for row in rows:
            document = cast(ProjectDocument, row["head_document"])
            graph_count = len(document.graphs)
            node_count = sum(len(graph.document.nodes) for graph in document.graphs)
            edge_count = sum(len(graph.document.edges) for graph in document.graphs)
            folder_id = row["folder_id"]
            creator_id = row["creator_id"]
            items.append(
                ProjectBrowserItem(
                    id=cast(UUID, row["id"]),
                    draft=ProjectBrowserDraft(
                        name=cast(str, row["head_name"]),
                        head_sequence=cast(int, row["collaboration_sequence"]),
                        checkpoint_sequence=cast(int, row["checkpoint_sequence"]),
                        checkpoint_revision=cast(int, row["checkpoint_revision"]),
                        updated_at=row["head_updated_at"],
                        graph_count=graph_count,
                        node_count=node_count,
                        edge_count=edge_count,
                    ),
                    location=ProjectBrowserLocation(
                        id=cast(UUID, row["workspace_id"]),
                        slug=cast(str, row["workspace_slug"]),
                        name=cast(str, row["workspace_name"]),
                        kind=WorkspaceKind(cast(str, row["workspace_kind"])),
                    ),
                    folder=(
                        None
                        if folder_id is None
                        else ProjectBrowserFolder(
                            id=folder_id,
                            name=cast(str, row["folder_name"]),
                        )
                    ),
                    archived_at=row["archived_at"],
                    starred=bool(row["starred"]),
                    last_opened_at=row["last_opened_at"],
                    organization_updated_at=row["organization_updated_at"],
                    creator=(
                        None
                        if creator_id is None
                        else ProjectBrowserCreator(
                            id=creator_id,
                            display_name=row["creator_display_name"],
                        )
                    ),
                )
            )
        return items

    # --- Append-only checkpoints -------------------------------------------------

    @override
    async def add_checkpoint(self, checkpoint: ProjectCheckpoint) -> None:
        try:
            await self._session.execute(
                insert(schema.project_checkpoints).values(
                    workspace_id=checkpoint.workspace_id,
                    project_id=checkpoint.project_id,
                    revision=checkpoint.revision,
                    name=checkpoint.name,
                    document=checkpoint.document,
                    created_at=checkpoint.created_at,
                )
            )
        except IntegrityError as exc:
            # The composite primary key is the append-only guard: a repeated revision
            # is a lost race, never an update of an existing checkpoint.
            raise ConcurrentWriteError(
                f"Project checkpoint already exists: {checkpoint.project_id}"
                f"/r{checkpoint.revision}"
            ) from exc

    @override
    async def get_checkpoint(
        self,
        workspace_id: UUID,
        project_id: UUID,
        revision: int,
    ) -> ProjectCheckpoint | None:
        table = schema.project_checkpoints
        row = (
            (
                await self._session.execute(
                    select(
                        table.c.workspace_id,
                        table.c.project_id,
                        table.c.revision,
                        table.c.name,
                        table.c.document,
                        table.c.created_at,
                    ).where(
                        table.c.workspace_id == workspace_id,
                        table.c.project_id == project_id,
                        table.c.revision == revision,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _checkpoint_from_row(row)

    @override
    async def list_checkpoints(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> list[ProjectCheckpoint]:
        table = schema.project_checkpoints
        rows = (
            (
                await self._session.execute(
                    select(
                        table.c.workspace_id,
                        table.c.project_id,
                        table.c.revision,
                        table.c.name,
                        table.c.document,
                        table.c.created_at,
                    )
                    .where(
                        table.c.workspace_id == workspace_id,
                        table.c.project_id == project_id,
                    )
                    .order_by(table.c.revision.asc())
                )
            )
            .mappings()
            .all()
        )
        return [_checkpoint_from_row(row) for row in rows]

    # --- Filing: folders ---------------------------------------------------------

    @override
    async def add_folder(self, folder: ProjectFolder) -> None:
        try:
            await self._session.execute(
                insert(schema.project_folders).values(
                    id=folder.id,
                    workspace_id=folder.workspace_id,
                    name=folder.name,
                    created_at=folder.created_at,
                    updated_at=folder.updated_at,
                )
            )
        except IntegrityError as exc:
            raise ProjectFolderNameConflictError(
                workspace_id=folder.workspace_id,
                name=folder.name,
            ) from exc

    @override
    async def get_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> ProjectFolder | None:
        table = schema.project_folders
        row = (
            (
                await self._session.execute(
                    select(
                        table.c.id,
                        table.c.workspace_id,
                        table.c.name,
                        table.c.created_at,
                        table.c.updated_at,
                    ).where(
                        table.c.workspace_id == workspace_id,
                        table.c.id == folder_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _folder_from_row(row)

    @override
    async def get_folder_by_name(
        self,
        workspace_id: UUID,
        name: str,
    ) -> ProjectFolder | None:
        table = schema.project_folders
        row = (
            (
                await self._session.execute(
                    select(
                        table.c.id,
                        table.c.workspace_id,
                        table.c.name,
                        table.c.created_at,
                        table.c.updated_at,
                    ).where(
                        table.c.workspace_id == workspace_id,
                        table.c.name == name,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _folder_from_row(row)

    @override
    async def list_folders(self, workspace_id: UUID) -> list[ProjectFolder]:
        table = schema.project_folders
        rows = (
            (
                await self._session.execute(
                    select(
                        table.c.id,
                        table.c.workspace_id,
                        table.c.name,
                        table.c.created_at,
                        table.c.updated_at,
                    )
                    .where(table.c.workspace_id == workspace_id)
                    .order_by(table.c.name.asc(), table.c.id.asc())
                )
            )
            .mappings()
            .all()
        )
        return [_folder_from_row(row) for row in rows]

    @override
    async def save_folder(self, folder: ProjectFolder) -> None:
        try:
            await self._session.execute(
                update(schema.project_folders)
                .where(
                    schema.project_folders.c.workspace_id == folder.workspace_id,
                    schema.project_folders.c.id == folder.id,
                )
                .values(name=folder.name, updated_at=folder.updated_at)
            )
        except IntegrityError as exc:
            raise ProjectFolderNameConflictError(
                workspace_id=folder.workspace_id,
                name=folder.name,
            ) from exc

    @override
    async def unfile_projects_in_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> None:
        from datetime import UTC, datetime

        await self._session.execute(
            update(schema.project_organizations)
            .where(
                schema.project_organizations.c.workspace_id == workspace_id,
                schema.project_organizations.c.folder_id == folder_id,
            )
            .values(folder_id=None, updated_at=datetime.now(UTC))
        )

    @override
    async def remove_folder(self, folder: ProjectFolder) -> None:
        await self._session.execute(
            delete(schema.project_folders).where(
                schema.project_folders.c.workspace_id == folder.workspace_id,
                schema.project_folders.c.id == folder.id,
            )
        )

    # --- Filing: organization and per-user state ---------------------------------

    @override
    async def get_organization(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectOrganization | None:
        table = schema.project_organizations
        row = (
            (
                await self._session.execute(
                    select(
                        table.c.workspace_id,
                        table.c.project_id,
                        table.c.folder_id,
                        table.c.archived_at,
                        table.c.updated_at,
                    ).where(
                        table.c.workspace_id == workspace_id,
                        table.c.project_id == project_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return ProjectOrganization(
            workspace_id=cast(UUID, row["workspace_id"]),
            project_id=cast(UUID, row["project_id"]),
            folder_id=row["folder_id"],
            archived_at=row["archived_at"],
            updated_at=row["updated_at"],
        )

    @override
    async def save_organization(self, organization: ProjectOrganization) -> None:
        await _upsert(
            self._session,
            schema.project_organizations,
            conflict_columns=(
                schema.project_organizations.c.workspace_id,
                schema.project_organizations.c.project_id,
            ),
            values={
                "workspace_id": organization.workspace_id,
                "project_id": organization.project_id,
                "folder_id": organization.folder_id,
                "archived_at": organization.archived_at,
                "updated_at": organization.updated_at,
            },
            update_columns=("folder_id", "archived_at", "updated_at"),
        )

    @override
    async def get_user_state(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> UserProjectState | None:
        table = schema.user_project_states
        row = (
            (
                await self._session.execute(
                    select(
                        table.c.workspace_id,
                        table.c.project_id,
                        table.c.user_id,
                        table.c.starred,
                        table.c.last_opened_at,
                    ).where(
                        table.c.workspace_id == workspace_id,
                        table.c.project_id == project_id,
                        table.c.user_id == user_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return UserProjectState(
            workspace_id=cast(UUID, row["workspace_id"]),
            project_id=cast(UUID, row["project_id"]),
            user_id=cast(UUID, row["user_id"]),
            starred=bool(row["starred"]),
            last_opened_at=row["last_opened_at"],
        )

    @override
    async def save_user_state(self, state: UserProjectState) -> None:
        await _upsert(
            self._session,
            schema.user_project_states,
            conflict_columns=(
                schema.user_project_states.c.workspace_id,
                schema.user_project_states.c.project_id,
                schema.user_project_states.c.user_id,
            ),
            values={
                "workspace_id": state.workspace_id,
                "project_id": state.project_id,
                "user_id": state.user_id,
                "starred": state.starred,
                "last_opened_at": state.last_opened_at,
            },
            update_columns=("starred", "last_opened_at"),
        )

    @override
    async def titles_referencing_artifact(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> dict[UUID, str]:
        # A node origin and an artifact card each hold the artifact identity as a
        # lowercase UUID string inside the JSON document, so the identity is matched
        # as text. No other value in a document can collide with a full 36-character
        # identity, and both the live head and every retained checkpoint count: a
        # restored checkpoint must not point at an artifact that has been deleted.
        needle = f"%{artifact_id}%"
        referencing = (
            select(schema.project_heads.c.project_id)
            .where(
                schema.project_heads.c.workspace_id == workspace_id,
                schema.project_heads.c.document.cast(String).like(needle),
            )
            .union(
                select(schema.project_checkpoints.c.project_id).where(
                    schema.project_checkpoints.c.workspace_id == workspace_id,
                    schema.project_checkpoints.c.document.cast(String).like(needle),
                )
            )
            .subquery("artifact_referencing_projects")
        )
        rows = await self._session.execute(
            select(schema.projects.c.id, schema.projects.c.name).where(
                schema.projects.c.workspace_id == workspace_id,
                schema.projects.c.id.in_(select(referencing.c.project_id)),
            )
        )
        return {project_id: name for project_id, name in rows}


class SqlCollaborationRepository(CollaborationRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add_head(self, head: ProjectHead) -> None:
        await self._session.execute(
            insert(schema.project_heads).values(_head_values(head))
        )

    @override
    async def get_head(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectHead | None:
        return await self._read_head(workspace_id, project_id, for_update=False)

    @override
    async def lock_head(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectHead | None:
        # SELECT ... FOR UPDATE serialises accept-and-append on the head inside the
        # current transaction; on SQLite the lock is a no-op the dialect elides.
        return await self._read_head(workspace_id, project_id, for_update=True)

    async def _read_head(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        for_update: bool,
    ) -> ProjectHead | None:
        table = schema.project_heads
        statement = select(table).where(
            table.c.workspace_id == workspace_id,
            table.c.project_id == project_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return ProjectHead(
            workspace_id=cast(UUID, row["workspace_id"]),
            project_id=cast(UUID, row["project_id"]),
            room_epoch=cast(UUID, row["room_epoch"]),
            collaboration_sequence=cast(int, row["collaboration_sequence"]),
            checkpoint_sequence=cast(int, row["checkpoint_sequence"]),
            checkpoint_revision=cast(int, row["checkpoint_revision"]),
            name=cast(str, row["name"]),
            document=cast(ProjectDocument, row["document"]),
            updated_at=row["updated_at"],
        )

    @override
    async def save_head(self, head: ProjectHead) -> None:
        await self._session.execute(
            update(schema.project_heads)
            .where(
                schema.project_heads.c.workspace_id == head.workspace_id,
                schema.project_heads.c.project_id == head.project_id,
            )
            .values(_head_values(head))
        )

    @override
    async def remove_head(self, workspace_id: UUID, project_id: UUID) -> None:
        await self._session.execute(
            delete(schema.project_heads).where(
                schema.project_heads.c.workspace_id == workspace_id,
                schema.project_heads.c.project_id == project_id,
            )
        )

    @override
    async def get_receipt(
        self,
        workspace_id: UUID,
        project_id: UUID,
        command_id: UUID,
    ) -> ProjectCommandReceipt | None:
        table = schema.project_command_receipts
        row = (
            (
                await self._session.execute(
                    select(table).where(
                        table.c.workspace_id == workspace_id,
                        table.c.project_id == project_id,
                        table.c.command_id == command_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return _receipt_from_row(dict(row))

    @override
    async def add_receipt(self, receipt: ProjectCommandReceipt) -> None:
        try:
            await self._session.execute(
                insert(schema.project_command_receipts).values(
                    workspace_id=receipt.workspace_id,
                    project_id=receipt.project_id,
                    command_id=receipt.command_id,
                    command_hmac=receipt.command_hmac,
                    hmac_key_version=receipt.hmac_key_version,
                    actor_kind=receipt.actor_kind.value,
                    actor_user_id=receipt.actor_user_id,
                    room_epoch=receipt.room_epoch,
                    accepted_sequence=receipt.accepted_sequence,
                    outcome=receipt.outcome.value,
                    created_at=receipt.created_at,
                )
            )
        except IntegrityError as exc:
            # The command id is the idempotency key: one accepted command, one row.
            raise ConcurrentWriteError(
                f"Project command receipt already recorded: {receipt.project_id}"
                f"/{receipt.command_id}"
            ) from exc

    @override
    async def get_checkpoint_mapping(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        room_epoch: UUID,
        collaboration_sequence: int,
    ) -> ProjectCheckpointMapping | None:
        table = schema.project_checkpoint_mappings
        row = (
            (
                await self._session.execute(
                    select(table).where(
                        table.c.workspace_id == workspace_id,
                        table.c.project_id == project_id,
                        table.c.room_epoch == room_epoch,
                        table.c.collaboration_sequence == collaboration_sequence,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return ProjectCheckpointMapping.model_validate(dict(row))

    @override
    async def add_checkpoint_mapping(
        self,
        mapping: ProjectCheckpointMapping,
    ) -> None:
        try:
            await self._session.execute(
                insert(schema.project_checkpoint_mappings).values(
                    workspace_id=mapping.workspace_id,
                    project_id=mapping.project_id,
                    room_epoch=mapping.room_epoch,
                    collaboration_sequence=mapping.collaboration_sequence,
                    checkpoint_revision=mapping.checkpoint_revision,
                    created_at=mapping.created_at,
                )
            )
        except IntegrityError as exc:
            raise ConcurrentWriteError(
                f"Project checkpoint mapping already recorded: {mapping.project_id}"
                f"/{mapping.room_epoch}/{mapping.collaboration_sequence}"
            ) from exc


def _head_values(head: ProjectHead) -> dict[str, object]:
    return {
        "workspace_id": head.workspace_id,
        "project_id": head.project_id,
        "room_epoch": head.room_epoch,
        "collaboration_sequence": head.collaboration_sequence,
        "checkpoint_sequence": head.checkpoint_sequence,
        "checkpoint_revision": head.checkpoint_revision,
        "name": head.name,
        "document": head.document,
        "updated_at": head.updated_at,
    }


def _receipt_from_row(row: dict[str, object]) -> ProjectCommandReceipt:
    command_hmac = row["command_hmac"]
    row["command_hmac"] = (
        bytes(command_hmac) if isinstance(command_hmac, memoryview) else command_hmac
    )
    return ProjectCommandReceipt.model_validate(row)


def _checkpoint_from_row(row) -> ProjectCheckpoint:
    return ProjectCheckpoint(
        workspace_id=cast(UUID, row["workspace_id"]),
        project_id=cast(UUID, row["project_id"]),
        revision=cast(int, row["revision"]),
        name=cast(str, row["name"]),
        document=cast(ProjectDocument, row["document"]),
        created_at=row["created_at"],
    )


def _folder_from_row(row) -> ProjectFolder:
    return ProjectFolder(
        workspace_id=cast(UUID, row["workspace_id"]),
        name=cast(str, row["name"]),
        id=cast(UUID, row["id"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _upsert(
    session: AsyncSession,
    table,
    *,
    conflict_columns,
    values: dict[str, object],
    update_columns: tuple[str, ...],
) -> None:
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        raise NotImplementedError(
            f"Project upsert requires SQLite or PostgreSQL; got {dialect_name!r}"
        )
    statement = dialect_insert(table).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=conflict_columns,
            set_={column: statement.excluded[column] for column in update_columns},
        )
    )
