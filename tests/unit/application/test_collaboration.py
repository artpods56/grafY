from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from grafy_core.application.collaboration import CollaborationService
from grafy_core.domain.collaboration import (
    AddEdgeCommand,
    AddNodeCommand,
    ApplyGraphCommandBatch,
    CollaborativeGraphHead,
    CommandReceiptOutcome,
    GraphActiveExecutionSlot,
    GraphCheckpointMapping,
    GraphCommandJournalEntry,
    GraphCommandKind,
    GraphCommandReceipt,
    MoveNodePosition,
    MoveNodesCommand,
    RenameGraphCommand,
    ReplaceDocumentCommand,
    UpdateNodeOperatorCommand,
    UpdateNodeConfigurationAndInputPlugsCommand,
)
from grafy_core.domain.errors import (
    CapabilityDeniedError,
    CollaborationActiveExecutionError,
    CollaborationCommandRejectedError,
    CollaborationHeadConflictError,
    CollaborationIdempotencyMismatchError,
    CollaborationUncheckpointedError,
    ConcurrentWriteError,
    MissingCollaborativeHeadError,
    SavedGraphRevisionConflictError,
)
from grafy_core.domain.identity import (
    ActorContext,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraph,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphInputPlug,
    SavedGraphNode,
    SavedGraphRevision,
)
from grafy_core.domain.security_audit import (
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.collaboration import CollaborationUnitOfWorkPort


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000201")
USER_ID = UUID("00000000-0000-0000-0000-000000000202")
HMAC_KEY = b"test-command-hmac-key-phase3"


class FakeCollaborationRepository:
    def __init__(self) -> None:
        self.heads: dict[tuple[UUID, UUID], CollaborativeGraphHead] = {}
        self.receipts: dict[tuple[UUID, UUID, UUID], GraphCommandReceipt] = {}
        self.journal: list[GraphCommandJournalEntry] = []
        self.mappings: dict[
            tuple[UUID, UUID, UUID, int], GraphCheckpointMapping
        ] = {}
        self.active_slots: dict[tuple[UUID, UUID], GraphActiveExecutionSlot] = {}
        self.locked: list[tuple[UUID, UUID]] = []
        self.graphs_by_id: dict[UUID, SavedGraph] = {}

    async def add_head(self, head: CollaborativeGraphHead) -> None:
        key = (head.workspace_id, head.graph_id)
        if key in self.heads:
            raise ValueError("head exists")
        self.heads[key] = head

    async def get_head(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> CollaborativeGraphHead | None:
        return self.heads.get((workspace_id, graph_id))

    async def lock_head(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> CollaborativeGraphHead | None:
        self.locked.append((workspace_id, graph_id))
        return self.heads.get((workspace_id, graph_id))

    async def save_head(self, head: CollaborativeGraphHead) -> None:
        self.heads[(head.workspace_id, head.graph_id)] = head

    async def remove_head(self, workspace_id: UUID, graph_id: UUID) -> None:
        self.heads.pop((workspace_id, graph_id), None)

    async def list_graphs_missing_heads(self) -> list[tuple[UUID, UUID]]:
        return [
            (graph.workspace_id, graph.id)
            for graph in self.graphs_by_id.values()
            if (graph.workspace_id, graph.id) not in self.heads
        ]

    async def add_journal_entry(self, entry: GraphCommandJournalEntry) -> None:
        self.journal.append(entry)

    async def clear_journal(self, workspace_id: UUID, graph_id: UUID) -> None:
        self.journal = [
            entry
            for entry in self.journal
            if not (
                entry.workspace_id == workspace_id and entry.graph_id == graph_id
            )
        ]

    async def get_receipt(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        command_id: UUID,
    ) -> GraphCommandReceipt | None:
        return self.receipts.get((workspace_id, graph_id, command_id))

    async def add_receipt(self, receipt: GraphCommandReceipt) -> None:
        self.receipts[(receipt.workspace_id, receipt.graph_id, receipt.command_id)] = (
            receipt
        )

    async def get_checkpoint_mapping(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        room_epoch: UUID,
        collaboration_sequence: int,
    ) -> GraphCheckpointMapping | None:
        return self.mappings.get(
            (workspace_id, graph_id, room_epoch, collaboration_sequence)
        )

    async def add_checkpoint_mapping(self, mapping: GraphCheckpointMapping) -> None:
        self.mappings[
            (
                mapping.workspace_id,
                mapping.graph_id,
                mapping.room_epoch,
                mapping.collaboration_sequence,
            )
        ] = mapping

    async def get_execution_idempotency(self, *args, **kwargs):
        del args, kwargs
        return None

    async def add_execution_idempotency(self, record) -> None:
        del record

    async def get_active_execution_slot(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> GraphActiveExecutionSlot | None:
        return self.active_slots.get((workspace_id, graph_id))

    async def acquire_active_execution_slot(self, slot: GraphActiveExecutionSlot) -> bool:
        key = (slot.workspace_id, slot.graph_id)
        if key in self.active_slots:
            return False
        self.active_slots[key] = slot
        return True

    async def clear_active_execution_slot(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        execution_id: UUID | None = None,
    ) -> None:
        key = (workspace_id, graph_id)
        existing = self.active_slots.get(key)
        if existing is None:
            return
        if execution_id is not None and existing.execution_id != execution_id:
            return
        self.active_slots.pop(key, None)

    async def clear_all_active_execution_slots(self) -> int:
        count = len(self.active_slots)
        self.active_slots.clear()
        return count


class FakeSavedGraphRepository:
    def __init__(self) -> None:
        self.graphs: dict[UUID, SavedGraph] = {}
        self.revisions: dict[tuple[UUID, int], SavedGraphRevision] = {}
        self.locked_revisions: list[tuple[UUID, UUID, int]] = []

    async def add(self, graph: SavedGraph) -> None:
        self.graphs[graph.id] = graph

    async def add_revision(self, revision: SavedGraphRevision) -> None:
        self.revisions[(revision.graph_id, revision.revision)] = revision

    async def lock_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        expected_revision: int,
    ) -> None:
        self.locked_revisions.append((workspace_id, graph_id, expected_revision))

    async def get(self, workspace_id: UUID, graph_id: UUID) -> SavedGraph | None:
        graph = self.graphs.get(graph_id)
        if graph is None or graph.workspace_id != workspace_id:
            return None
        return graph

    async def get_revision(self, *args, **kwargs):
        del args, kwargs
        return None

    async def list_revisions(self, *args, **kwargs):
        del args, kwargs
        return []

    async def list(self, workspace_id: UUID) -> list[SavedGraph]:
        return [
            graph for graph in self.graphs.values() if graph.workspace_id == workspace_id
        ]

    async def remove(self, workspace_id: UUID, graph: SavedGraph) -> None:
        if graph.workspace_id == workspace_id:
            self.graphs.pop(graph.id, None)


class FakeNodeSecretRepository:
    async def list_for_graph(self, *args, **kwargs):
        del args, kwargs
        return []

    async def remove(self, *args, **kwargs) -> None:
        del args, kwargs


class FakeIdentityRepository:
    def __init__(
        self,
        user: User,
        memberships: list[WorkspaceMembership],
    ) -> None:
        self.user = user
        self.memberships = {
            (membership.workspace_id, membership.user_id): membership
            for membership in memberships
        }

    async def get_user(self, user_id: UUID) -> User | None:
        if user_id != self.user.id:
            return None
        return self.user

    async def get_membership(self, *, workspace_id: UUID, user_id: UUID):
        return self.memberships.get((workspace_id, user_id))


class FakeSecurityAuditRepository:
    def __init__(self) -> None:
        self.events: list[SecurityAuditEvent] = []

    async def add(self, event: SecurityAuditEvent) -> None:
        self.events.append(event)


class FakeCollaborationUnitOfWork:
    def __init__(
        self,
        *,
        collaboration: FakeCollaborationRepository,
        graphs: FakeSavedGraphRepository,
        identity: FakeIdentityRepository,
        security_audit: FakeSecurityAuditRepository,
        commit_error: ConcurrentWriteError | None = None,
    ) -> None:
        self.collaboration = collaboration
        self.graphs = graphs
        self.node_secrets = FakeNodeSecretRepository()
        self.identity = identity
        self.security_audit = security_audit
        self._commit_error = commit_error
        self.commit_count = 0
        self.rollback_count = 0
        self._snapshot: dict[str, object] | None = None

    async def __aenter__(self) -> Self:
        self._snapshot = self._capture_state()
        self.collaboration.graphs_by_id = self.graphs.graphs
        return self

    def _capture_state(self) -> dict[str, object]:
        return {
            "heads": {
                key: _clone_head(head)
                for key, head in self.collaboration.heads.items()
            },
            "receipts": {
                key: receipt.model_copy(deep=True)
                for key, receipt in self.collaboration.receipts.items()
            },
            "journal": [
                entry.model_copy(deep=True) for entry in self.collaboration.journal
            ],
            "mappings": {
                key: mapping.model_copy(deep=True)
                for key, mapping in self.collaboration.mappings.items()
            },
            "active_slots": {
                key: slot.model_copy(deep=True)
                for key, slot in self.collaboration.active_slots.items()
            },
            "graphs": {
                key: _clone_graph(graph) for key, graph in self.graphs.graphs.items()
            },
            "revisions": {
                key: _clone_revision(revision)
                for key, revision in self.graphs.revisions.items()
            },
            "audit": list(self.security_audit.events),
        }

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.commit_count += 1
        if self._commit_error is not None:
            raise self._commit_error
        self._snapshot = self._capture_state()

    async def rollback(self) -> None:
        self.rollback_count += 1
        if self._snapshot is None:
            return
        heads = {
            key: _clone_head(head)
            for key, head in self._snapshot["heads"].items()  # type: ignore[union-attr]
        }
        self.collaboration.heads = heads
        self.collaboration.receipts = {
            key: receipt.model_copy(deep=True)
            for key, receipt in self._snapshot["receipts"].items()  # type: ignore[union-attr]
        }
        self.collaboration.journal = [
            entry.model_copy(deep=True)
            for entry in self._snapshot["journal"]  # type: ignore[union-attr]
        ]
        self.collaboration.mappings = {
            key: mapping.model_copy(deep=True)
            for key, mapping in self._snapshot["mappings"].items()  # type: ignore[union-attr]
        }
        self.collaboration.active_slots = {
            key: slot.model_copy(deep=True)
            for key, slot in self._snapshot["active_slots"].items()  # type: ignore[union-attr]
        }
        self.graphs.graphs = {
            key: _clone_graph(graph)
            for key, graph in self._snapshot["graphs"].items()  # type: ignore[union-attr]
        }
        self.graphs.revisions = {
            key: _clone_revision(revision)
            for key, revision in self._snapshot["revisions"].items()  # type: ignore[union-attr]
        }
        self.security_audit.events = list(
            self._snapshot["audit"]  # type: ignore[arg-type]
        )
        self.collaboration.graphs_by_id = self.graphs.graphs


def _clone_head(head: CollaborativeGraphHead) -> CollaborativeGraphHead:
    return CollaborativeGraphHead(
        workspace_id=head.workspace_id,
        graph_id=head.graph_id,
        room_epoch=head.room_epoch,
        collaboration_sequence=head.collaboration_sequence,
        checkpoint_sequence=head.checkpoint_sequence,
        checkpoint_revision=head.checkpoint_revision,
        name=head.name,
        document=SavedGraphDocument.model_validate(head.document.model_dump(mode="json")),
        updated_at=head.updated_at,
    )


def _clone_graph(graph: SavedGraph) -> SavedGraph:
    return SavedGraph(
        workspace_id=graph.workspace_id,
        created_by_user_id=graph.created_by_user_id,
        id=graph.id,
        name=graph.name,
        document=SavedGraphDocument.model_validate(graph.document.model_dump(mode="json")),
        revision=graph.revision,
        created_at=graph.created_at,
        updated_at=graph.updated_at,
    )


def _clone_revision(revision: SavedGraphRevision) -> SavedGraphRevision:
    return SavedGraphRevision(
        workspace_id=revision.workspace_id,
        graph_id=revision.graph_id,
        revision=revision.revision,
        name=revision.name,
        document=SavedGraphDocument.model_validate(
            revision.document.model_dump(mode="json")
        ),
        created_at=revision.created_at,
    )


TARGET_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000301")


class FakeFactory:
    def __init__(self, role: WorkspaceRole = WorkspaceRole.OWNER) -> None:
        self.user = User(id=USER_ID, email="editor@example.com", display_name="Editor")
        self.workspace = Workspace.shared(slug="phase3", name="Phase 3")
        self.workspace.id = WORKSPACE_ID
        self.membership = WorkspaceMembership(
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            role=role,
        )
        self.target_membership = WorkspaceMembership(
            workspace_id=TARGET_WORKSPACE_ID,
            user_id=USER_ID,
            role=role,
        )
        self.collaboration = FakeCollaborationRepository()
        self.graphs = FakeSavedGraphRepository()
        self.collaboration.graphs_by_id = self.graphs.graphs
        self.security_audit = FakeSecurityAuditRepository()
        self.identity = FakeIdentityRepository(
            self.user,
            [self.membership, self.target_membership],
        )
        self.commit_error: ConcurrentWriteError | None = None
        self.created: list[FakeCollaborationUnitOfWork] = []

    def __call__(self) -> FakeCollaborationUnitOfWork:
        unit = FakeCollaborationUnitOfWork(
            collaboration=self.collaboration,
            graphs=self.graphs,
            identity=self.identity,
            security_audit=self.security_audit,
            commit_error=self.commit_error,
        )
        self.created.append(unit)
        return unit


def _service(factory: FakeFactory) -> CollaborationService:
    return CollaborationService(
        factory,
        PluginRegistry(),
        command_hmac_key=HMAC_KEY,
        command_hmac_key_version=1,
    )


@pytest.mark.asyncio
async def test_initialize_head_for_existing_graph_is_idempotent() -> None:
    factory = FakeFactory()
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=USER_ID,
        name="Legacy",
        document=SavedGraphDocument(),
        revision=3,
    )
    factory.graphs.graphs[graph.id] = graph
    service = _service(factory)

    first = await service.initialize_head_for_existing_graph(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
    )
    second = await service.initialize_head_for_existing_graph(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
    )

    assert first.collaboration_sequence == 0
    assert first.checkpoint_revision == 3
    assert second.room_epoch == first.room_epoch
    assert factory.created[0].commit_count == 1
    assert factory.created[1].commit_count == 0


@pytest.mark.asyncio
async def test_bootstrap_graph_commits_head_checkpoint_and_receipt() -> None:
    factory = FakeFactory()
    service = _service(factory)
    command_id = uuid4()
    graph_id = uuid4()
    command = ReplaceDocumentCommand(
        name="Bootstrapped",
        document=SavedGraphDocument(
            nodes=(
                SavedGraphNode(
                    id="n1",
                    operator_id="example.operator",
                    operator_version=1,
                    position=GraphPoint(x=1, y=2),
                ),
            )
        ),
    )

    graph, head, receipt = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=command_id,
        command=command,
        graph_id=graph_id,
    )

    assert graph.id == graph_id
    assert graph.revision == 1
    assert head.collaboration_sequence == 1
    assert head.checkpoint_sequence == 1
    assert head.checkpoint_revision == 1
    assert receipt.outcome is CommandReceiptOutcome.ACCEPTED
    assert factory.collaboration.journal[0].accepted_sequence == 1
    assert (WORKSPACE_ID, graph_id, head.room_epoch, 1) in factory.collaboration.mappings
    assert factory.created[-1].commit_count == 1


@pytest.mark.asyncio
async def test_accept_command_advances_sequence_without_checkpoint() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )

    updated_head, receipt = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=head.collaboration_sequence,
        observed_room_epoch=head.room_epoch,
        command=RenameGraphCommand(name="Renamed", expected_name="Draft"),
    )

    assert updated_head.collaboration_sequence == 2
    assert updated_head.checkpoint_sequence == 1
    assert updated_head.name == "Renamed"
    assert receipt.accepted_sequence == 2
    assert factory.graphs.graphs[graph_id].revision == 1


@pytest.mark.asyncio
async def test_accept_operator_promotion_is_journaled_as_one_cas_command() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    node = SavedGraphNode(
        id="generated",
        operator_id="generated.node.00000000-0000-0000-0000-000000000321",
        operator_version=1,
        position=GraphPoint(x=120, y=80),
        config={"mode": "strict"},
    )
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(
            name="Draft",
            document=SavedGraphDocument(nodes=(node,)),
        ),
        graph_id=graph_id,
    )
    journal_before = len(factory.collaboration.journal)
    observed_sequence = head.collaboration_sequence

    updated, receipt = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=observed_sequence,
        observed_room_epoch=head.room_epoch,
        command=UpdateNodeOperatorCommand(
            node_id=node.id,
            operator_id=node.operator_id,
            operator_version=2,
            expected_operator_id=node.operator_id,
            expected_operator_version=1,
        ),
    )

    promoted = updated.document.nodes[0]
    assert promoted.operator_version == 2
    assert promoted.id == node.id
    assert promoted.config == node.config
    assert promoted.position == node.position
    assert receipt.accepted_sequence == observed_sequence + 1
    assert len(factory.collaboration.journal) == journal_before + 1
    assert factory.collaboration.journal[-1].command_kind is (
        GraphCommandKind.UPDATE_NODE_OPERATOR
    )


@pytest.mark.asyncio
async def test_accept_batch_advances_sequence_once_and_journals_one_command() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    source = SavedGraphNode(
        id="source",
        operator_id="example.source",
        operator_version=1,
        position=GraphPoint(x=0, y=0),
    )
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(
            name="Draft",
            document=SavedGraphDocument(nodes=(source,)),
        ),
        graph_id=graph_id,
    )
    observed_sequence = head.collaboration_sequence
    generated = SavedGraphNode(
        id="generated",
        operator_id="agent.draft.test",
        operator_version=1,
        position=GraphPoint(x=240, y=0),
    )

    updated_head, receipt = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=observed_sequence,
        observed_room_epoch=head.room_epoch,
        command=ApplyGraphCommandBatch(
            commands=(
                AddNodeCommand(node=generated),
                AddEdgeCommand(
                    edge=SavedGraphEdge(
                        id="source-to-generated",
                        from_node="source",
                        from_port="result",
                        to_node="generated",
                        to_port="value",
                    )
                ),
            )
        ),
    )

    assert updated_head.collaboration_sequence == observed_sequence + 1
    assert receipt.accepted_sequence == observed_sequence + 1
    assert [node.id for node in updated_head.document.nodes] == [
        "source",
        "generated",
    ]
    assert [edge.id for edge in updated_head.document.edges] == ["source-to-generated"]
    assert (
        factory.collaboration.journal[-1].command_kind is GraphCommandKind.APPLY_BATCH
    )
    commands_payload = factory.collaboration.journal[-1].command_payload["commands"]
    assert isinstance(commands_payload, list)
    assert len(commands_payload) == 2
    assert factory.created[-1].commit_count == 1


@pytest.mark.asyncio
async def test_accept_batch_rejects_stale_observed_sequence() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    stale_sequence = head.collaboration_sequence
    room_epoch = head.room_epoch
    await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=stale_sequence,
        observed_room_epoch=room_epoch,
        command=RenameGraphCommand(name="Concurrent edit", expected_name="Draft"),
    )

    with pytest.raises(CollaborationHeadConflictError):
        await service.accept_command(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            command_id=uuid4(),
            observed_sequence=stale_sequence,
            observed_room_epoch=room_epoch,
            command=ApplyGraphCommandBatch(
                commands=(
                    AddNodeCommand(
                        node=SavedGraphNode(
                            id="generated",
                            operator_id="agent.draft.test",
                            operator_version=1,
                            position=GraphPoint(x=0, y=0),
                        )
                    ),
                )
            ),
        )


@pytest.mark.asyncio
async def test_accept_command_in_caller_unit_of_work_does_not_commit() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    unit_of_work = factory()

    async with unit_of_work:
        updated_head, receipt = await service.accept_command_in_unit_of_work(
            cast(CollaborationUnitOfWorkPort, unit_of_work),
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            command_id=uuid4(),
            observed_sequence=head.collaboration_sequence,
            observed_room_epoch=head.room_epoch,
            command=RenameGraphCommand(name="Atomic caller", expected_name="Draft"),
        )

        assert updated_head.name == "Atomic caller"
        assert receipt.outcome is CommandReceiptOutcome.ACCEPTED
        assert unit_of_work.commit_count == 0
        assert factory.collaboration.journal[-1].command_payload["name"] == (
            "Atomic caller"
        )
        await unit_of_work.commit()

    assert unit_of_work.commit_count == 1


@pytest.mark.asyncio
async def test_accept_command_idempotent_replay_and_mismatch() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    command_id = uuid4()
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    command = RenameGraphCommand(name="Once", expected_name="Draft")
    observed_sequence = head.collaboration_sequence
    observed_room_epoch = head.room_epoch
    first_head, first_receipt = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=command_id,
        observed_sequence=observed_sequence,
        observed_room_epoch=observed_room_epoch,
        command=command,
    )
    replay_head, replay_receipt = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=command_id,
        observed_sequence=observed_sequence,
        observed_room_epoch=observed_room_epoch,
        command=command,
    )

    assert first_head.collaboration_sequence == replay_head.collaboration_sequence == 2
    assert replay_receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY
    assert first_receipt.outcome is CommandReceiptOutcome.ACCEPTED

    with pytest.raises(CollaborationIdempotencyMismatchError):
        await service.accept_command(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            command_id=command_id,
            observed_sequence=observed_sequence,
            observed_room_epoch=observed_room_epoch,
            command=RenameGraphCommand(name="Different", expected_name="Draft"),
        )


@pytest.mark.asyncio
async def test_checkpoint_advances_saved_revision_and_preserves_secrets() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    head, _ = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=head.collaboration_sequence,
        observed_room_epoch=head.room_epoch,
        command=RenameGraphCommand(name="Checkpoint me", expected_name="Draft"),
    )

    checkpointed_head, revision = await service.checkpoint(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        expected_sequence=head.collaboration_sequence,
        expected_room_epoch=head.room_epoch,
    )

    assert revision == 2
    assert checkpointed_head.checkpoint_sequence == 2
    assert checkpointed_head.checkpoint_revision == 2
    assert factory.graphs.graphs[graph_id].name == "Checkpoint me"
    assert factory.graphs.revisions[(graph_id, 2)].name == "Checkpoint me"


@pytest.mark.asyncio
async def test_accept_command_requires_existing_head() -> None:
    factory = FakeFactory()
    service = _service(factory)
    with pytest.raises(MissingCollaborativeHeadError):
        await service.accept_command(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=uuid4(),
            command_id=uuid4(),
            observed_sequence=0,
            observed_room_epoch=uuid4(),
            command=RenameGraphCommand(name="Nope", expected_name="Nope"),
        )


@pytest.mark.asyncio
async def test_replace_complete_document_resets_epoch_when_checkpointed() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    graph, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Original", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    prior_epoch = head.room_epoch

    replaced, new_head = await service.replace_complete_document(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        name="Replaced",
        document=SavedGraphDocument(
            nodes=(
                SavedGraphNode(
                    id="n1",
                    operator_id="example.operator",
                    operator_version=1,
                    position=GraphPoint(x=3, y=4),
                ),
            )
        ),
        expected_revision=graph.revision,
    )

    assert replaced.revision == 2
    assert replaced.name == "Replaced"
    assert new_head.room_epoch != prior_epoch
    assert new_head.collaboration_sequence == 0
    assert new_head.checkpoint_sequence == 0
    assert new_head.checkpoint_revision == 2
    assert factory.collaboration.journal == []
    assert (WORKSPACE_ID, graph_id, new_head.room_epoch, 0) in (
        factory.collaboration.mappings
    )

    after_replace, receipt = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=0,
        observed_room_epoch=new_head.room_epoch,
        command=RenameGraphCommand(name="After replace", expected_name="Replaced"),
    )
    assert receipt.outcome is CommandReceiptOutcome.ACCEPTED
    assert after_replace.collaboration_sequence == 1
    assert after_replace.name == "After replace"


@pytest.mark.asyncio
async def test_replace_complete_document_rejects_uncheckpointed_head() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    graph, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=head.collaboration_sequence,
        observed_room_epoch=head.room_epoch,
        command=RenameGraphCommand(name="Uncheckpointed", expected_name="Draft"),
    )

    with pytest.raises(CollaborationUncheckpointedError):
        await service.replace_complete_document(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            name="Nope",
            document=SavedGraphDocument(),
            expected_revision=graph.revision,
        )


@pytest.mark.asyncio
async def test_delete_graph_removes_head_and_graph() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    graph, _, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Delete me", document=SavedGraphDocument()),
        graph_id=graph_id,
    )

    await service.delete_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        expected_revision=graph.revision,
    )

    assert graph_id not in factory.graphs.graphs
    assert (WORKSPACE_ID, graph_id) not in factory.collaboration.heads


@pytest.mark.asyncio
async def test_delete_graph_rejects_uncheckpointed_legacy_delete() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    graph, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=head.collaboration_sequence,
        observed_room_epoch=head.room_epoch,
        command=RenameGraphCommand(name="Pending", expected_name="Draft"),
    )

    with pytest.raises(CollaborationUncheckpointedError):
        await service.delete_graph(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            expected_revision=graph.revision,
        )


@pytest.mark.asyncio
async def test_delete_graph_rejects_active_execution() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    graph, _, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Busy", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    execution_id = uuid4()
    factory.collaboration.active_slots[(WORKSPACE_ID, graph_id)] = (
        GraphActiveExecutionSlot(
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            execution_id=execution_id,
        )
    )

    with pytest.raises(CollaborationActiveExecutionError):
        await service.delete_graph(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            expected_revision=graph.revision,
        )


@pytest.mark.asyncio
async def test_get_head_returns_live_document() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Live", document=SavedGraphDocument()),
        graph_id=graph_id,
    )

    loaded = await service.get_head(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
    )

    assert loaded.room_epoch == head.room_epoch
    assert loaded.collaboration_sequence == 1
    assert loaded.name == "Live"


@pytest.mark.asyncio
async def test_accept_command_rebases_move_against_newer_head() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    node = SavedGraphNode(
        id="n1",
        operator_id="example.operator",
        operator_version=1,
        position=GraphPoint(x=0, y=0),
    )
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(
            name="Draft",
            document=SavedGraphDocument(nodes=(node,)),
        ),
        graph_id=graph_id,
    )
    observed_sequence = head.collaboration_sequence
    observed_epoch = head.room_epoch
    await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=observed_sequence,
        observed_room_epoch=observed_epoch,
        command=RenameGraphCommand(name="Moved ahead", expected_name="Draft"),
    )

    updated, receipt = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=observed_sequence,
        observed_room_epoch=observed_epoch,
        command=MoveNodesCommand(
            positions=(MoveNodePosition(node_id="n1", x=9, y=8),)
        ),
    )

    assert updated.collaboration_sequence == 3
    assert updated.document.nodes[0].position == GraphPoint(x=9, y=8)
    assert receipt.accepted_sequence == 3


@pytest.mark.asyncio
async def test_accept_command_rejects_stale_rename_with_field_conflict() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    observed_sequence = head.collaboration_sequence
    observed_epoch = head.room_epoch
    await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=observed_sequence,
        observed_room_epoch=observed_epoch,
        command=RenameGraphCommand(name="Other", expected_name="Draft"),
    )

    with pytest.raises(CollaborationCommandRejectedError) as exc:
        await service.accept_command(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            command_id=uuid4(),
            observed_sequence=observed_sequence,
            observed_room_epoch=observed_epoch,
            command=RenameGraphCommand(name="Mine", expected_name="Draft"),
        )
    assert exc.value.error_code == "field_conflict"


@pytest.mark.asyncio
async def test_copy_exact_head_bootstraps_target_without_source_secrets() -> None:
    factory = FakeFactory()
    service = _service(factory)
    source_graph_id = uuid4()
    _, source_head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(
            name="Source",
            document=SavedGraphDocument(
                nodes=(
                    SavedGraphNode(
                        id="n1",
                        operator_id="example.operator",
                        operator_version=1,
                        position=GraphPoint(x=1, y=2),
                        config={
                            "uploads": [
                                {
                                    "upload_key": "x.png",
                                    "filename": "x.png",
                                    "byte_size": 1,
                                }
                            ],
                            "label": "keep",
                        },
                    ),
                )
            ),
        ),
        graph_id=source_graph_id,
    )

    graph, head, receipt = await service.copy_exact_head(
        actor=ActorContext(user_id=USER_ID),
        source_workspace_id=WORKSPACE_ID,
        source_graph_id=source_graph_id,
        target_workspace_id=TARGET_WORKSPACE_ID,
        expected_room_epoch=source_head.room_epoch,
        expected_sequence=source_head.collaboration_sequence,
        command_id=uuid4(),
    )

    assert graph.workspace_id == TARGET_WORKSPACE_ID
    assert graph.revision == 1
    assert head.collaboration_sequence == 1
    assert head.checkpoint_sequence == 1
    assert head.checkpoint_revision == 1
    assert receipt.accepted_sequence == 1
    assert graph.document.nodes[0].config_dict() == {"label": "keep"}
    assert source_graph_id in factory.graphs.graphs
    assert factory.graphs.graphs[source_graph_id].workspace_id == WORKSPACE_ID


@pytest.mark.asyncio
async def test_copy_exact_head_rejects_moved_source() -> None:
    factory = FakeFactory()
    service = _service(factory)
    source_graph_id = uuid4()
    _, source_head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Source", document=SavedGraphDocument()),
        graph_id=source_graph_id,
    )
    expected_room_epoch = source_head.room_epoch
    expected_sequence = source_head.collaboration_sequence
    await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=source_graph_id,
        command_id=uuid4(),
        observed_sequence=expected_sequence,
        observed_room_epoch=expected_room_epoch,
        command=RenameGraphCommand(name="Moved", expected_name="Source"),
    )

    with pytest.raises(CollaborationHeadConflictError):
        await service.copy_exact_head(
            actor=ActorContext(user_id=USER_ID),
            source_workspace_id=WORKSPACE_ID,
            source_graph_id=source_graph_id,
            target_workspace_id=TARGET_WORKSPACE_ID,
            expected_room_epoch=expected_room_epoch,
            expected_sequence=expected_sequence,
            command_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_delete_graph_collaboration_aware_discards_uncheckpointed() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    graph, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    head, _ = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=head.collaboration_sequence,
        observed_room_epoch=head.room_epoch,
        command=RenameGraphCommand(name="Discard", expected_name="Draft"),
    )

    await service.delete_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        expected_revision=graph.revision,
        expected_room_epoch=head.room_epoch,
        expected_sequence=head.collaboration_sequence,
    )

    assert graph_id not in factory.graphs.graphs
    assert (WORKSPACE_ID, graph_id) not in factory.collaboration.heads


@pytest.mark.asyncio
async def test_accept_command_audits_capability_denied_and_idempotency_mismatch() -> None:
    viewer_factory = FakeFactory(role=WorkspaceRole.VIEWER)
    viewer_service = _service(viewer_factory)
    graph_id = uuid4()
    viewer_factory.graphs.graphs[graph_id] = SavedGraph(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=USER_ID,
        id=graph_id,
        name="View only",
        document=SavedGraphDocument(),
        revision=1,
    )
    viewer_factory.collaboration.heads[(WORKSPACE_ID, graph_id)] = (
        CollaborativeGraphHead.for_existing_saved_graph(
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            name="View only",
            document=SavedGraphDocument(),
            checkpoint_revision=1,
        )
    )

    with pytest.raises(CapabilityDeniedError):
        await viewer_service.accept_command(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            command_id=uuid4(),
            observed_sequence=0,
            observed_room_epoch=viewer_factory.collaboration.heads[
                (WORKSPACE_ID, graph_id)
            ].room_epoch,
            command=RenameGraphCommand(name="Nope", expected_name="View only"),
        )

    denied = [
        event
        for event in viewer_factory.security_audit.events
        if event.outcome is SecurityAuditOutcome.FAILURE
    ]
    assert len(denied) == 1
    assert denied[0].operation == "collaboration.command.accept"
    assert denied[0].error_code == "capability_denied"
    assert denied[0].resource_id == str(graph_id)
    assert "Nope" not in repr(denied[0])

    editor_factory = FakeFactory()
    editor_service = _service(editor_factory)
    _, head, _ = await editor_service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    command_id = uuid4()
    await editor_service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=command_id,
        observed_sequence=head.collaboration_sequence,
        observed_room_epoch=head.room_epoch,
        command=RenameGraphCommand(name="Once", expected_name="Draft"),
    )
    with pytest.raises(CollaborationIdempotencyMismatchError):
        await editor_service.accept_command(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            command_id=command_id,
            observed_sequence=head.collaboration_sequence,
            observed_room_epoch=head.room_epoch,
            command=RenameGraphCommand(name="Different", expected_name="Draft"),
        )
    mismatch = [
        event
        for event in editor_factory.security_audit.events
        if event.error_code == "idempotency_mismatch"
    ]
    assert len(mismatch) == 1
    assert mismatch[0].outcome is SecurityAuditOutcome.FAILURE
    assert mismatch[0].operation == "collaboration.command.accept"


@pytest.mark.asyncio
async def test_verify_every_graph_has_head_fails_closed_on_gap() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=USER_ID,
        name="Orphan",
        document=SavedGraphDocument(),
        revision=1,
    )
    factory.graphs.graphs[graph.id] = graph

    with pytest.raises(MissingCollaborativeHeadError):
        await service.verify_every_graph_has_head()

    await service.initialize_head_for_existing_graph(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
    )
    await service.verify_every_graph_has_head()
    again = await service.initialize_head_for_existing_graph(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.id,
    )
    assert again.collaboration_sequence == 0
    assert len(factory.collaboration.heads) == 1


@pytest.mark.asyncio
async def test_checkpoint_commit_failure_rolls_back_partial_state() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    _, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    head, _ = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=head.collaboration_sequence,
        observed_room_epoch=head.room_epoch,
        command=RenameGraphCommand(name="Pending", expected_name="Draft"),
    )
    factory.commit_error = ConcurrentWriteError("checkpoint race")

    with pytest.raises(SavedGraphRevisionConflictError):
        await service.checkpoint(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            expected_sequence=head.collaboration_sequence,
            expected_room_epoch=head.room_epoch,
        )

    restored = factory.collaboration.heads[(WORKSPACE_ID, graph_id)]
    assert restored.checkpoint_sequence == 1
    assert restored.name == "Pending"
    assert factory.graphs.graphs[graph_id].revision == 1
    assert factory.graphs.graphs[graph_id].name == "Draft"
    assert not any(
        key[3] == 2 for key in factory.collaboration.mappings if key[1] == graph_id
    )


@pytest.mark.asyncio
async def test_checkpoint_versus_replace_serializes_without_partial_state() -> None:
    factory = FakeFactory()
    service = _service(factory)
    graph_id = uuid4()
    graph, head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(name="Draft", document=SavedGraphDocument()),
        graph_id=graph_id,
    )
    head, _ = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        command_id=uuid4(),
        observed_sequence=head.collaboration_sequence,
        observed_room_epoch=head.room_epoch,
        command=RenameGraphCommand(name="Uncheckpointed", expected_name="Draft"),
    )

    with pytest.raises(CollaborationUncheckpointedError):
        await service.replace_complete_document(
            actor=ActorContext(user_id=USER_ID),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            name="Replace while dirty",
            document=SavedGraphDocument(),
            expected_revision=graph.revision,
        )

    assert factory.graphs.graphs[graph_id].name == "Draft"
    assert factory.collaboration.heads[(WORKSPACE_ID, graph_id)].name == (
        "Uncheckpointed"
    )

    checkpointed, revision = await service.checkpoint(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        expected_sequence=head.collaboration_sequence,
        expected_room_epoch=head.room_epoch,
    )
    assert checkpointed.checkpoint_sequence == 2
    assert revision == 2
    replaced, new_head = await service.replace_complete_document(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        name="Safe replace",
        document=SavedGraphDocument(),
        expected_revision=revision,
    )

    assert replaced.revision == 3
    assert new_head.collaboration_sequence == 0
    assert new_head.checkpoint_sequence == 0
    assert new_head.name == "Safe replace"


@pytest.mark.asyncio
async def test_workspace_qualified_mutations_leave_no_cross_workspace_state() -> None:
    factory = FakeFactory()
    service = _service(factory)
    source_id = uuid4()
    _, source_head, _ = await service.bootstrap_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        command_id=uuid4(),
        command=ReplaceDocumentCommand(
            name="Source",
            document=SavedGraphDocument(
                nodes=(
                    SavedGraphNode(
                        id="n1",
                        operator_id="example.operator",
                        operator_version=1,
                        position=GraphPoint(x=1, y=1),
                        config={"fields": [{"id": "a", "name": "a", "kind": "string"}]},
                        input_plugs=(SavedGraphInputPlug(id="a", port="schemas"),),
                    ),
                )
            ),
        ),
        graph_id=source_id,
    )
    source_head, _ = await service.accept_command(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=source_id,
        command_id=uuid4(),
        observed_sequence=source_head.collaboration_sequence,
        observed_room_epoch=source_head.room_epoch,
        command=UpdateNodeConfigurationAndInputPlugsCommand(
            node_id="n1",
            config={"fields": []},
            input_plugs=(),
            expected_config={"fields": [{"id": "a", "name": "a", "kind": "string"}]},
            expected_plug_ids=("a",),
        ),
    )
    await service.checkpoint(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=source_id,
        expected_sequence=source_head.collaboration_sequence,
        expected_room_epoch=source_head.room_epoch,
    )
    source_head = factory.collaboration.heads[(WORKSPACE_ID, source_id)]

    copied, copied_head, _ = await service.copy_exact_head(
        actor=ActorContext(user_id=USER_ID),
        source_workspace_id=WORKSPACE_ID,
        source_graph_id=source_id,
        target_workspace_id=TARGET_WORKSPACE_ID,
        expected_room_epoch=source_head.room_epoch,
        expected_sequence=source_head.collaboration_sequence,
        command_id=uuid4(),
    )
    assert copied.workspace_id == TARGET_WORKSPACE_ID
    assert (TARGET_WORKSPACE_ID, copied.id) in factory.collaboration.heads
    assert factory.graphs.graphs[source_id].workspace_id == WORKSPACE_ID
    assert factory.collaboration.heads[(WORKSPACE_ID, source_id)].name == "Source"

    await service.delete_graph(
        actor=ActorContext(user_id=USER_ID),
        workspace_id=WORKSPACE_ID,
        graph_id=source_id,
        expected_revision=factory.graphs.graphs[source_id].revision,
        expected_room_epoch=source_head.room_epoch,
        expected_sequence=source_head.collaboration_sequence,
    )
    assert source_id not in factory.graphs.graphs
    assert (WORKSPACE_ID, source_id) not in factory.collaboration.heads
    assert copied.id in factory.graphs.graphs
    assert factory.graphs.graphs[copied.id].workspace_id == TARGET_WORKSPACE_ID
    assert factory.collaboration.heads[(TARGET_WORKSPACE_ID, copied.id)].room_epoch == (
        copied_head.room_epoch
    )
