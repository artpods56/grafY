"""Focused tests for ``CollaborationService``: head, batches, checkpoints, copies.

Run with ``--noconftest``: this file builds its own fakes from
``tests/unit/application/project_fakes.py`` and expects nothing from shared fixtures.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from tests.unit.application.project_fakes import (
    IdentityDirectory,
    ProjectStore,
    ProjectUnitOfWorkFactory,
    new_member,
)

from grafy_core.application.collaboration import (
    CheckpointOutcome,
    CollaborationService,
    CommandSubmission,
)
from grafy_core.domain.collaboration import (
    AddGraphCommand,
    AddNodeCommand,
    CollaborationActorKind,
    CommandReceiptOutcome,
    InGraphCommand,
    ProjectCommand,
    RenameGraphCommand,
    RenameProjectCommand,
    ReplaceDocumentCommand,
)
from grafy_core.domain.errors import (
    CapabilityDeniedError,
    CollaborationCommandRejectedError,
    CollaborationError,
    CollaborationHeadConflictError,
    CollaborationIdempotencyMismatchError,
    CollaborationUncheckpointedError,
    MissingProjectHeadError,
    NotFoundError,
    ProjectCheckpointConflictError,
)
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphNode,
    GraphPoint,
)
from grafy_core.domain.identity import (
    ActorContext,
    User,
    Workspace,
    WorkspaceRole,
)
from grafy_core.domain.projects import ProjectCheckpoint
from grafy_core.kernel.project import ProjectDocument

HMAC_KEY = b"test-project-command-hmac-key"
HMAC_KEY_VERSION = 3


def actor_for(user: User) -> ActorContext:
    return ActorContext(user_id=user.id, credential_reference="session:test")


def node(node_id: str, **config: object) -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id="demo.echo",
        operator_version=1,
        position=GraphPoint(x=8, y=12),
        config=dict(config),
    )


def add_node(
    node_id: str, *, graph_id: str = "main", **config: object
) -> ProjectCommand:
    return InGraphCommand(
        graph_id=graph_id,
        command=AddNodeCommand(node=node(node_id, **config)),
    )


@dataclass
class Harness:
    directory: IdentityDirectory
    store: ProjectStore
    factory: ProjectUnitOfWorkFactory
    service: CollaborationService

    def workspace(
        self,
        *,
        name: str,
        slug: str,
        role: WorkspaceRole = WorkspaceRole.OWNER,
    ) -> tuple[Workspace, ActorContext]:
        workspace, user = new_member(
            self.directory, display_name=name, slug=slug, role=role
        )
        self.store.seed_location(workspace)
        return workspace, actor_for(user)

    def add_member(
        self,
        workspace: Workspace,
        *,
        name: str,
        role: WorkspaceRole,
    ) -> ActorContext:
        user = self.directory.add_user(User(display_name=name))
        self.directory.grant(workspace_id=workspace.id, user_id=user.id, role=role)
        return actor_for(user)

    def join(
        self,
        workspace: Workspace,
        actor: ActorContext,
        *,
        role: WorkspaceRole,
    ) -> ActorContext:
        """Give an existing member a role in another Workspace (a copy needs both)."""

        self.directory.grant(
            workspace_id=workspace.id, user_id=actor.user_id, role=role
        )
        return actor

    def create(
        self,
        actor: ActorContext,
        workspace: Workspace,
        *,
        name: str = "Field survey",
        graph_id: str = "main",
        graph_name: str = "Main",
        project_id: UUID | None = None,
        command_id: UUID | None = None,
    ):
        return self.service.create_project(
            actor=actor,
            workspace_id=workspace.id,
            name=name,
            graph_id=graph_id,
            graph_name=graph_name,
            project_id=project_id,
            command_id=command_id,
        )

    def submit(
        self,
        actor: ActorContext,
        workspace: Workspace,
        project_id: UUID,
        commands: list[ProjectCommand],
        *,
        observed_sequence: int | None = None,
        observed_room_epoch: UUID | None = None,
        command_id: UUID | None = None,
    ):
        head = self.store.head_for(workspace.id, project_id)
        return self.service.submit_commands(
            actor=actor,
            workspace_id=workspace.id,
            project_id=project_id,
            command_id=uuid4() if command_id is None else command_id,
            observed_sequence=(
                head.collaboration_sequence
                if observed_sequence is None
                else observed_sequence
            ),
            observed_room_epoch=(
                head.room_epoch if observed_room_epoch is None else observed_room_epoch
            ),
            commands=commands,
        )

    def checkpoint(
        self,
        actor: ActorContext,
        workspace: Workspace,
        project_id: UUID,
        *,
        expected_sequence: int | None = None,
        expected_room_epoch: UUID | None = None,
    ):
        head = self.store.head_for(workspace.id, project_id)
        return self.service.checkpoint(
            actor=actor,
            workspace_id=workspace.id,
            project_id=project_id,
            expected_sequence=(
                head.collaboration_sequence
                if expected_sequence is None
                else expected_sequence
            ),
            expected_room_epoch=(
                head.room_epoch if expected_room_epoch is None else expected_room_epoch
            ),
        )

    def restore(
        self,
        self_actor: ActorContext,
        workspace: Workspace,
        project_id: UUID,
        revision: int,
        *,
        expected_sequence: int | None = None,
        expected_room_epoch: UUID | None = None,
    ):
        head = self.store.head_for(workspace.id, project_id)
        return self.service.restore_checkpoint(
            actor=self_actor,
            workspace_id=workspace.id,
            project_id=project_id,
            revision=revision,
            expected_sequence=(
                head.collaboration_sequence
                if expected_sequence is None
                else expected_sequence
            ),
            expected_room_epoch=(
                head.room_epoch if expected_room_epoch is None else expected_room_epoch
            ),
        )

    def revisions(self, project_id: UUID) -> list[int]:
        return sorted(
            revision
            for (owned_project, revision) in self.store.checkpoints
            if owned_project == project_id
        )

    def checkpoint_document(self, project_id: UUID, revision: int) -> ProjectDocument:
        return self.store.checkpoints[(project_id, revision)].document

    @property
    def audits(self):
        return self.store.audit


@pytest.fixture
def harness() -> Harness:
    directory = IdentityDirectory()
    store = ProjectStore(directory)
    factory = ProjectUnitOfWorkFactory(store)
    return Harness(
        directory=directory,
        store=store,
        factory=factory,
        service=CollaborationService(
            factory,
            command_hmac_key=HMAC_KEY,
            command_hmac_key_version=HMAC_KEY_VERSION,
        ),
    )


async def test_service_requires_a_usable_hmac_key() -> None:
    store = ProjectStore(IdentityDirectory())
    factory = ProjectUnitOfWorkFactory(store)
    with pytest.raises(ValueError):
        CollaborationService(factory, command_hmac_key=b"", command_hmac_key_version=1)
    with pytest.raises(ValueError):
        CollaborationService(
            factory, command_hmac_key=HMAC_KEY, command_hmac_key_version=0
        )


async def test_create_project_stages_identity_checkpoint_and_head(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")

    project, head, receipt = await harness.create(owner, workspace, name="Field survey")

    assert receipt is None
    assert project.workspace_id == workspace.id
    assert project.created_by_user_id == owner.user_id
    assert head.project_id == project.id
    assert head.name == "Field survey"
    assert head.collaboration_sequence == 0
    assert head.checkpoint_sequence == 0
    assert head.checkpoint_revision == 1
    assert head.is_fully_checkpointed is True
    assert [graph.id for graph in head.document.graphs] == ["main"]
    assert [graph.name for graph in head.document.graphs] == ["Main"]

    checkpoint = harness.store.checkpoints[(project.id, 1)]
    assert checkpoint.name == "Field survey"
    assert checkpoint.document == head.document
    mapping = harness.store.mappings[(workspace.id, project.id, head.room_epoch, 0)]
    assert mapping.checkpoint_revision == 1
    assert harness.store.receipts == {}
    assert [event.operation for event in harness.audits] == [
        "collaboration.project.create"
    ]
    assert harness.factory.secrets_touched is False


async def test_create_project_names_the_opening_graph_when_asked(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")

    project, head, _ = await harness.create(
        owner,
        workspace,
        name="Field survey",
        graph_id="first",
        graph_name="First transect",
    )

    assert [graph.id for graph in head.document.graphs] == ["first"]
    assert [graph.name for graph in head.document.graphs] == ["First transect"]
    assert harness.checkpoint_document(project.id, 1) == head.document


async def test_create_project_replays_the_same_command_id(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project_id, command_id = uuid4(), uuid4()

    created = await harness.create(
        owner,
        workspace,
        name="Field survey",
        project_id=project_id,
        command_id=command_id,
    )
    replayed = await harness.create(
        owner,
        workspace,
        name="Field survey",
        project_id=project_id,
        command_id=command_id,
    )

    assert created.receipt is not None
    assert created.receipt.outcome is CommandReceiptOutcome.ACCEPTED
    assert created.receipt.accepted_sequence == 0
    assert created.receipt.actor_user_id == owner.user_id
    assert created.receipt.actor_kind is CollaborationActorKind.USER
    assert replayed.receipt is not None
    assert replayed.project.id == created.project.id
    assert replayed.head.collaboration_sequence == 0
    assert replayed.receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY
    assert replayed.receipt.command_hmac == created.receipt.command_hmac
    assert list(harness.store.projects) == [project_id]
    assert harness.revisions(project_id) == [1]


async def test_reused_command_id_with_another_name_is_refused(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project_id, command_id = uuid4(), uuid4()
    await harness.create(
        owner,
        workspace,
        name="Field survey",
        project_id=project_id,
        command_id=command_id,
    )

    with pytest.raises(CollaborationIdempotencyMismatchError):
        await harness.create(
            owner,
            workspace,
            name="Something else",
            project_id=project_id,
            command_id=command_id,
        )

    assert list(harness.store.projects) == [project_id]
    assert harness.store.head_for(workspace.id, project_id).name == "Field survey"
    failures = [event for event in harness.audits if event.error_code is not None]
    assert [(event.operation, event.error_code) for event in failures] == [
        ("collaboration.project.create", "idempotency_mismatch")
    ]


async def test_command_id_without_a_project_id_is_refused(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")

    with pytest.raises(ValueError):
        await harness.create(owner, workspace, command_id=uuid4())

    assert harness.factory.opened == []


async def test_viewer_and_stranger_cannot_open_a_project(harness: Harness) -> None:
    workspace, _ = harness.workspace(name="Owner", slug="owner")
    viewer = harness.add_member(workspace, name="Viewer", role=WorkspaceRole.VIEWER)
    _, stranger = harness.workspace(name="Stranger", slug="stranger")

    with pytest.raises(CapabilityDeniedError):
        await harness.create(viewer, workspace)
    with pytest.raises(NotFoundError):
        await harness.create(stranger, workspace)

    assert harness.store.projects == {}
    assert harness.store.heads == {}
    assert [(event.operation, event.error_code) for event in harness.audits] == [
        ("collaboration.project.create", "capability_denied"),
        ("collaboration.project.create", "not_found"),
    ]


async def test_get_head_reads_the_draft_in_the_owning_workspace(
    harness: Harness,
) -> None:
    theirs, other = harness.workspace(name="Theirs", slug="theirs")
    foreign_project, head, _ = await harness.create(other, theirs, name="Not yours")

    await harness.submit(other, theirs, foreign_project.id, [add_node("node-1")])

    draft = await harness.service.get_head(
        actor=other, workspace_id=theirs.id, project_id=foreign_project.id
    )
    assert draft.collaboration_sequence == 1
    assert draft.room_epoch == head.room_epoch
    assert [node.id for node in draft.document.graphs[0].document.nodes] == ["node-1"]


async def test_a_project_of_another_workspace_is_no_room_at_all(
    harness: Harness,
) -> None:
    """Membership of a Workspace buys nothing in another one.

    The Project id alone is not an address: the head is keyed by Workspace and Project,
    so the same id in a Workspace that does not own it has no room and no draft.
    """

    mine, owner = harness.workspace(name="Mine", slug="mine")
    theirs, other = harness.workspace(name="Theirs", slug="theirs")
    foreign_project, foreign_head, _ = await harness.create(
        other, theirs, name="Not yours"
    )

    with pytest.raises(NotFoundError):
        await harness.service.submit_commands(
            actor=owner,
            workspace_id=mine.id,
            project_id=foreign_project.id,
            command_id=uuid4(),
            observed_sequence=0,
            observed_room_epoch=foreign_head.room_epoch,
            commands=[add_node("node-1")],
        )
    with pytest.raises(NotFoundError):
        await harness.service.get_head(
            actor=owner, workspace_id=mine.id, project_id=foreign_project.id
        )

    assert harness.store.heads == {(theirs.id, foreign_project.id): foreign_head}
    assert harness.store.receipts == {}


async def test_get_head_of_a_project_without_a_head_reports_missing(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    harness.store.heads.pop((workspace.id, project.id))
    del head

    with pytest.raises(MissingProjectHeadError):
        await harness.service.get_head(
            actor=owner, workspace_id=workspace.id, project_id=project.id
        )


async def test_accepted_batch_advances_the_sequence_once(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    command_id = uuid4()

    submission = await harness.submit(
        owner,
        workspace,
        project.id,
        [
            AddGraphCommand(graph_id="branch", name="Branch"),
            add_node("node-1"),
            RenameGraphCommand(
                graph_id="branch", name="Branch 2", expected_name="Branch"
            ),
        ],
        command_id=command_id,
    )

    assert isinstance(submission, CommandSubmission)
    assert submission.head.collaboration_sequence == 1
    assert submission.head.checkpoint_sequence == 0
    assert submission.head.checkpoint_revision == 1
    assert submission.head.room_epoch == head.room_epoch
    assert [graph.id for graph in submission.head.document.graphs] == ["main", "branch"]
    assert [graph.name for graph in submission.head.document.graphs] == [
        "Main",
        "Branch 2",
    ]
    assert [node.id for node in submission.head.document.graphs[0].document.nodes] == [
        "node-1"
    ]
    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.collaboration_sequence == 1
    receipt = harness.store.receipts[(workspace.id, project.id, command_id)]
    assert receipt.outcome is CommandReceiptOutcome.ACCEPTED
    assert receipt.accepted_sequence == 1
    assert receipt.hmac_key_version == HMAC_KEY_VERSION
    assert [event.operation for event in harness.audits] == [
        "collaboration.project.create",
        "collaboration.command.submit",
    ]


async def test_rejected_batch_leaves_the_head_and_receipt_untouched(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)

    with pytest.raises(CollaborationCommandRejectedError) as raised:
        await harness.submit(
            owner,
            workspace,
            project.id,
            [
                add_node("node-1"),
                AddGraphCommand(graph_id="main", name="Clash"),
            ],
        )

    assert raised.value.error_code == "duplicate_graph"
    assert "index 1" in str(raised.value)
    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.collaboration_sequence == head.collaboration_sequence == 0
    assert committed.document == head.document
    assert harness.store.receipts == {}
    assert harness.factory.last.commit_count == 0
    assert harness.revisions(project.id) == [1]


async def test_compare_and_set_conflict_names_the_field_that_moved(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)

    with pytest.raises(CollaborationCommandRejectedError) as raised:
        await harness.submit(
            owner,
            workspace,
            project.id,
            [RenameProjectCommand(name="Renamed", expected_name="Stale name")],
        )

    assert raised.value.error_code == "field_conflict"
    assert harness.store.head_for(workspace.id, project.id).name == "Field survey"


async def test_empty_batch_is_refused_without_opening_a_transaction(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    opened = len(harness.factory.opened)

    with pytest.raises(CollaborationCommandRejectedError) as raised:
        await harness.submit(owner, workspace, project.id, [])

    assert raised.value.error_code == "empty_batch"
    assert len(harness.factory.opened) == opened


async def test_retry_of_an_accepted_batch_replays_the_receipt(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    command_id = uuid4()
    commands = [add_node("node-1"), AddGraphCommand(graph_id="branch", name="Branch")]

    accepted = await harness.submit(
        owner,
        workspace,
        project.id,
        commands,
        command_id=command_id,
        observed_sequence=0,
        observed_room_epoch=head.room_epoch,
    )
    replayed = await harness.submit(
        owner,
        workspace,
        project.id,
        commands,
        command_id=command_id,
        observed_sequence=0,
        observed_room_epoch=head.room_epoch,
    )

    assert accepted.receipt.outcome is CommandReceiptOutcome.ACCEPTED
    assert replayed.receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY
    assert replayed.receipt.command_id == command_id
    assert replayed.receipt.accepted_sequence == 1
    assert replayed.head.collaboration_sequence == 1
    assert replayed.head.room_epoch == head.room_epoch
    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.collaboration_sequence == 1
    assert len(harness.store.receipts) == 1


async def test_the_same_command_id_arriving_twice_is_accepted_once_and_replayed(
    harness: Harness,
) -> None:
    # A client that retries without waiting sends one command id twice at once. Both
    # read "no receipt" before either holds the head, so only the re-read taken under
    # the row lock can tell the loser that the batch is already in.
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    command_id = uuid4()
    batch = [add_node("node-1")]
    harness.store.gate("lock_head", parties=2)

    def send():
        return harness.submit(
            owner,
            workspace,
            project.id,
            list(batch),
            command_id=command_id,
            observed_sequence=0,
            observed_room_epoch=head.room_epoch,
        )

    first, second = await asyncio.gather(send(), send())

    assert {first.receipt.outcome, second.receipt.outcome} == {
        CommandReceiptOutcome.ACCEPTED,
        CommandReceiptOutcome.IDEMPOTENT_REPLAY,
    }
    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.collaboration_sequence == 1
    assert len(harness.store.receipts) == 1


async def test_reused_command_id_with_another_batch_is_refused(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    command_id = uuid4()
    await harness.submit(
        owner,
        workspace,
        project.id,
        [add_node("node-1")],
        observed_sequence=0,
        observed_room_epoch=head.room_epoch,
        command_id=command_id,
    )

    with pytest.raises(CollaborationIdempotencyMismatchError):
        await harness.submit(
            owner,
            workspace,
            project.id,
            [add_node("node-2")],
            observed_sequence=0,
            observed_room_epoch=head.room_epoch,
            command_id=command_id,
        )

    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.collaboration_sequence == 1
    assert [node.id for node in committed.document.graphs[0].document.nodes] == [
        "node-1"
    ]
    failures = [event for event in harness.audits if event.error_code is not None]
    assert [(event.operation, event.error_code) for event in failures] == [
        ("collaboration.command.submit", "idempotency_mismatch")
    ]


async def test_a_stale_room_epoch_is_a_head_conflict(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)

    with pytest.raises(CollaborationHeadConflictError) as raised:
        await harness.submit(
            owner,
            workspace,
            project.id,
            [add_node("node-1")],
            observed_room_epoch=uuid4(),
        )

    assert raised.value.actual_sequence == head.collaboration_sequence == 0
    assert raised.value.room_epoch == head.room_epoch
    assert harness.store.receipts == {}
    assert [(event.operation, event.error_code) for event in harness.audits] == [
        ("collaboration.project.create", None),
        ("collaboration.head.conflict", "head_moved"),
    ]


async def test_an_observed_sequence_ahead_of_the_head_is_a_conflict(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)

    with pytest.raises(CollaborationHeadConflictError) as raised:
        await harness.submit(
            owner,
            workspace,
            project.id,
            [add_node("node-1")],
            observed_sequence=4,
        )

    assert (raised.value.expected_sequence, raised.value.actual_sequence) == (4, 0)


async def test_whole_document_replace_is_refused_behind_the_head(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])
    stale_graph = GraphDocument()

    with pytest.raises(CollaborationHeadConflictError):
        await harness.submit(
            owner,
            workspace,
            project.id,
            [
                InGraphCommand(
                    graph_id="main",
                    command=ReplaceDocumentCommand(document=stale_graph),
                )
            ],
            observed_sequence=0,
        )

    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.collaboration_sequence == 1
    assert [node.id for node in committed.document.graphs[0].document.nodes] == [
        "node-1"
    ]

    # Read at the current sequence, the same wholesale replace is accepted.
    accepted = await harness.submit(
        owner,
        workspace,
        project.id,
        [
            InGraphCommand(
                graph_id="main",
                command=ReplaceDocumentCommand(document=stale_graph),
            )
        ],
        observed_sequence=1,
    )
    assert accepted.head.collaboration_sequence == 2
    assert accepted.head.document.graphs[0].document == stale_graph


async def test_viewer_cannot_submit_commands(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    viewer = harness.add_member(workspace, name="Viewer", role=WorkspaceRole.VIEWER)

    with pytest.raises(CapabilityDeniedError):
        await harness.submit(viewer, workspace, project.id, [add_node("node-1")])

    assert harness.store.head_for(workspace.id, project.id).collaboration_sequence == 0
    assert harness.store.receipts == {}


async def test_two_batches_on_one_head_take_one_sequence_step_each(
    harness: Harness,
) -> None:
    """Two submissions race on one head: one lands, the other is refused."""

    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    # Both transactions reach the head before either is allowed to read it, so they
    # really are concurrent and only the row lock can order them.
    harness.store.gate("lock_head", parties=2)

    first = asyncio.create_task(
        harness.submit(
            owner,
            workspace,
            project.id,
            [RenameProjectCommand(name="Renamed by A", expected_name="Field survey")],
            command_id=uuid4(),
        )
    )
    second = asyncio.create_task(
        harness.submit(
            owner,
            workspace,
            project.id,
            [RenameProjectCommand(name="Renamed by B", expected_name="Field survey")],
            command_id=uuid4(),
        )
    )

    results = await asyncio.gather(first, second, return_exceptions=True)
    accepted = [
        result
        for result in results
        if isinstance(result, CommandSubmission)
        and result.receipt.outcome is CommandReceiptOutcome.ACCEPTED
    ]
    refused = [result for result in results if isinstance(result, CollaborationError)]

    assert len(accepted) == 1
    assert len(refused) == 1
    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.collaboration_sequence == 1
    assert committed.name == accepted[0].head.name
    assert committed.name != (
        "Renamed by A" if accepted[0].head.name == "Renamed by B" else "Renamed by B"
    )
    assert len(harness.store.receipts) == 1
    assert harness.revisions(project.id) == [1]


async def test_checkpoint_appends_the_next_immutable_revision(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    await harness.submit(
        owner, workspace, project.id, [add_node("node-1", value="first")]
    )

    outcome = await harness.checkpoint(owner, workspace, project.id)

    assert isinstance(outcome, CheckpointOutcome)
    assert outcome.revision == 2
    assert outcome.head.checkpoint_sequence == 1
    assert outcome.head.checkpoint_revision == 2
    assert outcome.head.is_fully_checkpointed is True
    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.checkpoint_sequence == 1
    checkpoint = harness.store.checkpoints[(project.id, 2)]
    assert checkpoint.name == "Field survey"
    assert checkpoint.document == committed.document
    assert checkpoint.document.graphs[0].document.nodes[0].config_dict() == {
        "value": "first"
    }
    mapping = harness.store.mappings[(workspace.id, project.id, head.room_epoch, 1)]
    assert mapping.checkpoint_revision == 2
    assert harness.revisions(project.id) == [1, 2]
    assert [event.operation for event in harness.audits][-1] == (
        "collaboration.checkpoint"
    )


async def test_checkpoint_is_idempotent_for_durable_state(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])
    first = await harness.checkpoint(owner, workspace, project.id)

    again = await harness.checkpoint(owner, workspace, project.id)

    assert again.revision == first.revision == 2
    assert harness.revisions(project.id) == [1, 2]
    assert harness.factory.last.commit_count == 0


async def test_checkpoint_of_a_moved_head_is_refused(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])

    with pytest.raises(CollaborationHeadConflictError):
        await harness.checkpoint(
            owner,
            workspace,
            project.id,
            expected_sequence=0,
            expected_room_epoch=head.room_epoch,
        )
    with pytest.raises(CollaborationHeadConflictError):
        await harness.checkpoint(
            owner,
            workspace,
            project.id,
            expected_sequence=1,
            expected_room_epoch=uuid4(),
        )

    assert harness.revisions(project.id) == [1]
    assert harness.store.head_for(workspace.id, project.id).checkpoint_sequence == 0


async def test_checkpoint_of_a_project_without_a_head_reports_missing(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    harness.store.heads.pop((workspace.id, project.id))

    with pytest.raises(MissingProjectHeadError):
        await harness.service.checkpoint(
            actor=owner,
            workspace_id=workspace.id,
            project_id=project.id,
            expected_sequence=head.collaboration_sequence,
            expected_room_epoch=head.room_epoch,
        )


async def test_checkpoint_conflict_surfaces_as_a_revision_conflict(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])
    # A checkpoint for revision 2 landed from elsewhere while this transaction read
    # the head, so the append is a duplicate revision.
    harness.store.checkpoints[(project.id, 2)] = ProjectCheckpoint(
        workspace_id=workspace.id,
        project_id=project.id,
        revision=2,
        name="Checkpointed elsewhere",
        document=harness.checkpoint_document(project.id, 1),
        created_at=datetime(2026, 1, 4, tzinfo=UTC),
    )

    with pytest.raises(ProjectCheckpointConflictError):
        await harness.checkpoint(owner, workspace, project.id)

    # The revision that landed elsewhere is still the one on disk, and this head has
    # not pretended to be level with it.
    assert harness.store.checkpoints[(project.id, 2)].name == "Checkpointed elsewhere"
    committed = harness.store.head_for(workspace.id, project.id)
    assert (committed.checkpoint_sequence, committed.checkpoint_revision) == (0, 1)


async def test_checkpoint_requires_the_checkpoint_capability(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])
    viewer = harness.add_member(workspace, name="Viewer", role=WorkspaceRole.VIEWER)

    with pytest.raises(CapabilityDeniedError):
        await harness.checkpoint(viewer, workspace, project.id)

    assert harness.revisions(project.id) == [1]


async def test_restore_replays_a_checkpoint_as_a_new_revision(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, old_head, _ = await harness.create(owner, workspace)
    original_document = harness.checkpoint_document(project.id, 1)
    await harness.submit(
        owner,
        workspace,
        project.id,
        [
            add_node("node-1"),
            RenameProjectCommand(name="Renamed", expected_name="Field survey"),
        ],
    )
    await harness.checkpoint(owner, workspace, project.id)
    old_revision_two = harness.checkpoint_document(project.id, 2)

    outcome = await harness.restore(owner, workspace, project.id, 1)

    assert outcome.revision == 3
    assert outcome.head.collaboration_sequence == 0
    assert outcome.head.checkpoint_sequence == 0
    assert outcome.head.checkpoint_revision == 3
    assert outcome.head.name == "Field survey"
    assert outcome.head.room_epoch != old_head.room_epoch
    assert outcome.head.document == original_document
    assert harness.revisions(project.id) == [1, 2, 3]
    assert harness.checkpoint_document(project.id, 1) == original_document
    assert harness.checkpoint_document(project.id, 2) == old_revision_two
    assert harness.store.checkpoints[(project.id, 3)].name == "Field survey"
    mapping = harness.store.mappings[
        (workspace.id, project.id, outcome.head.room_epoch, 0)
    ]
    assert mapping.checkpoint_revision == 3
    assert [event.operation for event in harness.audits][-1] == (
        "collaboration.checkpoint.restore"
    )


async def test_restore_refuses_to_discard_uncheckpointed_drafts(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])

    with pytest.raises(CollaborationUncheckpointedError) as raised:
        await harness.restore(owner, workspace, project.id, 1)

    assert (raised.value.head_sequence, raised.value.checkpoint_sequence) == (1, 0)
    assert harness.revisions(project.id) == [1]
    committed = harness.store.head_for(workspace.id, project.id)
    assert committed.room_epoch == head.room_epoch
    assert committed.collaboration_sequence == 1


async def test_restore_of_a_moved_head_or_missing_revision_is_refused(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)

    with pytest.raises(NotFoundError):
        await harness.restore(owner, workspace, project.id, 7)
    with pytest.raises(CollaborationHeadConflictError):
        await harness.restore(
            owner,
            workspace,
            project.id,
            1,
            expected_sequence=3,
            expected_room_epoch=head.room_epoch,
        )

    assert harness.revisions(project.id) == [1]
    assert (
        harness.store.head_for(workspace.id, project.id).room_epoch == head.room_epoch
    )


async def test_restore_requires_the_checkpoint_capability(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    viewer = harness.add_member(workspace, name="Viewer", role=WorkspaceRole.VIEWER)

    with pytest.raises(CapabilityDeniedError):
        await harness.restore(viewer, workspace, project.id, 1)

    assert harness.revisions(project.id) == [1]


async def test_copy_project_sanitizes_every_graph(harness: Harness) -> None:
    source, source_owner = harness.workspace(name="Source", slug="source")
    target, _ = harness.workspace(name="Target", slug="target")
    harness.join(target, source_owner, role=WorkspaceRole.OWNER)
    project, head, _ = await harness.create(source_owner, source, name="Field survey")
    await harness.submit(
        source_owner,
        source,
        project.id,
        [
            add_node("upload-1", upload_key="source-key", artifact_id="a", keep="yes"),
            AddGraphCommand(graph_id="branch", name="Branch"),
            add_node("upload-2", graph_id="branch", uploads=["one"], keep="also"),
        ],
        observed_room_epoch=head.room_epoch,
    )

    copied_project, copied_head, receipt = await harness.service.copy_project(
        actor=source_owner,
        source_workspace_id=source.id,
        source_project_id=project.id,
        target_workspace_id=target.id,
        expected_room_epoch=head.room_epoch,
        expected_sequence=1,
        name="Field survey (copy)",
    )

    assert receipt is None
    assert copied_project.workspace_id == target.id
    assert copied_project.name == "Field survey (copy)"
    assert copied_head.collaboration_sequence == 0
    assert copied_head.checkpoint_sequence == 0
    assert copied_head.checkpoint_revision == 1
    assert [graph.id for graph in copied_head.document.graphs] == ["main", "branch"]
    assert [graph.name for graph in copied_head.document.graphs] == ["Main", "Branch"]
    copied_configs = [
        graph.document.nodes[0].config_dict()
        for graph in copied_head.document.graphs
        if graph.document.nodes
    ]
    assert copied_configs == [{"keep": "yes"}, {"keep": "also"}]
    assert harness.checkpoint_document(copied_project.id, 1) == copied_head.document
    assert harness.store.head_for(source.id, project.id).collaboration_sequence == 1
    audits = [
        event
        for event in harness.audits
        if event.operation == "collaboration.project.copy"
    ]
    assert [(event.workspace_id, event.resource_id) for event in audits] == [
        (target.id, str(copied_project.id))
    ]
    assert target.id != source.id


async def test_copy_needs_view_in_source_and_create_in_target(harness: Harness) -> None:
    source, source_owner = harness.workspace(
        name="Source", slug="source", role=WorkspaceRole.EDITOR
    )
    target, _ = harness.workspace(name="Target", slug="target")
    project, head, _ = await harness.create(source_owner, source)
    # The copier may see the source but may not create in the target.
    harness.join(target, source_owner, role=WorkspaceRole.VIEWER)
    _, stranger = harness.workspace(name="Stranger", slug="stranger")

    def copy(actor: ActorContext):
        return harness.service.copy_project(
            actor=actor,
            source_workspace_id=source.id,
            source_project_id=project.id,
            target_workspace_id=target.id,
            expected_room_epoch=head.room_epoch,
            expected_sequence=0,
        )

    with pytest.raises(CapabilityDeniedError):
        await copy(source_owner)
    with pytest.raises(NotFoundError):
        await copy(stranger)

    assert list(harness.store.projects) == [project.id]
    assert len(harness.store.heads) == 1


async def test_copy_of_a_moved_source_head_is_refused(harness: Harness) -> None:
    source, source_owner = harness.workspace(name="Source", slug="source")
    target, _ = harness.workspace(name="Target", slug="target")
    harness.join(target, source_owner, role=WorkspaceRole.OWNER)
    project, head, _ = await harness.create(source_owner, source)
    await harness.submit(source_owner, source, project.id, [add_node("node-1")])

    with pytest.raises(CollaborationHeadConflictError) as raised:
        await harness.service.copy_project(
            actor=source_owner,
            source_workspace_id=source.id,
            source_project_id=project.id,
            target_workspace_id=target.id,
            expected_room_epoch=head.room_epoch,
            expected_sequence=0,
        )

    assert (raised.value.expected_sequence, raised.value.actual_sequence) == (0, 1)
    assert list(harness.store.projects) == [project.id]


async def test_copy_replays_the_same_command_id(harness: Harness) -> None:
    source, source_owner = harness.workspace(name="Source", slug="source")
    target, target_owner = harness.workspace(name="Target", slug="target")
    harness.join(source, target_owner, role=WorkspaceRole.VIEWER)
    project, head, _ = await harness.create(source_owner, source)
    await harness.submit(source_owner, source, project.id, [add_node("node-1")])
    target_project_id, command_id = uuid4(), uuid4()

    def copy():
        return harness.service.copy_project(
            actor=target_owner,
            source_workspace_id=source.id,
            source_project_id=project.id,
            target_workspace_id=target.id,
            expected_room_epoch=head.room_epoch,
            expected_sequence=1,
            command_id=command_id,
            project_id=target_project_id,
            name="Field survey (copy)",
        )

    created = await copy()
    replayed = await copy()

    assert created.receipt is not None
    assert created.receipt.outcome is CommandReceiptOutcome.ACCEPTED
    assert created.project.id == target_project_id
    assert replayed.project.id == target_project_id
    assert replayed.receipt is not None
    assert replayed.receipt.outcome is CommandReceiptOutcome.IDEMPOTENT_REPLAY
    assert replayed.receipt.command_hmac == created.receipt.command_hmac
    assert replayed.head.room_epoch == created.head.room_epoch
    assert len(harness.store.projects) == 2
    assert harness.revisions(target_project_id) == [1]

    with pytest.raises(CollaborationIdempotencyMismatchError):
        await harness.service.copy_project(
            actor=target_owner,
            source_workspace_id=source.id,
            source_project_id=project.id,
            target_workspace_id=target.id,
            expected_room_epoch=head.room_epoch,
            expected_sequence=1,
            command_id=command_id,
            project_id=target_project_id,
            name="Renamed retry",
        )

    assert harness.store.head_for(target.id, target_project_id).name == (
        "Field survey (copy)"
    )


async def test_delete_project_removes_the_head_and_the_project_rows(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])
    await harness.checkpoint(owner, workspace, project.id)

    await harness.service.delete_project(
        actor=owner, workspace_id=workspace.id, project_id=project.id
    )

    assert harness.store.projects == {}
    assert harness.store.heads == {}
    assert harness.revisions(project.id) == []
    assert [event.operation for event in harness.audits][-1] == (
        "collaboration.project.delete"
    )


async def test_delete_refuses_uncheckpointed_drafts_and_a_moved_head(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, head, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])

    with pytest.raises(CollaborationUncheckpointedError):
        await harness.service.delete_project(
            actor=owner, workspace_id=workspace.id, project_id=project.id
        )
    with pytest.raises(CollaborationHeadConflictError):
        await harness.service.delete_project(
            actor=owner,
            workspace_id=workspace.id,
            project_id=project.id,
            expected_room_epoch=head.room_epoch,
            expected_sequence=7,
        )

    assert harness.store.projects != {}
    assert harness.store.head_for(workspace.id, project.id).collaboration_sequence == 1

    # A caller that names the draft it is looking at may take it with the project.
    await harness.service.delete_project(
        actor=owner,
        workspace_id=workspace.id,
        project_id=project.id,
        expected_room_epoch=head.room_epoch,
        expected_sequence=1,
    )
    assert harness.store.projects == {}


async def test_delete_requires_the_delete_capability_and_the_right_workspace(
    harness: Harness,
) -> None:
    mine, owner = harness.workspace(name="Mine", slug="mine")
    editor = harness.add_member(mine, name="Editor", role=WorkspaceRole.EDITOR)
    project, _, _ = await harness.create(owner, mine)
    other, _ = harness.workspace(name="Other", slug="other")

    with pytest.raises(CapabilityDeniedError):
        await harness.service.delete_project(
            actor=editor, workspace_id=mine.id, project_id=project.id
        )
    with pytest.raises(NotFoundError):
        await harness.service.delete_project(
            actor=owner, workspace_id=other.id, project_id=project.id
        )

    assert list(harness.store.projects) == [project.id]
    assert harness.store.heads != {}


async def test_no_project_operation_touches_node_secrets(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project, _, _ = await harness.create(owner, workspace)
    await harness.submit(owner, workspace, project.id, [add_node("node-1")])
    await harness.checkpoint(owner, workspace, project.id)
    await harness.restore(owner, workspace, project.id, 1)
    await harness.service.delete_project(
        actor=owner, workspace_id=workspace.id, project_id=project.id
    )

    assert harness.factory.secrets_touched is False
