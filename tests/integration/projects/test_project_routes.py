"""Project routes: the browser, the head, command batches, checkpoints, filing."""

from collections.abc import Sequence
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from grafy_core.domain.collaboration import (
    AddGraphCommand,
    AddNodeCommand,
    InGraphCommand,
    ProjectCommand,
    RenameGraphCommand,
    RenameProjectCommand,
    ReplaceDocumentCommand,
)
from grafy_core.domain.graph_documents import GraphDocument, GraphNode, GraphPoint
from grafy_api.project_contracts import (
    AssignProjectFolderRequest,
    CheckpointProjectRequest,
    CopyExactHeadRequest,
    CreateProjectRequest,
    ProjectFolderWriteRequest,
    ProjectHeadResponse,
    SubmitProjectCommandRequest,
)

from tests.support.clients import GrafyApi
from tests.support.identity import WORKSPACE_ID


def _node(node_id: str) -> GraphNode:
    """A node the deployment's own catalog can describe.

    An accepted batch makes the Run service re-derive this Project's instances, and a
    node the build has no registration for stops that: a fixture node invented for a
    test would fail the route for a reason that has nothing to do with the route.
    """

    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id="text.input",
        operator_version=1,
        config={"text": "draft"},
        position=GraphPoint(x=0, y=0),
    )


def _rename(name: str, expected_name: str) -> RenameProjectCommand:
    return RenameProjectCommand(name=name, expected_name=expected_name)


def _batch_request(
    commands: Sequence[ProjectCommand], room_epoch: UUID, observed_sequence: int
) -> SubmitProjectCommandRequest:
    return SubmitProjectCommandRequest(
        command_id=uuid4(),
        room_epoch=room_epoch,
        observed_sequence=observed_sequence,
        commands=tuple(commands),
    )


def _create(api: GrafyApi, name: str = "Field notes"):
    projects = api.workspace(WORKSPACE_ID).projects
    created = projects.create_ok(CreateProjectRequest(name=name))
    return projects, created


def _checkpoint_request(head: ProjectHeadResponse) -> CheckpointProjectRequest:
    return CheckpointProjectRequest(
        expected_room_epoch=head.room_epoch,
        expected_sequence=head.collaboration_sequence,
    )


def test_create_opens_a_project_with_one_graph_and_its_first_checkpoint(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects, created = _create(api, "  Field notes  ")

    assert created.name == "Field notes"
    head = projects.get_head_ok(created.id)
    assert head.project_id == created.id
    assert head.name == "Field notes"
    # A staged Project is durable before anyone edits it: the first batch is
    # accepted at sequence 1 against checkpoint 1.
    assert head.collaboration_sequence == 0
    assert head.checkpoint_sequence == 0
    assert head.checkpoint_revision == 1
    assert [graph.id for graph in head.document.graphs] == ["main"]

    listed = projects.list_ok().projects
    assert [item.id for item in listed] == [created.id]
    assert listed[0].name == "Field notes"
    assert listed[0].revision == 1
    assert listed[0].draft_pending is False
    assert projects.get_ok(created.id).name == "Field notes"


def test_create_replays_only_the_promise_it_was_given(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects = api.workspace(WORKSPACE_ID).projects
    project_id, command_id = uuid4(), uuid4()
    payload = CreateProjectRequest(
        name="Replayed", project_id=project_id, command_id=command_id
    )

    first = projects.create_ok(payload)
    replay = projects.create_ok(payload)
    # A second promise under the ids of a creation that already happened is a client
    # bug, not a retry: the batch it replays is a different batch.
    mismatch = projects.create(payload.model_copy(update={"name": "Mismatched"}))
    # Raw, because the request model itself refuses an unpaired pair.
    unpaired = api.raw.post(
        f"/v1/workspaces/{WORKSPACE_ID}/projects",
        json={"name": "Unpaired", "command_id": str(uuid4())},
    )

    assert (first.id, replay.id) == (project_id, project_id)
    assert projects.list_ok().projects[0].id == project_id
    assert mismatch.status_code == 409
    # A command id replays only against a Project id the retry can find it under.
    assert unpaired.status_code == 422


def test_command_batch_is_accepted_or_rejected_as_a_whole(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects, created = _create(api, "Whole batch")
    head = projects.get_head_ok(created.id)

    accepted = projects.submit_commands_ok(
        created.id,
        _batch_request(
            (
                _rename("Renamed once", "Whole batch"),
                AddGraphCommand(graph_id="notes", name="Notes"),
                InGraphCommand(
                    graph_id="notes",
                    command=AddNodeCommand(node=_node("source")),
                ),
            ),
            head.room_epoch,
            head.collaboration_sequence,
        ),
    )
    # One batch, one step: three commands, one collaboration sequence.
    assert accepted.head.collaboration_sequence == head.collaboration_sequence + 1
    assert accepted.head.name == "Renamed once"
    assert accepted.receipt.outcome == "accepted"
    assert accepted.receipt.accepted_sequence == accepted.head.collaboration_sequence
    assert accepted.receipt.deduplicated is False
    assert [graph.id for graph in accepted.head.document.graphs] == ["main", "notes"]
    notes = accepted.head.document.get_graph("notes")
    assert [node.id for node in notes.document.nodes] == ["source"]

    rejected = projects.submit_commands(
        created.id,
        _batch_request(
            (
                _rename("Renamed twice", "Renamed once"),
                RenameGraphCommand(
                    graph_id="missing", name="Nothing", expected_name="Absent"
                ),
            ),
            accepted.head.room_epoch,
            accepted.head.collaboration_sequence,
        ),
    )

    assert rejected.status_code == 422
    assert "index 1" in rejected.json()["detail"]
    after = projects.get_head_ok(created.id)
    assert after.model_dump() == accepted.head.model_dump()

    # A batch is never empty: there is nothing to accept and nothing to reject.
    empty = api.raw.post(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/{created.id}/commands",
        json={
            "command_id": str(uuid4()),
            "room_epoch": str(after.room_epoch),
            "observed_sequence": after.collaboration_sequence,
            "commands": [],
        },
    )
    assert empty.status_code == 422


def test_command_retry_replays_and_a_reused_id_is_refused(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects, created = _create(api, "One promise")
    head = projects.get_head_ok(created.id)
    command_id = uuid4()
    payload = SubmitProjectCommandRequest(
        command_id=command_id,
        room_epoch=head.room_epoch,
        observed_sequence=head.collaboration_sequence,
        commands=(_rename("Promised", "One promise"),),
    )

    first = projects.submit_commands_ok(created.id, payload)
    retry = projects.submit_commands_ok(created.id, payload)
    assert retry.head.model_dump() == first.head.model_dump()
    assert retry.receipt.outcome == "idempotent_replay"
    assert retry.receipt.deduplicated is True

    mismatch = projects.submit_commands(
        created.id,
        payload.model_copy(update={"commands": (_rename("Different", "One promise"),)}),
    )
    assert mismatch.status_code == 409

    # A whole-document replace carries no compare-and-set of its own, so it is only
    # accepted at the sequence it was read at: a moved head sends the client back to
    # the head rather than replaying its own.
    stale = projects.submit_commands(
        created.id,
        _batch_request(
            (
                InGraphCommand(
                    graph_id="main",
                    command=ReplaceDocumentCommand(document=GraphDocument()),
                ),
            ),
            first.head.room_epoch,
            0,
        ),
    )
    assert stale.status_code == 409
    assert projects.get_head_ok(created.id).collaboration_sequence == 1


def test_checkpoint_freezes_the_head_and_restore_writes_it_forward(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects, created = _create(api, "Checkpoints")
    original = projects.get_head_ok(created.id)

    moved = projects.submit_commands_ok(
        created.id,
        _batch_request(
            (
                _rename("Drafted", "Checkpoints"),
                AddGraphCommand(graph_id="second", name="Second"),
            ),
            original.room_epoch,
            original.collaboration_sequence,
        ),
    )
    assert projects.list_ok().projects[0].draft_pending is True

    checkpointed = projects.checkpoint_ok(created.id, _checkpoint_request(moved.head))
    assert checkpointed.checkpoint_revision == 2
    assert checkpointed.head.checkpoint_sequence == 1
    assert checkpointed.head.checkpoint_revision == 2
    assert projects.list_ok().projects[0].draft_pending is False
    assert projects.list_ok().projects[0].revision == 2

    # Checkpointing an already-durable head is idempotent, not a second copy.
    again = projects.checkpoint_ok(created.id, _checkpoint_request(checkpointed.head))
    assert again.checkpoint_revision == 2

    listed = projects.list_checkpoints_ok(created.id).checkpoints
    assert [item.revision for item in listed] == [1, 2]
    frozen = projects.get_checkpoint_ok(created.id, 1)
    assert frozen.name == "Checkpoints"
    assert [graph.id for graph in frozen.document.graphs] == ["main"]
    assert frozen.created_at == listed[0].created_at

    # The way back is a new revision, so nothing that followed is erased.
    restored = projects.restore_checkpoint_ok(
        created.id, 1, _checkpoint_request(again.head)
    )
    assert restored.checkpoint_revision == 3
    assert restored.head.name == "Checkpoints"
    assert [graph.id for graph in restored.head.document.graphs] == ["main"]
    # The room reopens rather than rewinds, so every participant rehydrates.
    assert restored.head.room_epoch != original.room_epoch
    assert restored.head.collaboration_sequence == 0
    assert projects.get_head_ok(created.id).name == "Checkpoints"
    assert [
        item.revision for item in projects.list_checkpoints_ok(created.id).checkpoints
    ] == [1, 2, 3]


def test_restore_refuses_to_discard_an_uncheckpointed_draft(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects, created = _create(api, "Live draft")
    head = projects.get_head_ok(created.id)
    draft = projects.submit_commands_ok(
        created.id,
        _batch_request(
            (_rename("Unsaved work", "Live draft"),),
            head.room_epoch,
            head.collaboration_sequence,
        ),
    )

    refused = projects.restore_checkpoint(
        created.id, 1, _checkpoint_request(draft.head)
    )

    assert refused.status_code == 409
    assert "uncheckpointed" in refused.json()["detail"].lower()
    assert projects.get_head_ok(created.id).name == "Unsaved work"


def test_checkpoint_routes_answer_only_for_the_project_that_holds_them(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects, created = _create(api, "Unknown revisions")

    assert projects.get_checkpoint(created.id, 2).status_code == 404
    assert projects.get_checkpoint(uuid4(), 1).status_code == 404
    assert projects.list_checkpoints(uuid4()).status_code == 404
    assert (
        projects.restore_checkpoint(
            created.id,
            7,
            CheckpointProjectRequest(expected_room_epoch=uuid4(), expected_sequence=0),
        ).status_code
        == 404
    )
    assert (
        projects.checkpoint(
            created.id,
            CheckpointProjectRequest(
                expected_room_epoch=projects.get_head_ok(created.id).room_epoch,
                expected_sequence=41,
            ),
        ).status_code
        == 409
    )


def test_copy_takes_the_head_the_caller_read(builtin_client: TestClient) -> None:
    api = GrafyApi(builtin_client)
    projects, source = _create(api, "Copy source")
    head = projects.get_head_ok(source.id)

    copied = projects.copy_ok(
        CopyExactHeadRequest(
            source_workspace_id=WORKSPACE_ID,
            source_project_id=source.id,
            project_id=uuid4(),
            expected_room_epoch=head.room_epoch,
            expected_sequence=head.collaboration_sequence,
            command_id=uuid4(),
            name="Copied notes",
        )
    )

    assert copied.name == "Copied notes"
    assert copied.id != source.id
    copied_head = projects.get_head_ok(copied.id)
    assert copied_head.document == head.document
    assert copied_head.collaboration_sequence == 0
    assert copied_head.checkpoint_revision == 1

    stale = projects.copy(
        CopyExactHeadRequest(
            source_workspace_id=WORKSPACE_ID,
            source_project_id=source.id,
            project_id=uuid4(),
            expected_room_epoch=head.room_epoch,
            expected_sequence=head.collaboration_sequence + 5,
            command_id=uuid4(),
        )
    )
    assert stale.status_code == 409
    assert {item.id for item in projects.list_ok().projects} == {source.id, copied.id}


def test_filing_archive_and_star_each_have_their_inverse(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    workspace = api.workspace(WORKSPACE_ID)
    projects, created = _create(api, "To file")

    folder = workspace.project_folders.create_ok(
        ProjectFolderWriteRequest(name="Research")
    )
    assert workspace.project_folders.list_ok().folders[0].id == folder.id
    renamed = workspace.project_folders.rename_ok(
        folder.id, ProjectFolderWriteRequest(name="  Fieldwork  ")
    )
    assert renamed.name == "Fieldwork"
    assert (
        workspace.project_folders.create(
            ProjectFolderWriteRequest(name="Fieldwork")
        ).status_code
        == 409
    )

    filed = projects.assign_folder_ok(
        created.id, AssignProjectFolderRequest(folder_id=folder.id)
    )
    assert filed.folder_id == folder.id
    row = api.project_browser.list_ok().projects[0]
    assert row.folder is not None and row.folder.id == folder.id
    assert row.location.id == WORKSPACE_ID
    assert row.name == "To file"
    assert row.archived is False

    unfiled = projects.assign_folder_ok(
        created.id, AssignProjectFolderRequest(folder_id=None)
    )
    assert unfiled.folder_id is None
    assert (
        projects.assign_folder(
            created.id, AssignProjectFolderRequest(folder_id=uuid4())
        ).status_code
        == 404
    )

    assert projects.archive_ok(created.id).archived is True
    assert api.project_browser.list_ok().projects[0].archived is True
    assert projects.unarchive_ok(created.id).archived is False

    assert projects.star_ok(created.id).starred is True
    assert api.project_browser.list_ok().projects[0].starred is True
    assert projects.unstar_ok(created.id).starred is False
    assert projects.record_open_ok(created.id).last_opened_at is not None

    assert workspace.project_folders.delete(folder.id).status_code == 204
    assert workspace.project_folders.list_ok().folders == []
    assert (
        workspace.project_folders.rename(
            uuid4(), ProjectFolderWriteRequest(name="x")
        ).status_code
        == 404
    )
    assert workspace.project_folders.delete(uuid4()).status_code == 404


def test_delete_removes_the_project_and_refuses_to_lose_unsaved_work(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects, created = _create(api, "Temporary")
    head = projects.get_head_ok(created.id)
    draft = projects.submit_commands_ok(
        created.id,
        _batch_request(
            (_rename("Unsaved", "Temporary"),),
            head.room_epoch,
            head.collaboration_sequence,
        ),
    )

    # Without the sequence the caller read, discarding a draft is refused outright.
    assert projects.delete(created.id).status_code == 409

    aware = projects.delete(
        created.id,
        expected_room_epoch=draft.head.room_epoch,
        expected_sequence=draft.head.collaboration_sequence,
    )
    assert aware.status_code == 204
    assert projects.get(created.id).status_code == 404
    assert projects.get_head(created.id).status_code == 404
    assert projects.list_ok().projects == []

    half_a_promise = projects.delete(created.id, expected_sequence=1)
    assert half_a_promise.status_code == 422


def test_project_routes_answer_404_for_a_project_that_is_not_there(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects = api.workspace(WORKSPACE_ID).projects
    missing = UUID("00000000-0000-0000-0000-000000000404")
    node_secrets = api.workspace(WORKSPACE_ID).node_secrets

    responses = {
        "get": projects.get(missing),
        "delete": projects.delete(missing),
        "head": projects.get_head(missing),
        "commands": projects.submit_commands(
            missing,
            _batch_request((_rename("x", "y"),), uuid4(), 0),
        ),
        "checkpoint": projects.checkpoint(
            missing,
            CheckpointProjectRequest(expected_room_epoch=uuid4(), expected_sequence=0),
        ),
        "checkpoints": projects.list_checkpoints(missing),
        "checkpoint detail": projects.get_checkpoint(missing, 1),
        "restore": projects.restore_checkpoint(
            missing,
            1,
            CheckpointProjectRequest(expected_room_epoch=uuid4(), expected_sequence=0),
        ),
        "folder": projects.assign_folder(
            missing, AssignProjectFolderRequest(folder_id=None)
        ),
        "archive": projects.archive(missing),
        "unarchive": projects.unarchive(missing),
        "star": projects.star(missing),
        "unstar": projects.unstar(missing),
        "opened": projects.record_open(missing),
        "node secrets": node_secrets.list_secrets(missing),
    }

    for context, response in responses.items():
        assert response.status_code == 404, (
            context,
            response.status_code,
            response.text,
        )
    assert str(missing) in responses["get"].json()["detail"]


def test_project_document_round_trips_through_the_head(
    builtin_client: TestClient,
) -> None:
    """The document a batch writes is the document the head and checkpoints carry."""

    api = GrafyApi(builtin_client)
    projects, created = _create(api, "Document shape")
    head = projects.get_head_ok(created.id)
    document = GraphDocument(nodes=(_node("source"), _node("target")))

    accepted = projects.submit_commands_ok(
        created.id,
        _batch_request(
            (
                AddGraphCommand(
                    graph_id="wide",
                    name="Wide",
                    document=document,
                ),
                InGraphCommand(
                    graph_id="wide",
                    command=AddNodeCommand(node=_node("third")),
                ),
            ),
            head.room_epoch,
            head.collaboration_sequence,
        ),
    )
    projects.checkpoint_ok(created.id, _checkpoint_request(accepted.head))

    frozen = projects.get_checkpoint_ok(created.id, 2)
    graph = frozen.document.get_graph("wide")
    assert [node.id for node in graph.document.nodes] == ["source", "target", "third"]
    assert frozen.document == accepted.head.document
    assert [node.config for node in graph.document.nodes] == [{"text": "draft"}] * 3


def test_project_browser_lists_every_workspace_the_user_can_see(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    projects, created = _create(api, "Browser row")
    workspace = api.workspace(WORKSPACE_ID)
    folder = workspace.project_folders.create_ok(ProjectFolderWriteRequest(name="Row"))
    projects.assign_folder_ok(
        created.id, AssignProjectFolderRequest(folder_id=folder.id)
    )
    projects.star_ok(created.id)
    projects.record_open_ok(created.id)

    row = api.project_browser.list_ok().projects[0]
    assert row.id == created.id
    assert row.folder is not None and row.folder.name == "Row"
    assert row.starred is True and row.last_opened_at is not None
    assert row.creator is not None
    summary = projects.list_ok().projects[0]
    # The browser row is the workspace summary plus where it lives and what the
    # acting user made of it.
    assert (
        row.model_dump(include=set(type(summary).model_fields)) == summary.model_dump()
    )
