"""Focused tests for ``ProjectService``: browser, folders, archive, star, open (ADR 0020).

Run with ``--noconftest``: this file builds its own fakes from
``tests/unit/application/project_fakes.py`` and expects nothing from shared fixtures.
"""

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

from grafy_core.application.projects import ProjectService
from grafy_core.domain.collaboration import empty_project_document
from grafy_core.domain.errors import (
    CapabilityDeniedError,
    NotFoundError,
    ProjectFolderNameConflictError,
    UserDisabledError,
)
from grafy_core.domain.graph_documents import GraphDocument, GraphNode, GraphPoint
from grafy_core.domain.identity import (
    ActorContext,
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceRole,
)
from grafy_core.domain.projects import ProjectCheckpoint, ProjectFolder
from grafy_core.kernel.project import GraphDefinition, ProjectDocument


def actor_for(user: User) -> ActorContext:
    return ActorContext(user_id=user.id, credential_reference="session:test")


@dataclass
class Harness:
    directory: IdentityDirectory
    store: ProjectStore
    factory: ProjectUnitOfWorkFactory
    service: ProjectService

    def workspace(
        self,
        *,
        name: str,
        slug: str,
        role: WorkspaceRole = WorkspaceRole.OWNER,
        kind: WorkspaceKind = WorkspaceKind.SHARED,
    ) -> tuple[Workspace, ActorContext]:
        """A Workspace with one member holding ``role``, plus that member's actor."""

        workspace, user = new_member(
            self.directory, display_name=name, slug=slug, role=role, kind=kind
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

    def project(
        self,
        workspace: Workspace,
        *,
        name: str,
        actor: ActorContext | None = None,
        document: ProjectDocument | None = None,
    ):
        project, _head = self.store.seed_project(
            workspace_id=workspace.id,
            name=name,
            document=empty_project_document("main") if document is None else document,
            created_by_user_id=None if actor is None else actor.user_id,
        )
        return project

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
        service=ProjectService(factory),
    )


async def test_get_returns_the_project_row(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)

    found = await harness.service.get(workspace_id=workspace.id, project_id=project.id)

    assert (found.id, found.name, found.workspace_id) == (
        project.id,
        "Field survey",
        workspace.id,
    )


async def test_get_hides_a_project_of_another_workspace(harness: Harness) -> None:
    mine, _ = harness.workspace(name="Mine", slug="mine")
    theirs, other = harness.workspace(name="Theirs", slug="theirs")
    foreign = harness.project(theirs, name="Not yours", actor=other)

    with pytest.raises(NotFoundError) as raised:
        await harness.service.get(workspace_id=mine.id, project_id=foreign.id)

    assert raised.value.resource == "Project"
    assert raised.value.resource_id == str(foreign.id)


async def test_list_is_scoped_to_one_workspace(harness: Harness) -> None:
    mine, owner = harness.workspace(name="Mine", slug="mine")
    theirs, other = harness.workspace(name="Theirs", slug="theirs")
    harness.project(mine, name="Beta", actor=owner)
    harness.project(mine, name="Alpha", actor=owner)
    harness.project(theirs, name="Gamma", actor=other)

    listed = await harness.service.list(workspace_id=mine.id)

    assert [project.name for project in listed] == ["Alpha", "Beta"]


async def test_browser_listing_shows_head_state_and_only_visible_workspaces(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)
    other_workspace, other = harness.workspace(name="Other", slug="other")
    harness.project(other_workspace, name="Someone else", actor=other)

    items = await harness.service.list_accessible(actor=owner)

    assert [item.id for item in items] == [project.id]
    item = items[0]
    assert item.draft.name == "Field survey"
    assert item.draft.head_sequence == 0
    assert item.draft.checkpoint_sequence == 0
    assert item.draft.checkpoint_revision == 1
    assert (item.draft.graph_count, item.draft.node_count, item.draft.edge_count) == (
        1,
        0,
        0,
    )
    assert item.location.id == workspace.id
    assert item.location.slug == "owner"
    assert item.location.kind is WorkspaceKind.SHARED
    assert (item.folder, item.archived_at, item.starred, item.last_opened_at) == (
        None,
        None,
        False,
        None,
    )
    assert item.creator is not None
    assert item.creator.id == owner.user_id


async def test_revoked_membership_stops_listing_the_workspace(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    harness.project(workspace, name="Field survey", actor=owner)

    harness.directory.revoke(workspace_id=workspace.id, user_id=owner.user_id)

    assert await harness.service.list_accessible(actor=owner) == []


async def test_folder_create_rename_and_delete_round_trip(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")

    created = await harness.service.create_folder(
        actor=owner, workspace_id=workspace.id, name="  Field season  "
    )
    assert (created.name, created.workspace_id) == ("Field season", workspace.id)

    renamed = await harness.service.rename_folder(
        actor=owner,
        workspace_id=workspace.id,
        folder_id=created.id,
        name="Field season 2026",
    )
    assert (renamed.id, renamed.name) == (created.id, "Field season 2026")

    listed = await harness.service.list_folders(actor=owner, workspace_id=workspace.id)
    assert [folder.name for folder in listed] == ["Field season 2026"]

    await harness.service.delete_folder(
        actor=owner, workspace_id=workspace.id, folder_id=created.id
    )

    assert harness.store.folders == {}
    assert [event.operation for event in harness.audits] == [
        "project.folder.create",
        "project.folder.rename",
        "project.folder.delete",
    ]
    assert all(event.workspace_id == workspace.id for event in harness.audits)
    assert all(event.resource_id == str(created.id) for event in harness.audits)


async def test_duplicate_folder_name_is_refused_and_writes_nothing(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    await harness.service.create_folder(
        actor=owner, workspace_id=workspace.id, name="Field season"
    )

    with pytest.raises(ProjectFolderNameConflictError) as raised:
        await harness.service.create_folder(
            actor=owner, workspace_id=workspace.id, name="Field season"
        )

    assert raised.value.name == "Field season"
    assert [folder.name for folder in harness.store.folders.values()] == [
        "Field season"
    ]
    assert harness.factory.last.commit_count == 0
    # Only the folder that was accepted is audited; the refusal wrote nothing.
    assert [event.operation for event in harness.audits] == ["project.folder.create"]


async def test_rename_folder_onto_another_folders_name_is_refused(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    first = await harness.service.create_folder(
        actor=owner, workspace_id=workspace.id, name="First"
    )
    await harness.service.create_folder(
        actor=owner, workspace_id=workspace.id, name="Second"
    )

    with pytest.raises(ProjectFolderNameConflictError):
        await harness.service.rename_folder(
            actor=owner,
            workspace_id=workspace.id,
            folder_id=first.id,
            name="Second",
        )

    assert sorted(folder.name for folder in harness.store.folders.values()) == [
        "First",
        "Second",
    ]


async def test_folder_operations_hide_a_foreign_workspace_folder(
    harness: Harness,
) -> None:
    mine, owner = harness.workspace(name="Mine", slug="mine")
    theirs, _ = harness.workspace(name="Theirs", slug="theirs")
    foreign = harness.store.seed_folder(
        ProjectFolder(workspace_id=theirs.id, name="Theirs")
    )

    with pytest.raises(NotFoundError):
        await harness.service.rename_folder(
            actor=owner,
            workspace_id=mine.id,
            folder_id=foreign.id,
            name="Stolen",
        )
    with pytest.raises(NotFoundError):
        await harness.service.delete_folder(
            actor=owner, workspace_id=mine.id, folder_id=foreign.id
        )

    assert harness.store.folders[foreign.id].name == "Theirs"
    assert harness.factory.last.commit_count == 0


async def test_assign_folder_files_a_project_and_none_unfiles_it(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)
    folder = await harness.service.create_folder(
        actor=owner, workspace_id=workspace.id, name="Field season"
    )

    filed = await harness.service.assign_folder(
        actor=owner,
        workspace_id=workspace.id,
        project_id=project.id,
        folder_id=folder.id,
    )
    assert (filed.folder_id, filed.archived_at) == (folder.id, None)
    filed_items = await harness.service.list_accessible(
        actor=owner, workspace_id=workspace.id
    )
    assert [
        (
            item.folder.name if item.folder else None,
            item.folder.id if item.folder else None,
        )
        for item in filed_items
    ] == [(folder.name, folder.id)]

    unfiled = await harness.service.assign_folder(
        actor=owner,
        workspace_id=workspace.id,
        project_id=project.id,
        folder_id=None,
    )
    assert unfiled.folder_id is None
    unfiled_items = await harness.service.list_accessible(
        actor=owner, workspace_id=workspace.id
    )
    assert [item.folder for item in unfiled_items] == [None]


async def test_assign_folder_refuses_a_foreign_folder_and_a_foreign_project(
    harness: Harness,
) -> None:
    mine, owner = harness.workspace(name="Mine", slug="mine")
    theirs, _ = harness.workspace(name="Theirs", slug="theirs")
    project = harness.project(mine, name="Field survey", actor=owner)
    foreign_folder = harness.store.seed_folder(
        ProjectFolder(workspace_id=theirs.id, name="Theirs")
    )

    with pytest.raises(NotFoundError):
        await harness.service.assign_folder(
            actor=owner,
            workspace_id=mine.id,
            project_id=project.id,
            folder_id=foreign_folder.id,
        )
    with pytest.raises(NotFoundError):
        await harness.service.assign_folder(
            actor=owner,
            workspace_id=theirs.id,
            project_id=project.id,
            folder_id=None,
        )

    assert harness.store.organizations == {}


async def test_delete_folder_unfiles_the_projects_it_held(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)
    folder = await harness.service.create_folder(
        actor=owner, workspace_id=workspace.id, name="Field season"
    )
    await harness.service.assign_folder(
        actor=owner,
        workspace_id=workspace.id,
        project_id=project.id,
        folder_id=folder.id,
    )

    await harness.service.delete_folder(
        actor=owner, workspace_id=workspace.id, folder_id=folder.id
    )

    assert harness.store.organizations[(workspace.id, project.id)].folder_id is None
    assert harness.store.folders == {}


async def test_archive_and_restore_are_inverses(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)

    archived = await harness.service.archive(
        actor=owner, workspace_id=workspace.id, project_id=project.id
    )
    assert archived.is_archived is True
    assert archived.archived_at is not None
    assert [
        item.is_archived for item in await harness.service.list_accessible(actor=owner)
    ] == [True]

    restored = await harness.service.restore(
        actor=owner, workspace_id=workspace.id, project_id=project.id
    )
    assert restored.is_archived is False
    assert restored.archived_at is None
    assert [
        item.is_archived for item in await harness.service.list_accessible(actor=owner)
    ] == [False]
    assert [event.operation for event in harness.audits] == [
        "project.archive",
        "project.restore",
    ]


async def test_archiving_twice_keeps_the_first_stamp(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)

    first = await harness.service.archive(
        actor=owner, workspace_id=workspace.id, project_id=project.id
    )
    second = await harness.service.archive(
        actor=owner, workspace_id=workspace.id, project_id=project.id
    )

    assert second.archived_at == first.archived_at


async def test_archiving_keeps_a_projects_filing(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)
    folder = await harness.service.create_folder(
        actor=owner, workspace_id=workspace.id, name="Field season"
    )
    await harness.service.assign_folder(
        actor=owner,
        workspace_id=workspace.id,
        project_id=project.id,
        folder_id=folder.id,
    )

    archived = await harness.service.archive(
        actor=owner, workspace_id=workspace.id, project_id=project.id
    )

    assert (archived.folder_id, archived.is_archived) == (folder.id, True)


async def test_star_and_open_belong_to_one_user_only(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    editor = harness.add_member(workspace, name="Editor", role=WorkspaceRole.EDITOR)
    project = harness.project(workspace, name="Field survey", actor=owner)

    starred = await harness.service.set_starred(
        actor=owner,
        workspace_id=workspace.id,
        project_id=project.id,
        starred=True,
    )
    assert starred.starred is True
    assert [
        (item.id, item.starred)
        for item in await harness.service.list_accessible(actor=owner)
    ] == [(project.id, True)]
    assert [
        (item.id, item.starred)
        for item in await harness.service.list_accessible(actor=editor)
    ] == [(project.id, False)]

    unstarred = await harness.service.set_starred(
        actor=owner,
        workspace_id=workspace.id,
        project_id=project.id,
        starred=False,
    )
    assert unstarred.starred is False

    opened = await harness.service.record_open(
        actor=editor, workspace_id=workspace.id, project_id=project.id
    )
    first_open = opened.last_opened_at
    assert first_open is not None
    again = await harness.service.record_open(
        actor=editor, workspace_id=workspace.id, project_id=project.id
    )
    assert again.last_opened_at is not None
    assert again.last_opened_at >= first_open
    owner_items = await harness.service.list_accessible(actor=owner)
    assert [item.last_opened_at for item in owner_items] == [None]


async def test_star_of_a_foreign_project_is_refused(harness: Harness) -> None:
    mine, owner = harness.workspace(name="Mine", slug="mine")
    theirs, other = harness.workspace(name="Theirs", slug="theirs")
    project = harness.project(theirs, name="Not yours", actor=other)

    with pytest.raises(NotFoundError):
        await harness.service.set_starred(
            actor=owner,
            workspace_id=mine.id,
            project_id=project.id,
            starred=True,
        )

    assert harness.store.user_states == {}


async def test_viewer_may_star_and_open_but_not_file_or_archive(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)
    viewer = harness.add_member(workspace, name="Viewer", role=WorkspaceRole.VIEWER)

    starred = await harness.service.set_starred(
        actor=viewer, workspace_id=workspace.id, project_id=project.id, starred=True
    )
    opened = await harness.service.record_open(
        actor=viewer, workspace_id=workspace.id, project_id=project.id
    )
    assert (starred.starred, opened.last_opened_at is not None) == (True, True)

    with pytest.raises(CapabilityDeniedError):
        await harness.service.create_folder(
            actor=viewer, workspace_id=workspace.id, name="Nope"
        )
    with pytest.raises(CapabilityDeniedError):
        await harness.service.archive(
            actor=viewer, workspace_id=workspace.id, project_id=project.id
        )
    with pytest.raises(CapabilityDeniedError):
        await harness.service.assign_folder(
            actor=viewer,
            workspace_id=workspace.id,
            project_id=project.id,
            folder_id=None,
        )

    assert harness.store.folders == {}
    assert harness.store.organizations == {}


async def test_a_disabled_user_is_refused(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)

    harness.directory.disable_user(owner.user_id)

    with pytest.raises(UserDisabledError):
        await harness.service.archive(
            actor=owner, workspace_id=workspace.id, project_id=project.id
        )

    assert harness.store.organizations == {}


async def test_a_non_member_cannot_reach_a_workspace(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    _, stranger = harness.workspace(name="Stranger", slug="stranger")
    project = harness.project(workspace, name="Field survey", actor=owner)

    with pytest.raises(NotFoundError):
        await harness.service.archive(
            actor=stranger, workspace_id=workspace.id, project_id=project.id
        )
    with pytest.raises(NotFoundError):
        await harness.service.create_folder(
            actor=stranger, workspace_id=workspace.id, name="Nope"
        )

    assert harness.store.organizations == {}
    assert harness.store.folders == {}


async def test_checkpoints_are_read_oldest_first_and_workspace_scoped(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    other, _ = harness.workspace(name="Other", slug="other")
    project = harness.project(workspace, name="Field survey", actor=owner)
    _seed_checkpoint(harness, workspace.id, project.id, revision=2, name="Field survey")
    _seed_checkpoint(harness, workspace.id, project.id, revision=3, name="Renamed")

    checkpoints = await harness.service.list_checkpoints(
        workspace_id=workspace.id, project_id=project.id
    )
    assert [(item.revision, item.name) for item in checkpoints] == [
        (1, "Field survey"),
        (2, "Field survey"),
        (3, "Renamed"),
    ]

    latest = await harness.service.get_checkpoint(
        workspace_id=workspace.id, project_id=project.id, revision=3
    )
    assert latest.name == "Renamed"

    with pytest.raises(NotFoundError):
        await harness.service.get_checkpoint(
            workspace_id=workspace.id, project_id=project.id, revision=4
        )
    with pytest.raises(NotFoundError):
        await harness.service.list_checkpoints(
            workspace_id=other.id, project_id=project.id
        )
    with pytest.raises(NotFoundError):
        await harness.service.get_checkpoint(
            workspace_id=other.id, project_id=project.id, revision=1
        )


async def test_titles_referencing_artifact_counts_head_and_checkpoints(
    harness: Harness,
) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    holder = harness.project(workspace, name="Holder", actor=owner)
    harness.project(workspace, name="Bare", actor=owner)
    artifact_id = uuid4()
    _seed_checkpoint(
        harness,
        workspace.id,
        holder.id,
        revision=2,
        name="Holder",
        document=_project_document_with_artifact(artifact_id),
    )

    titles = await harness.service.titles_referencing_artifact(
        workspace_id=workspace.id, artifact_id=artifact_id
    )

    assert titles == {holder.id: "Holder"}
    assert (
        await harness.service.titles_referencing_artifact(
            workspace_id=workspace.id, artifact_id=uuid4()
        )
        == {}
    )


async def test_reads_never_audit_commit_or_touch_secrets(harness: Harness) -> None:
    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)

    await harness.service.get(workspace_id=workspace.id, project_id=project.id)
    await harness.service.list(workspace_id=workspace.id)
    await harness.service.list_accessible(actor=owner)
    await harness.service.list_checkpoints(
        workspace_id=workspace.id, project_id=project.id
    )

    assert harness.audits == []
    assert all(unit.commit_count == 0 for unit in harness.factory.opened)
    assert harness.factory.secrets_touched is False


async def test_filing_and_archive_mutations_never_touch_node_secrets(
    harness: Harness,
) -> None:
    """Secret re-key is its own task; this service must not start it."""

    workspace, owner = harness.workspace(name="Owner", slug="owner")
    project = harness.project(workspace, name="Field survey", actor=owner)
    folder = await harness.service.create_folder(
        actor=owner, workspace_id=workspace.id, name="Field season"
    )
    await harness.service.assign_folder(
        actor=owner,
        workspace_id=workspace.id,
        project_id=project.id,
        folder_id=folder.id,
    )
    await harness.service.archive(
        actor=owner, workspace_id=workspace.id, project_id=project.id
    )

    assert harness.factory.secrets_touched is False


def _seed_checkpoint(
    harness: Harness,
    workspace_id: UUID,
    project_id: UUID,
    *,
    revision: int,
    name: str,
    document: ProjectDocument | None = None,
) -> ProjectCheckpoint:
    checkpoint = ProjectCheckpoint(
        workspace_id=workspace_id,
        project_id=project_id,
        revision=revision,
        name=name,
        document=empty_project_document("main") if document is None else document,
        created_at=datetime(2026, 1, revision + 1, tzinfo=UTC),
    )
    harness.store.checkpoints[(project_id, revision)] = checkpoint
    return checkpoint


def _project_document_with_artifact(artifact_id: UUID) -> ProjectDocument:
    return ProjectDocument(
        graphs=(
            GraphDefinition(
                id="main",
                name="Main",
                document=GraphDocument(
                    nodes=(
                        GraphNode(
                            kind="builtin",
                            id="upload-1",
                            operator_id="file.upload",
                            operator_version=1,
                            position=GraphPoint(x=0, y=0),
                            config={"artifact_id": str(artifact_id)},
                        ),
                    )
                ),
            ),
        )
    )
