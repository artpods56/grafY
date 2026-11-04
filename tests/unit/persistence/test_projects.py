from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func as sa_func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.collaboration import (
    CollaborationActorKind,
    CommandReceiptOutcome,
    ProjectCheckpointMapping,
    ProjectCommandReceipt,
    ProjectHead,
)
from grafy_core.domain.errors import (
    ConcurrentWriteError,
    ProjectFolderNameConflictError,
)
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphEdge,
    GraphNode,
    GraphOrigin,
    GraphPoint,
)
from grafy_core.domain.identity import WorkspaceKind, WorkspaceRole
from grafy_core.domain.projects import (
    Project,
    ProjectCheckpoint,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_persistence.adapters.repositories import (
    SqlCollaborationRepository,
    SqlProjectRepository,
)
from grafy_persistence.database import Database
from grafy_persistence import schema
from tests.support.persistence import database as _base_database_fixture

base_database = _base_database_fixture

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
ARTIFACT_ID = UUID("00000000-0000-0000-0000-0000000000a1")


@pytest.fixture
async def database(base_database: Database) -> AsyncIterator[Database]:
    async with base_database.engine.begin() as connection:
        await connection.execute(
            insert(schema.users).values(
                id=USER_ID,
                active=True,
                email_verified=False,
                display_name="Ada",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
    yield base_database


def _graph(
    token: str, label: str, *, nodes: int = 2, edges: int = 1
) -> GraphDefinition:
    node_objs = tuple(
        GraphNode(
            kind="builtin",
            id=f"{token}-node-{i}",
            operator_id="text.source",
            operator_version=1,
            position=GraphPoint(x=float(i), y=0.0),
        )
        for i in range(nodes)
    )
    edge_objs = tuple(
        GraphEdge(
            id=f"{token}-edge-{i}",
            from_node=node_objs[i].id,
            from_port="result",
            to_node=node_objs[i + 1].id,
            to_port="value",
        )
        for i in range(edges)
    )
    return GraphDefinition(
        id=token,
        name=label,
        document=GraphDocument(nodes=node_objs, edges=edge_objs),
    )


def _document(*graph_specs: tuple[str, str]) -> ProjectDocument:
    return ProjectDocument(
        graphs=tuple(_graph(token, label) for token, label in graph_specs)
    )


def _document_with_artifact(token: str, label: str) -> ProjectDocument:
    node = GraphNode(
        kind="builtin",
        id=f"{token}-node-0",
        operator_id="text.source",
        operator_version=1,
        position=GraphPoint(x=0.0, y=0.0),
    )
    origin = GraphOrigin(
        id=f"{token}-origin",
        to_node=node.id,
        to_port="value",
        value=ArtifactRef(
            artifact_id=ARTIFACT_ID,
            artifact_type="scalar.text",
            schema_version=1,
        ),
    )
    return ProjectDocument(
        graphs=(
            GraphDefinition(
                id=token,
                name=label,
                document=GraphDocument(nodes=(node,), origins=(origin,)),
            ),
        )
    )


def _session(database: Database):
    return database.sessions()


async def _add_project(
    session: AsyncSession,
    *,
    project_id: UUID,
    workspace_id: UUID = WORKSPACE_ID,
    name: str = "Project",
    created_by_user_id: UUID | None = None,
) -> Project:
    projects = SqlProjectRepository(session)
    project = Project(
        workspace_id=workspace_id,
        id=project_id,
        name=name,
        created_by_user_id=created_by_user_id,
    )
    await projects.add(project)
    return project


# --- Identity: Project CRUD, Workspace isolation, ordering ---------------------


@pytest.mark.asyncio
async def test_project_round_trip_and_rename(database: Database) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000101")
    async with _session(database) as session:
        created = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
        project = Project(
            workspace_id=WORKSPACE_ID,
            id=project_id,
            name="Original",
            created_by_user_id=USER_ID,
            created_at=created,
            updated_at=created,
        )
        await SqlProjectRepository(session).add(project)
        await session.commit()

    async with _session(database) as session:
        loaded = await SqlProjectRepository(session).get(WORKSPACE_ID, project_id)
    assert loaded is not None
    assert loaded.name == "Original"
    assert loaded.created_by_user_id == USER_ID
    assert loaded.created_at == created
    assert loaded.created_at.tzinfo is UTC

    async with _session(database) as session:
        loaded.rename("Renamed", updated_at=datetime(2026, 7, 14, 9, 0, tzinfo=UTC))
        await SqlProjectRepository(session).save(loaded)
        await session.commit()

    async with _session(database) as session:
        reloaded = await SqlProjectRepository(session).get(WORKSPACE_ID, project_id)
    assert reloaded is not None
    assert reloaded.name == "Renamed"
    assert reloaded.updated_at == datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_reads_are_scoped_to_workspace(database: Database) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000102")
    async with _session(database) as session:
        await _add_project(session, project_id=project_id)
        await session.commit()

    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        assert await projects.get(OTHER_WORKSPACE_ID, project_id) is None
        assert await projects.list(OTHER_WORKSPACE_ID) == []
        assert await projects.get(WORKSPACE_ID, project_id) is not None


@pytest.mark.asyncio
async def test_list_orders_by_updated_at_desc_then_id_asc(database: Database) -> None:
    older = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    newer = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    low = UUID("00000000-0000-0000-0000-000000000001")
    high = UUID("00000000-0000-0000-0000-000000000009")
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        await projects.add(
            Project(
                WORKSPACE_ID, "tie high", id=high, created_at=older, updated_at=older
            )
        )
        await projects.add(
            Project(WORKSPACE_ID, "newest", id=low, created_at=newer, updated_at=newer)
        )
        await session.commit()

    async with _session(database) as session:
        listed = await SqlProjectRepository(session).list(WORKSPACE_ID)
    assert [p.id for p in listed] == [low, high]


@pytest.mark.asyncio
async def test_remove_deletes_scoped_project_only(database: Database) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000103")
    async with _session(database) as session:
        project = await _add_project(session, project_id=project_id)
        await session.commit()

    async with _session(database) as session:
        # A wrong-workspace removal must not touch the row.
        await SqlProjectRepository(session).remove(OTHER_WORKSPACE_ID, project)
        await session.commit()
    async with _session(database) as session:
        assert (
            await SqlProjectRepository(session).get(WORKSPACE_ID, project_id)
            is not None
        )

    async with _session(database) as session:
        await SqlProjectRepository(session).remove(WORKSPACE_ID, project)
        await session.commit()
    async with _session(database) as session:
        assert await SqlProjectRepository(session).get(WORKSPACE_ID, project_id) is None


# --- Checkpoints: append-only, collision, Workspace isolation ------------------


@pytest.mark.asyncio
async def test_checkpoints_append_only_and_reject_duplicate_revision(
    database: Database,
) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000110")
    async with _session(database) as session:
        await _add_project(session, project_id=project_id)
        await session.commit()

    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        await projects.add_checkpoint(
            ProjectCheckpoint(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                revision=1,
                name="First",
                document=_document(("g0", "Main")),
                created_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    async with _session(database) as session:
        with pytest.raises(ConcurrentWriteError):
            await SqlProjectRepository(session).add_checkpoint(
                ProjectCheckpoint(
                    workspace_id=WORKSPACE_ID,
                    project_id=project_id,
                    revision=1,
                    name="Second",
                    document=_document(("g0", "Main")),
                    created_at=datetime(2026, 7, 14, 9, 0, tzinfo=UTC),
                )
            )

    # The rejected second write never replaced the original checkpoint.
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        first = await projects.get_checkpoint(WORKSPACE_ID, project_id, 1)
        assert first is not None
        assert first.name == "First"
        # A different revision appends; a foreign workspace read sees nothing.
        await projects.add_checkpoint(
            ProjectCheckpoint(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                revision=2,
                name="Second",
                document=_document(("g0", "Main"), ("g1", "Sub")),
                created_at=datetime(2026, 7, 14, 9, 0, tzinfo=UTC),
            )
        )
        await session.commit()
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        listed = await projects.list_checkpoints(WORKSPACE_ID, project_id)
        assert [c.revision for c in listed] == [1, 2]
        assert listed[0].document.graphs[0].name == "Main"
        assert await projects.get_checkpoint(OTHER_WORKSPACE_ID, project_id, 1) is None


# --- Head: CAS/sequence invariants, lock, mapping ------------------------------


@pytest.mark.asyncio
async def test_head_round_trip_and_sequence_persist(database: Database) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000120")
    epoch = UUID("00000000-0000-0000-0000-000000000ead")
    async with _session(database) as session:
        await _add_project(session, project_id=project_id)
        head = ProjectHead(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            room_epoch=epoch,
            collaboration_sequence=0,
            checkpoint_sequence=0,
            checkpoint_revision=1,
            name="Head",
            document=_document(("g0", "Main")),
        )
        await SqlCollaborationRepository(session).add_head(head)
        await session.commit()

    async with _session(database) as session:
        collab = SqlCollaborationRepository(session)
        loaded = await collab.lock_head(WORKSPACE_ID, project_id)
        assert loaded is not None
        loaded.apply_accepted_batch(
            name="Advanced",
            document=_document(("g0", "Main"), ("g1", "Sub")),
            updated_at=datetime(2026, 7, 14, 10, 0, tzinfo=UTC),
        )
        await collab.save_head(loaded)
        await session.commit()

    async with _session(database) as session:
        collab = SqlCollaborationRepository(session)
        reloaded = await collab.get_head(WORKSPACE_ID, project_id)
        assert reloaded is not None
        assert reloaded.collaboration_sequence == 1
        assert reloaded.name == "Advanced"
        assert len(reloaded.document.graphs) == 2
        # Foreign workspace sees no head.
        assert await collab.get_head(OTHER_WORKSPACE_ID, project_id) is None


@pytest.mark.asyncio
async def test_checkpoint_mapping_round_trip_and_rejects_duplicate(
    database: Database,
) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000121")
    epoch = UUID("00000000-0000-0000-0000-000000000ebe")
    async with _session(database) as session:
        await _add_project(session, project_id=project_id)
        await SqlCollaborationRepository(session).add_head(
            ProjectHead(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                room_epoch=epoch,
                collaboration_sequence=0,
                checkpoint_sequence=0,
                checkpoint_revision=1,
                name="Head",
                document=_document(("g0", "Main")),
            )
        )
        await SqlProjectRepository(session).add_checkpoint(
            ProjectCheckpoint(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                revision=1,
                name="Head",
                document=_document(("g0", "Main")),
                created_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    mapping = ProjectCheckpointMapping(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        room_epoch=epoch,
        collaboration_sequence=0,
        checkpoint_revision=1,
    )
    async with _session(database) as session:
        await SqlCollaborationRepository(session).add_checkpoint_mapping(mapping)
        await session.commit()

    async with _session(database) as session:
        collab = SqlCollaborationRepository(session)
        found = await collab.get_checkpoint_mapping(
            WORKSPACE_ID, project_id, room_epoch=epoch, collaboration_sequence=0
        )
        assert found is not None
        assert found.checkpoint_revision == 1
        with pytest.raises(ConcurrentWriteError):
            await collab.add_checkpoint_mapping(mapping)


# --- Receipts: idempotency key, HMAC bytes, duplicate rejection ----------------


@pytest.mark.asyncio
async def test_command_receipt_round_trip_and_rejects_duplicate(
    database: Database,
) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000130")
    epoch = UUID("00000000-0000-0000-0000-000000000ec0")
    command_id = UUID("00000000-0000-0000-0000-000000000c01")
    async with _session(database) as session:
        await _add_project(session, project_id=project_id)
        await SqlCollaborationRepository(session).add_head(
            ProjectHead(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                room_epoch=epoch,
                collaboration_sequence=1,
                checkpoint_sequence=0,
                checkpoint_revision=1,
                name="Head",
                document=_document(("g0", "Main")),
            )
        )
        await session.commit()

    receipt = ProjectCommandReceipt(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        command_id=command_id,
        command_hmac=b"\x01\x02\x03" + b"\x00" * 29,
        hmac_key_version=1,
        actor_kind=CollaborationActorKind.USER,
        actor_user_id=USER_ID,
        room_epoch=epoch,
        accepted_sequence=1,
        outcome=CommandReceiptOutcome.ACCEPTED,
    )
    async with _session(database) as session:
        await SqlCollaborationRepository(session).add_receipt(receipt)
        await session.commit()

    async with _session(database) as session:
        collab = SqlCollaborationRepository(session)
        found = await collab.get_receipt(WORKSPACE_ID, project_id, command_id)
        assert found is not None
        assert bytes(found.command_hmac) == receipt.command_hmac
        assert found.actor_kind is CollaborationActorKind.USER
        assert found.outcome is CommandReceiptOutcome.ACCEPTED
        assert found.accepted_sequence == 1
        with pytest.raises(ConcurrentWriteError):
            await collab.add_receipt(receipt)


# --- Filing: folders, archive/star/open inverse transitions ---------------------


@pytest.mark.asyncio
async def test_folder_name_conflict_and_lookup(database: Database) -> None:
    async with _session(database) as session:
        folders = SqlProjectRepository(session)
        await folders.add_folder(ProjectFolder(WORKSPACE_ID, "Research"))
        await session.commit()
    async with _session(database) as session:
        folders = SqlProjectRepository(session)
        with pytest.raises(ProjectFolderNameConflictError):
            await folders.add_folder(ProjectFolder(WORKSPACE_ID, "Research"))
        await session.rollback()
        assert await folders.get_folder_by_name(WORKSPACE_ID, "Research") is not None
        assert await folders.get_folder_by_name(OTHER_WORKSPACE_ID, "Research") is None


@pytest.mark.asyncio
async def test_archive_and_star_are_reversible(database: Database) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000140")
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        await _add_project(session, project_id=project_id)
        folder = ProjectFolder(WORKSPACE_ID, "Research")
        await projects.add_folder(folder)
        organization = ProjectOrganization(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            folder_id=folder.id,
        )
        organization.archive(archived_at=datetime(2026, 8, 11, 8, 0, tzinfo=UTC))
        await projects.save_organization(organization)
        state = UserProjectState(WORKSPACE_ID, project_id, USER_ID, starred=True)
        state.record_open(opened_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC))
        await projects.save_user_state(state)
        await session.commit()

    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        loaded_org = await projects.get_organization(
            workspace_id=WORKSPACE_ID, project_id=project_id
        )
        assert loaded_org is not None
        assert loaded_org.is_archived and loaded_org.folder_id == folder.id
        loaded_state = await projects.get_user_state(
            workspace_id=WORKSPACE_ID, project_id=project_id, user_id=USER_ID
        )
        assert loaded_state is not None
        assert loaded_state.starred is True
        assert loaded_state.last_opened_at == datetime(2026, 8, 11, 9, 0, tzinfo=UTC)

    # Reverse both: unarchive and unstar, then reopen with an earlier stamp is a no-op.
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        loaded_org.restore(restored_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC))
        loaded_org.assign_folder(
            None, updated_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
        )
        await projects.save_organization(loaded_org)
        loaded_state.set_starred(False)
        loaded_state.record_open(opened_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC))
        await projects.save_user_state(loaded_state)
        await session.commit()

    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        org = await projects.get_organization(
            workspace_id=WORKSPACE_ID, project_id=project_id
        )
        assert org is not None
        assert not org.is_archived and org.folder_id is None
        state = await projects.get_user_state(
            workspace_id=WORKSPACE_ID, project_id=project_id, user_id=USER_ID
        )
        assert state is not None
        assert state.starred is False
        # record_open is monotonic: the older reopen did not overwrite the newer one.
        assert state.last_opened_at == datetime(2026, 8, 11, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_unfile_and_remove_folder(database: Database) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000141")
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        await _add_project(session, project_id=project_id)
        folder = ProjectFolder(WORKSPACE_ID, "Research")
        await projects.add_folder(folder)
        await projects.save_organization(
            ProjectOrganization(WORKSPACE_ID, project_id, folder_id=folder.id)
        )
        await session.commit()

    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        await projects.unfile_projects_in_folder(WORKSPACE_ID, folder.id)
        await projects.remove_folder(folder)
        await session.commit()

    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        org = await projects.get_organization(
            workspace_id=WORKSPACE_ID, project_id=project_id
        )
        assert org is not None and org.folder_id is None
        assert await projects.get_folder(WORKSPACE_ID, folder.id) is None


# --- Browser list: counts, location, creator, archive/star ---------------------


@pytest.mark.asyncio
async def test_removing_project_cascades_to_all_child_rows(database: Database) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000170")
    epoch = UUID("00000000-0000-0000-0000-000000000ef0")
    command_id = UUID("00000000-0000-0000-0000-000000000f01")
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        collab = SqlCollaborationRepository(session)
        project = await _add_project(session, project_id=project_id)
        await collab.add_head(
            ProjectHead(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                room_epoch=epoch,
                collaboration_sequence=1,
                checkpoint_sequence=0,
                checkpoint_revision=1,
                name="Head",
                document=_document(("g0", "Main")),
            )
        )
        await projects.add_checkpoint(
            ProjectCheckpoint(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                revision=1,
                name="Head",
                document=_document(("g0", "Main")),
                created_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
            )
        )
        await collab.add_checkpoint_mapping(
            ProjectCheckpointMapping(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                room_epoch=epoch,
                collaboration_sequence=0,
                checkpoint_revision=1,
            )
        )
        await collab.add_receipt(
            ProjectCommandReceipt(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                command_id=command_id,
                command_hmac=b"\x00" * 32,
                hmac_key_version=1,
                actor_kind=CollaborationActorKind.USER,
                actor_user_id=USER_ID,
                room_epoch=epoch,
                accepted_sequence=1,
                outcome=CommandReceiptOutcome.ACCEPTED,
            )
        )
        await projects.save_organization(
            ProjectOrganization(workspace_id=WORKSPACE_ID, project_id=project_id)
        )
        await projects.save_user_state(
            UserProjectState(WORKSPACE_ID, project_id, USER_ID, starred=True)
        )
        await session.commit()

    async with _session(database) as session:
        await SqlProjectRepository(session).remove(WORKSPACE_ID, project)
        await session.commit()

    async with _session(database) as session:
        for table in (
            schema.project_heads,
            schema.project_checkpoints,
            schema.project_checkpoint_mappings,
            schema.project_command_receipts,
            schema.project_organizations,
            schema.user_project_states,
        ):
            remaining = await session.scalar(
                select(sa_func.count())
                .select_from(table)
                .where(table.c.project_id == project_id)
            )
            assert remaining == 0, f"{table.name} survived project deletion"


@pytest.mark.asyncio
async def test_list_accessible_counts_and_metadata(database: Database) -> None:
    project_id = UUID("00000000-0000-0000-0000-000000000150")
    epoch = UUID("00000000-0000-0000-0000-000000000ed0")
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        await _add_project(
            session,
            project_id=project_id,
            name="Two graphs",
            created_by_user_id=USER_ID,
        )
        folder = ProjectFolder(WORKSPACE_ID, "Research")
        await projects.add_folder(folder)
        await projects.save_organization(
            ProjectOrganization(WORKSPACE_ID, project_id, folder_id=folder.id)
        )
        await projects.save_user_state(
            UserProjectState(WORKSPACE_ID, project_id, USER_ID, starred=True)
        )
        await session.execute(
            insert(schema.workspace_memberships).values(
                workspace_id=WORKSPACE_ID,
                user_id=USER_ID,
                role=WorkspaceRole.EDITOR.value,
                authorization_version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await SqlCollaborationRepository(session).add_head(
            ProjectHead(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                room_epoch=epoch,
                collaboration_sequence=5,
                checkpoint_sequence=3,
                checkpoint_revision=2,
                name="Renamed head",
                document=_document(("g0", "Main"), ("g1", "Sub")),
                updated_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    async with _session(database) as session:
        items = await SqlProjectRepository(session).list_accessible(USER_ID)
    assert len(items) == 1
    item = items[0]
    assert item.id == project_id
    # Two graphs, each built with 2 nodes and 1 edge.
    assert item.draft.graph_count == 2
    assert item.draft.node_count == 4
    assert item.draft.edge_count == 2
    assert item.draft.name == "Renamed head"  # the browser shows the head, not identity
    assert item.draft.head_sequence == 5
    assert item.location.kind is WorkspaceKind.SHARED
    assert item.folder is not None and item.folder.name == "Research"
    assert item.creator is not None and item.creator.id == USER_ID
    assert item.starred is True

    # A non-member sees nothing.
    async with _session(database) as session:
        assert (
            await SqlProjectRepository(session).list_accessible(
                UUID("00000000-0000-0000-0000-000000000999")
            )
            == []
        )

    # Filtered to a Workspace that holds nothing for the user.
    async with _session(database) as session:
        assert (
            await SqlProjectRepository(session).list_accessible(
                USER_ID, workspace_id=OTHER_WORKSPACE_ID
            )
            == []
        )


# --- titles_referencing_artifact spans heads and checkpoints -------------------


@pytest.mark.asyncio
async def test_titles_referencing_artifact_across_heads_and_checkpoints(
    database: Database,
) -> None:
    head_project = UUID("00000000-0000-0000-0000-000000000160")
    checkpoint_project = UUID("00000000-0000-0000-0000-000000000161")
    unrelated_project = UUID("00000000-0000-0000-0000-000000000162")
    epoch = UUID("00000000-0000-0000-0000-000000000ee0")
    async with _session(database) as session:
        projects = SqlProjectRepository(session)
        collab = SqlCollaborationRepository(session)
        # One project references the artifact only through its live head.
        await _add_project(session, project_id=head_project, name="Head holder")
        await collab.add_head(
            ProjectHead(
                workspace_id=WORKSPACE_ID,
                project_id=head_project,
                room_epoch=epoch,
                collaboration_sequence=0,
                checkpoint_sequence=0,
                checkpoint_revision=1,
                name="Head holder",
                document=_document_with_artifact("g0", "Main"),
            )
        )
        # Another references it only through a retained checkpoint.
        await _add_project(
            session, project_id=checkpoint_project, name="Checkpoint holder"
        )
        await collab.add_head(
            ProjectHead(
                workspace_id=WORKSPACE_ID,
                project_id=checkpoint_project,
                room_epoch=epoch,
                collaboration_sequence=0,
                checkpoint_sequence=0,
                checkpoint_revision=1,
                name="Checkpoint holder now",
                document=_document(("g0", "Main")),
            )
        )
        await projects.add_checkpoint(
            ProjectCheckpoint(
                workspace_id=WORKSPACE_ID,
                project_id=checkpoint_project,
                revision=1,
                name="Checkpoint holder then",
                document=_document_with_artifact("g0", "Main"),
                created_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
            )
        )
        # An unrelated project must not appear.
        await _add_project(session, project_id=unrelated_project, name="Unrelated")
        await collab.add_head(
            ProjectHead(
                workspace_id=WORKSPACE_ID,
                project_id=unrelated_project,
                room_epoch=epoch,
                collaboration_sequence=0,
                checkpoint_sequence=0,
                checkpoint_revision=1,
                name="Unrelated",
                document=_document(("g0", "Main")),
            )
        )
        await session.commit()

    async with _session(database) as session:
        titles = await SqlProjectRepository(session).titles_referencing_artifact(
            WORKSPACE_ID, ARTIFACT_ID
        )
    assert set(titles) == {head_project, checkpoint_project}
    assert titles[head_project] == "Head holder"
    assert titles[checkpoint_project] == "Checkpoint holder"
