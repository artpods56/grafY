"""Tenant IDOR and role/capability matrix for workspace-qualified routes."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from httpx import Response
from pydantic import SecretStr
from sqlalchemy import select

from grafy_api.settings import Settings
from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreateRequest,
    PersonalAccessTokenScope,
    WorkspaceInvitationCreateRequest,
)
from grafy_api.v1.routes.auth.services import AuthService, IssuedSession
from grafy_api.execution.requests import RunRequest
from grafy_api.v1.routes.node_secrets.models import ConfigureNodeSecretRequest
from grafy_api.graph_contracts import (
    AssignGraphFolderRequest,
    CopyExactHeadRequest,
    CreateSavedGraphRequest,
    GraphFolderWriteRequest,
    SubmitGraphCommandRequest,
    UpdateSavedGraphRequest,
)
from grafy_api.v1.routes.uploads.models import SampleRequest
from grafy_core.application.identity import IdentityService
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.collaboration import RenameGraphCommand
from grafy_core.domain.identity import User, Workspace, WorkspaceKind, WorkspaceRole
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_core.domain.security_audit import SecurityAuditEvent, SecurityAuditOutcome
from grafy_persistence import schema
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.testkit import client_with_overrides, create_db_url, db


def _csrf_headers(issued: IssuedSession) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": issued.csrf_value}


def _auth_service(settings: Settings, database: Database) -> AuthService:
    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    return AuthService(
        settings=settings,
        unit_of_work_factory=unit_of_work_factory,
        identity_service=IdentityService(unit_of_work_factory),
    )


@dataclass(frozen=True)
class AuthorizationMatrix:
    workspace_a: Workspace
    workspace_b: Workspace
    owner_a: User
    viewer_a: User
    editor_a: User
    owner_b: User
    both: User
    artifact_id: UUID


async def _seed_authorization_matrix(database: Database) -> AuthorizationMatrix:
    seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
    owner_a = await seeder.user(email="owner-a@example.test", display_name="Owner A")
    viewer_a = await seeder.user(email="viewer-a@example.test", display_name="Viewer A")
    editor_a = await seeder.user(email="editor-a@example.test", display_name="Editor A")
    owner_b = await seeder.user(email="owner-b@example.test", display_name="Owner B")
    both = await seeder.user(email="both@example.test", display_name="Both Workspaces")
    workspace_a = Workspace(
        slug="workspace-a", name="Workspace A", kind=WorkspaceKind.SHARED
    )
    workspace_b = Workspace(
        slug="workspace-b", name="Workspace B", kind=WorkspaceKind.SHARED
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_workspace(workspace_a)
        await unit_of_work.identity.add_workspace(workspace_b)
        await unit_of_work.commit()
    for user, workspace, role in (
        (owner_a, workspace_a, WorkspaceRole.OWNER),
        (viewer_a, workspace_a, WorkspaceRole.VIEWER),
        (editor_a, workspace_a, WorkspaceRole.EDITOR),
        (both, workspace_a, WorkspaceRole.EDITOR),
        (owner_b, workspace_b, WorkspaceRole.OWNER),
        (both, workspace_b, WorkspaceRole.OWNER),
    ):
        await seeder.membership(user=user, workspace=workspace, role=role)
    artifact = ArtifactObject(
        workspace_id=workspace_a.id,
        artifact_type="scalar.text",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": "workspace-a-secret-payload"},
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.artifacts.add(artifact)
        await unit_of_work.commit()
    return AuthorizationMatrix(
        workspace_a=workspace_a,
        workspace_b=workspace_b,
        owner_a=owner_a,
        viewer_a=viewer_a,
        editor_a=editor_a,
        owner_b=owner_b,
        both=both,
        artifact_id=artifact.id,
    )


def _assert_not_found(response: Response, *, context: object) -> None:
    assert response.status_code == 404, (context, response.status_code, response.text)
    body = response.json()
    assert body["detail"] == "Not found"
    assert body["code"] == "resource.not_found"
    UUID(body["error_id"])


def _assert_forbidden(response: Response, *, context: object) -> None:
    assert response.status_code == 403, (context, response.status_code, response.text)
    body = response.json()
    assert body["detail"] == "Forbidden"
    assert body["code"] == "identity.capability_denied"
    UUID(body["error_id"])


async def test_global_graph_browser_is_authorized_and_keeps_user_state_private(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-authz-browser.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        matrix = await _seed_authorization_matrix(database)
        auth = _auth_service(app_settings, database)
        owner_a_issued = await auth.issue_session(matrix.owner_a.id)
        viewer_a_issued = await auth.issue_session(matrix.viewer_a.id)
        owner_b_issued = await auth.issue_session(matrix.owner_b.id)
        both_issued = await auth.issue_session(matrix.both.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(owner_a_issued)
            workspace_a = api.workspace(matrix.workspace_a.id)
            workspace_b = api.workspace(matrix.workspace_b.id)
            graph_a = workspace_a.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="Workspace A draft", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(owner_a_issued),
            )
            api.authenticate(owner_b_issued)
            graph_b = workspace_b.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="Workspace B private", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(owner_b_issued),
            )

            api.authenticate(owner_a_issued)
            head = workspace_a.graphs.get_head_ok(graph_a.id)
            renamed = workspace_a.graphs.submit_command_ok(
                graph_a.id,
                SubmitGraphCommandRequest(
                    command_id=uuid4(),
                    room_epoch=head.room_epoch,
                    observed_sequence=head.collaboration_sequence,
                    command=RenameGraphCommand(
                        name="Current live-head name",
                        expected_name="Workspace A draft",
                    ),
                ),
                headers=_csrf_headers(owner_a_issued),
            )
            folder = workspace_a.graph_folders.create_ok(
                GraphFolderWriteRequest(name="Research"),
                headers=_csrf_headers(owner_a_issued),
            )
            assigned = workspace_a.graphs.assign_folder_ok(
                graph_a.id,
                AssignGraphFolderRequest(folder_id=folder.id),
                headers=_csrf_headers(owner_a_issued),
            )
            starred = workspace_a.graphs.star(
                graph_a.id, headers=_csrf_headers(owner_a_issued)
            )
            opened = workspace_a.graphs.record_open_ok(
                graph_a.id, headers=_csrf_headers(owner_a_issued)
            )

            assert assigned.folder_id == folder.id
            assert starred.status_code == 200
            assert opened.last_opened_at is not None
            owner_browser = api.graph_browser.list_ok()
            assert [item.id for item in owner_browser.graphs] == [graph_a.id]
            owner_row = owner_browser.graphs[0]
            location = owner_row.location
            assert (
                location.id,
                location.slug,
                location.name,
                location.kind,
            ) == (
                matrix.workspace_a.id,
                "workspace-a",
                "Workspace A",
                WorkspaceKind.SHARED,
            )
            folder_row = owner_row.folder
            assert folder_row is not None
            assert (folder_row.id, folder_row.name) == (folder.id, "Research")
            assert owner_row.starred is True
            assert owner_row.last_opened_at is not None
            draft = owner_row.draft
            assert draft.name == "Current live-head name"
            assert draft.head_sequence == 2
            assert draft.checkpoint_sequence == 1
            assert draft.checkpoint_revision == 1
            assert draft.updated_at == renamed.head.updated_at
            assert (draft.node_count, draft.edge_count) == (0, 0)
            creator = owner_row.creator
            assert creator is not None
            assert (creator.id, creator.display_name) == (
                matrix.owner_a.id,
                "Owner A",
            )

            api.authenticate(viewer_a_issued)
            viewer_browser = api.graph_browser.list_ok()
            viewer_row = viewer_browser.graphs[0]
            assert viewer_row.id == graph_a.id
            assert viewer_row.starred is False
            assert viewer_row.last_opened_at is None
            _assert_forbidden(
                workspace_a.graphs.archive(
                    graph_a.id, headers=_csrf_headers(viewer_a_issued)
                ),
                context="viewer archive graph",
            )
            _assert_forbidden(
                workspace_a.graph_folders.create(
                    GraphFolderWriteRequest(name="Viewer folder"),
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer create folder",
            )
            assert (
                workspace_a.graphs.star(
                    graph_a.id, headers=_csrf_headers(viewer_a_issued)
                ).status_code
                == 200
            )

            api.authenticate(owner_a_issued)
            owner_row_after_viewer_star = api.graph_browser.list_ok().graphs[0]
            assert owner_row_after_viewer_star.starred is True
            unstarred = workspace_a.graphs.unstar_ok(
                graph_a.id, headers=_csrf_headers(owner_a_issued)
            )
            assert unstarred.starred is False
            assert api.graph_browser.list_ok().graphs[0].starred is False

            archived = workspace_a.graphs.archive_ok(
                graph_a.id, headers=_csrf_headers(owner_a_issued)
            )
            assert archived.archived is True
            assert api.graph_browser.list_ok().graphs[0].archived is True
            restored = workspace_a.graphs.restore_ok(
                graph_a.id, headers=_csrf_headers(owner_a_issued)
            )
            assert restored.archived is False

            api.authenticate(both_issued)
            both_browser = api.graph_browser.list_ok()
            assert {item.id for item in both_browser.graphs} == {
                graph_a.id,
                graph_b.id,
            }

            api.authenticate(owner_b_issued)
            revoked = workspace_b.remove_member(
                matrix.both.id,
                headers=_csrf_headers(owner_b_issued),
            )
            assert revoked.status_code == 204
            api.authenticate(both_issued)
            after_revocation = api.graph_browser.list_ok()
            assert [item.id for item in after_revocation.graphs] == [graph_a.id]


async def test_folder_assignment_cannot_cross_workspace_and_delete_unfiles_graphs(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-authz-folders.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        matrix = await _seed_authorization_matrix(database)
        auth = _auth_service(app_settings, database)
        owner_a_issued = await auth.issue_session(matrix.owner_a.id)
        owner_b_issued = await auth.issue_session(matrix.owner_b.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(owner_a_issued)
            workspace_a = api.workspace(matrix.workspace_a.id)
            graph_a = workspace_a.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="Folder boundary", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(owner_a_issued),
            )

            api.authenticate(owner_b_issued)
            foreign_folder = api.workspace(
                matrix.workspace_b.id
            ).graph_folders.create_ok(
                GraphFolderWriteRequest(name="Foreign"),
                headers=_csrf_headers(owner_b_issued),
            )

            api.authenticate(owner_a_issued)
            rejected = workspace_a.graphs.assign_folder(
                graph_a.id,
                AssignGraphFolderRequest(folder_id=foreign_folder.id),
                headers=_csrf_headers(owner_a_issued),
            )
            _assert_not_found(rejected, context="cross-workspace folder assignment")

            own_folder = workspace_a.graph_folders.create_ok(
                GraphFolderWriteRequest(name="Temporary"),
                headers=_csrf_headers(owner_a_issued),
            )
            renamed = workspace_a.graph_folders.rename_ok(
                own_folder.id,
                GraphFolderWriteRequest(name="  Renamed  "),
                headers=_csrf_headers(owner_a_issued),
            )
            listed = workspace_a.graph_folders.list_ok()
            duplicate = workspace_a.graph_folders.create(
                GraphFolderWriteRequest(name="Renamed"),
                headers=_csrf_headers(owner_a_issued),
            )
            assert renamed.name == "Renamed"
            assert listed.folders == [renamed]
            assert duplicate.status_code == 409
            assigned = workspace_a.graphs.assign_folder_ok(
                graph_a.id,
                AssignGraphFolderRequest(folder_id=own_folder.id),
                headers=_csrf_headers(owner_a_issued),
            )
            assert assigned.folder_id == own_folder.id
            unfiled = workspace_a.graphs.assign_folder_ok(
                graph_a.id,
                AssignGraphFolderRequest(folder_id=None),
                headers=_csrf_headers(owner_a_issued),
            )
            assert unfiled.folder_id is None
            reassigned = workspace_a.graphs.assign_folder(
                graph_a.id,
                AssignGraphFolderRequest(folder_id=own_folder.id),
                headers=_csrf_headers(owner_a_issued),
            )
            assert reassigned.status_code == 200

            deleted = workspace_a.graph_folders.delete(
                own_folder.id,
                headers=_csrf_headers(owner_a_issued),
            )
            row = api.graph_browser.list_ok().graphs[0]
            assert deleted.status_code == 204
            assert row.id == graph_a.id
            assert row.folder is None


async def test_non_member_cannot_read_or_write_other_workspace_by_uuid(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-authz-idor.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        matrix = await _seed_authorization_matrix(database)
        auth = _auth_service(app_settings, database)
        owner_a_issued = await auth.issue_session(matrix.owner_a.id)
        owner_b_issued = await auth.issue_session(matrix.owner_b.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(owner_b_issued)
            workspace_b = api.workspace(matrix.workspace_b.id)
            graph_b = workspace_b.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="B private graph", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(owner_b_issued),
            )
            execution_b = workspace_b.executions.start_execution_ok(
                RunRequest(nodes=[], edges=[]),
                headers=_csrf_headers(owner_b_issued),
            )

            api.authenticate(owner_a_issued)
            _assert_not_found(workspace_b.catalog.list_nodes(), context="nodes")
            _assert_not_found(workspace_b.graphs.list(), context="list graphs")
            _assert_not_found(workspace_b.graphs.get(graph_b.id), context="get graph")
            _assert_not_found(
                workspace_b.graphs.create(
                    CreateSavedGraphRequest(
                        name="Authz graph", document=SavedGraphDocument()
                    ),
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="create graph",
            )
            _assert_not_found(
                workspace_b.graphs.update(
                    graph_b.id,
                    UpdateSavedGraphRequest(
                        name="Authz graph",
                        document=SavedGraphDocument(),
                        expected_revision=graph_b.revision,
                    ),
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="update graph",
            )
            _assert_not_found(
                workspace_b.graphs.delete(
                    graph_b.id,
                    expected_revision=graph_b.revision,
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="delete graph",
            )
            _assert_not_found(
                workspace_b.node_secrets.list_secrets(graph_b.id),
                context="list secrets",
            )
            _assert_not_found(
                workspace_b.node_secrets.configure_secret(
                    graph_b.id,
                    "llm",
                    "api_key",
                    ConfigureNodeSecretRequest(
                        value=SecretStr("secret"),
                        expected_graph_revision=graph_b.revision,
                    ),
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="put secret",
            )
            _assert_not_found(
                workspace_b.executions.run(
                    RunRequest(nodes=[], edges=[]),
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="run",
            )
            _assert_not_found(
                workspace_b.executions.start_execution(
                    RunRequest(nodes=[], edges=[]),
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="start execution",
            )
            _assert_not_found(
                workspace_b.executions.get_execution(execution_b.execution_id),
                context="get execution",
            )
            _assert_not_found(
                workspace_b.executions.stream_execution_events(
                    execution_b.execution_id
                ),
                context="sse",
            )
            _assert_not_found(
                workspace_b.executions.cancel_execution(
                    execution_b.execution_id,
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="cancel execution",
            )
            _assert_not_found(
                workspace_b.executions.list_materializations(
                    graph_b.id,
                    graph_revision=graph_b.revision,
                ),
                context="materializations",
            )
            _assert_not_found(
                workspace_b.executions.list_graph_executions(graph_b.id),
                context="history",
            )
            _assert_not_found(
                workspace_b.artifacts.content(matrix.artifact_id),
                context="artifact content",
            )
            _assert_not_found(
                workspace_b.uploads.upload(
                    "sample.png",
                    b"\x89PNG\r\n\x1a\n",
                    content_type="image/png",
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="upload",
            )
            _assert_not_found(
                workspace_b.uploads.create_samples(
                    SampleRequest(count=1),
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="samples",
            )
            _assert_not_found(workspace_b.list_members(), context="list members")
            _assert_not_found(
                workspace_b.create_invitation(
                    WorkspaceInvitationCreateRequest(
                        email=matrix.viewer_a.email or "viewer-a@example.test",
                        role=WorkspaceRole.VIEWER,
                    ),
                    headers=_csrf_headers(owner_a_issued),
                ),
                context="create invitation",
            )


async def test_viewer_can_read_but_cannot_mutate_execute_or_manage_secrets(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-authz-viewer.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        matrix = await _seed_authorization_matrix(database)
        auth = _auth_service(app_settings, database)
        owner_a_issued = await auth.issue_session(matrix.owner_a.id)
        editor_a_issued = await auth.issue_session(matrix.editor_a.id)
        viewer_a_issued = await auth.issue_session(matrix.viewer_a.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(owner_a_issued)
            workspace_a = api.workspace(matrix.workspace_a.id)
            graph_a = workspace_a.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="Shared readable graph", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(owner_a_issued),
            )
            api.authenticate(editor_a_issued)
            execution = workspace_a.executions.start_execution_ok(
                RunRequest(nodes=[], edges=[]),
                headers=_csrf_headers(editor_a_issued),
            )

            api.authenticate(viewer_a_issued)
            assert workspace_a.catalog.list_nodes().status_code == 200
            assert workspace_a.graphs.list().status_code == 200
            assert workspace_a.graphs.get(graph_a.id).status_code == 200
            assert workspace_a.node_secrets.list_secrets(graph_a.id).status_code == 200
            assert workspace_a.artifacts.content(matrix.artifact_id).status_code == 200
            assert (
                workspace_a.executions.get_execution(execution.execution_id).status_code
                == 200
            )
            assert (
                workspace_a.executions.list_materializations(
                    graph_a.id,
                    graph_revision=graph_a.revision,
                ).status_code
                == 200
            )
            assert (
                workspace_a.executions.list_graph_executions(graph_a.id).status_code
                == 200
            )

            _assert_forbidden(
                workspace_a.graphs.create(
                    CreateSavedGraphRequest(
                        name="viewer", document=SavedGraphDocument()
                    ),
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer create graph",
            )
            _assert_forbidden(
                workspace_a.graphs.update(
                    graph_a.id,
                    UpdateSavedGraphRequest(
                        name="viewer edit",
                        document=SavedGraphDocument(),
                        expected_revision=graph_a.revision,
                    ),
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer update graph",
            )
            _assert_forbidden(
                workspace_a.graphs.delete(
                    graph_a.id,
                    expected_revision=graph_a.revision,
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer delete graph",
            )
            _assert_forbidden(
                workspace_a.node_secrets.configure_secret(
                    graph_a.id,
                    "llm",
                    "api_key",
                    ConfigureNodeSecretRequest(
                        value=SecretStr("secret"),
                        expected_graph_revision=graph_a.revision,
                    ),
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer put secret",
            )
            _assert_forbidden(
                workspace_a.node_secrets.remove_secret(
                    graph_a.id,
                    "llm",
                    "api_key",
                    graph_a.revision,
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer delete secret",
            )
            _assert_forbidden(
                workspace_a.executions.run(
                    RunRequest(nodes=[], edges=[]),
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer run",
            )
            _assert_forbidden(
                workspace_a.executions.start_execution(
                    RunRequest(nodes=[], edges=[]),
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer start execution",
            )
            _assert_forbidden(
                workspace_a.executions.cancel_execution(
                    execution.execution_id,
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer cancel",
            )
            _assert_forbidden(
                workspace_a.uploads.upload(
                    "sample.png",
                    b"\x89PNG\r\n\x1a\n",
                    content_type="image/png",
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer upload",
            )
            _assert_forbidden(
                workspace_a.uploads.create_samples(
                    SampleRequest(count=1),
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer samples",
            )
            _assert_forbidden(
                workspace_a.create_invitation(
                    WorkspaceInvitationCreateRequest(
                        email=matrix.owner_b.email or "owner-b@example.test",
                        role=WorkspaceRole.VIEWER,
                    ),
                    headers=_csrf_headers(viewer_a_issued),
                ),
                context="viewer create invitation",
            )


async def test_editor_can_edit_and_execute_but_not_manage_secrets_delete_or_members(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-authz-editor.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        matrix = await _seed_authorization_matrix(database)
        auth = _auth_service(app_settings, database)
        editor_a_issued = await auth.issue_session(matrix.editor_a.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(editor_a_issued)
            workspace_a = api.workspace(matrix.workspace_a.id)
            graph_a = workspace_a.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="Editor draft", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(editor_a_issued),
            )
            updated = workspace_a.graphs.update_ok(
                graph_a.id,
                UpdateSavedGraphRequest(
                    name="Editor updated",
                    document=SavedGraphDocument(),
                    expected_revision=graph_a.revision,
                ),
                headers=_csrf_headers(editor_a_issued),
            )
            revision = updated.revision

            run = workspace_a.executions.run(
                RunRequest(nodes=[], edges=[]),
                headers=_csrf_headers(editor_a_issued),
            )
            execution = workspace_a.executions.start_execution_ok(
                RunRequest(nodes=[], edges=[]),
                headers=_csrf_headers(editor_a_issued),
            )
            events = workspace_a.executions.stream_execution_events(
                execution.execution_id
            )
            upload = workspace_a.uploads.upload(
                "sample.png",
                b"\x89PNG\r\n\x1a\n",
                content_type="image/png",
                headers=_csrf_headers(editor_a_issued),
            )

            assert run.status_code == 200
            assert (
                workspace_a.executions.get_execution(execution.execution_id).status_code
                == 200
            )
            assert events.status_code == 200
            assert "text/event-stream" in events.headers["content-type"]
            assert events.text  # at least one lifecycle frame for the empty graph run
            assert upload.status_code == 200

            _assert_forbidden(
                workspace_a.node_secrets.configure_secret(
                    graph_a.id,
                    "llm",
                    "api_key",
                    ConfigureNodeSecretRequest(
                        value=SecretStr("secret"),
                        expected_graph_revision=revision,
                    ),
                    headers=_csrf_headers(editor_a_issued),
                ),
                context="editor put secret",
            )
            _assert_forbidden(
                workspace_a.node_secrets.remove_secret(
                    graph_a.id,
                    "llm",
                    "api_key",
                    revision,
                    headers=_csrf_headers(editor_a_issued),
                ),
                context="editor delete secret",
            )
            _assert_forbidden(
                workspace_a.graphs.delete(
                    graph_a.id,
                    expected_revision=revision,
                    headers=_csrf_headers(editor_a_issued),
                ),
                context="editor delete graph",
            )
            _assert_forbidden(
                workspace_a.list_members(),
                context="editor list members",
            )
            _assert_forbidden(
                workspace_a.create_invitation(
                    WorkspaceInvitationCreateRequest(
                        email=matrix.owner_b.email or "owner-b@example.test",
                        role=WorkspaceRole.VIEWER,
                    ),
                    headers=_csrf_headers(editor_a_issued),
                ),
                context="editor create invitation",
            )


async def test_owner_can_manage_secrets_delete_graph_and_members(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-authz-owner.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        matrix = await _seed_authorization_matrix(database)
        auth = _auth_service(app_settings, database)
        owner_a_issued = await auth.issue_session(matrix.owner_a.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(owner_a_issued)
            workspace_a = api.workspace(matrix.workspace_a.id)
            graph_a = workspace_a.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="Owner managed graph", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(owner_a_issued),
            )

            # Capability gate is before resource lookup: owner clears MANAGE_SECRETS
            # (404 for undeclared secret) while editor/viewer receive 403 above.
            secret_put = workspace_a.node_secrets.configure_secret(
                graph_a.id,
                "missing",
                "api_key",
                ConfigureNodeSecretRequest(
                    value=SecretStr("secret"),
                    expected_graph_revision=graph_a.revision,
                ),
                headers=_csrf_headers(owner_a_issued),
            )
            assert secret_put.status_code == 404

            members = workspace_a.list_members_ok()
            member_ids = {member.user.id for member in members}
            deleted = workspace_a.graphs.delete(
                graph_a.id,
                expected_revision=graph_a.revision,
                headers=_csrf_headers(owner_a_issued),
            )

            assert matrix.owner_a.id in member_ids
            assert matrix.viewer_a.id in member_ids
            assert matrix.editor_a.id in member_ids
            assert deleted.status_code == 204
            assert workspace_a.graphs.get(graph_a.id).status_code == 404


async def test_cross_workspace_resource_ids_do_not_authorize_via_wrong_path(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "workspace-authz-cross-path.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        matrix = await _seed_authorization_matrix(database)
        auth = _auth_service(app_settings, database)
        owner_a_issued = await auth.issue_session(matrix.owner_a.id)
        owner_b_issued = await auth.issue_session(matrix.owner_b.id)
        both_issued = await auth.issue_session(matrix.both.id)

        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(owner_a_issued)
            workspace_a = api.workspace(matrix.workspace_a.id)
            graph_a = workspace_a.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="Graph in A", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(owner_a_issued),
            )
            execution_a = workspace_a.executions.start_execution_ok(
                RunRequest(nodes=[], edges=[]),
                headers=_csrf_headers(owner_a_issued),
            )
            api.authenticate(owner_b_issued)
            workspace_b = api.workspace(matrix.workspace_b.id)
            graph_b = workspace_b.graphs.create_ok(
                CreateSavedGraphRequest(
                    name="Graph in B", document=SavedGraphDocument()
                ),
                headers=_csrf_headers(owner_b_issued),
            )

            # Member of both workspaces still cannot reach A resources under B's path.
            api.authenticate(both_issued)
            assert workspace_a.graphs.get(graph_a.id).status_code == 200
            assert workspace_b.graphs.get(graph_b.id).status_code == 200

            wrong_path_reads = (
                workspace_b.graphs.get(graph_a.id),
                workspace_a.graphs.get(graph_b.id),
                workspace_b.node_secrets.list_secrets(graph_a.id),
                workspace_b.artifacts.content(matrix.artifact_id),
                workspace_b.executions.get_execution(execution_a.execution_id),
                workspace_b.executions.stream_execution_events(
                    execution_a.execution_id
                ),
                workspace_b.executions.list_graph_executions(graph_a.id),
                workspace_a.executions.list_graph_executions(graph_b.id),
            )
            for response in wrong_path_reads:
                assert response.status_code == 404, (
                    response.request.url,
                    response.status_code,
                    response.text,
                )

            wrong_materializations = (
                workspace_b.executions.list_materializations(
                    graph_a.id,
                    graph_revision=graph_a.revision,
                ),
                workspace_a.executions.list_materializations(
                    graph_b.id,
                    graph_revision=graph_b.revision,
                ),
            )
            for response in wrong_materializations:
                assert response.status_code == 404

            wrong_secret = workspace_b.node_secrets.configure_secret(
                graph_a.id,
                "llm",
                "api_key",
                ConfigureNodeSecretRequest(
                    value=SecretStr("secret"),
                    expected_graph_revision=graph_a.revision,
                ),
                headers=_csrf_headers(both_issued),
            )
            wrong_delete = workspace_b.graphs.delete(
                graph_a.id,
                expected_revision=graph_a.revision,
                headers=_csrf_headers(both_issued),
            )
            assert wrong_secret.status_code == 404
            assert wrong_delete.status_code == 404

            # Resource remains readable under its owning workspace path.
            assert workspace_a.graphs.get(graph_a.id).status_code == 200
            assert workspace_a.artifacts.content(matrix.artifact_id).status_code == 200


async def test_target_bound_pat_cannot_copy_graph_from_another_workspace(
    tmp_path: Path, settings: Settings
) -> None:
    database_url = create_db_url(tmp_path, "pat-cross-workspace-copy.sqlite3")
    async with db(database_url) as database:
        app_settings = settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
            }
        )
        matrix = await _seed_authorization_matrix(database)
        issued = await _auth_service(app_settings, database).issue_session(
            matrix.both.id
        )
        with client_with_overrides(settings=app_settings) as client:
            api = GrafyApi(client)
            api.authenticate(issued)
            source = api.workspace(matrix.workspace_a.id).graphs
            target = api.workspace(matrix.workspace_b.id)
            graph = source.create_ok(
                CreateSavedGraphRequest(name="Source", document=SavedGraphDocument()),
                headers=_csrf_headers(issued),
            )
            head = source.get_head_ok(graph.id)
            request = CopyExactHeadRequest(
                source_workspace_id=matrix.workspace_a.id,
                source_graph_id=graph.id,
                expected_room_epoch=head.room_epoch,
                expected_sequence=head.collaboration_sequence,
                command_id=uuid4(),
                name="Browser copy",
            )
            copied = target.graphs.copy_ok(request, headers=_csrf_headers(issued))
            assert copied.name == "Browser copy"
            created = target.create_token_ok(
                PersonalAccessTokenCreateRequest(
                    label="target-workspace-copy",
                    scopes=(
                        PersonalAccessTokenScope.VIEW_GRAPH,
                        PersonalAccessTokenScope.CREATE_GRAPH,
                        PersonalAccessTokenScope.EDIT_GRAPH,
                        PersonalAccessTokenScope.CHECKPOINT_GRAPH,
                    ),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                headers=_csrf_headers(issued),
            )
            before = target.graphs.list_ok().model_dump()
            client.cookies.clear()
            response = target.graphs.copy(
                request.model_copy(update={"command_id": uuid4(), "name": "PAT copy"}),
                headers={"Authorization": f"Bearer {created.token.get_secret_value()}"},
            )
            assert response.status_code == 404, response.text
            api.authenticate(issued)
            assert target.graphs.list_ok().model_dump() == before

        async with database.sessions() as session:
            events = list(
                await session.scalars(
                    select(SecurityAuditEvent).where(
                        schema.security_audit_events.c.operation
                        == "collaboration.graph.copy",
                        schema.security_audit_events.c.outcome
                        == SecurityAuditOutcome.FAILURE,
                    )
                )
            )
        assert len(events) == 1
        assert events[0].user_id == matrix.both.id
        assert events[0].workspace_id == matrix.workspace_a.id
        assert events[0].resource_id == str(graph.id)
        assert events[0].credential_reference == f"pat:{created.id}"
        assert events[0].error_code == "not_found"
