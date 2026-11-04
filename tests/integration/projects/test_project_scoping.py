"""Every Project route is Workspace-scoped and capability-gated (ADR 0020).

Three rules hold across the whole surface, so they are tested as lists of routes
rather than route by route:

* **A Project of another Workspace is not there.** A member of both Workspaces asking
  for the first one's Project under the second one's path gets 404, never a 403 that
  would confirm the Project exists.
* **The capability is asked for before the Project is touched.** A principal without
  it is refused even when the Project sits in its own Workspace.
* **The browser follows membership, not the path.** A Project is listed where the
  caller can see it, and nowhere else.

Real sessions and real personal access tokens drive these requests, with no identity
override: a gate is only proven when the caller is the kind of principal the route
answers to.
"""

import asyncio
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import Response
from pydantic import SecretStr

from grafy_core.application.identity import IdentityService
from grafy_core.domain.collaboration import RenameProjectCommand
from grafy_core.domain.identity import User, Workspace, WorkspaceKind, WorkspaceRole
from grafy_api.project_contracts import (
    AssignProjectFolderRequest,
    CheckpointProjectRequest,
    CopyExactHeadRequest,
    CreateProjectRequest,
    ProjectFolderWriteRequest,
    ProjectHeadResponse,
    SubmitProjectCommandRequest,
)
from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.services import AuthService, IssuedSession
from grafy_api.v1.routes.node_secrets.models import ConfigureNodeSecretRequest
from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreateRequest,
    PersonalAccessTokenScope,
)
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig

from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.testkit import client_with_overrides, create_db_url, db, with_setting_values

MAIN = "main"
# A personal access token that can see the Workspace and nothing of its Projects.
PAT_WITHOUT_PROJECTS = PersonalAccessTokenScope.VIEW_ARTIFACTS


def _csrf(issued: IssuedSession) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": issued.csrf_value}


def _auth_service(settings: Settings, database: Database) -> AuthService:
    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    return AuthService(
        auth=settings.auth,
        public_origin=settings.app.public_origin,
        unit_of_work_factory=unit_of_work_factory,
        identity_service=IdentityService(unit_of_work_factory),
    )


@dataclass(frozen=True)
class Matrix:
    workspace_a: Workspace
    workspace_b: Workspace
    owner_a: User
    viewer_a: User
    editor_a: User
    owner_b: User
    both: User


async def _seed_matrix(database: Database) -> Matrix:
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
    return Matrix(
        workspace_a=workspace_a,
        workspace_b=workspace_b,
        owner_a=owner_a,
        viewer_a=viewer_a,
        editor_a=editor_a,
        owner_b=owner_b,
        both=both,
    )


@dataclass
class Stage:
    """The live app, one Project and one folder in each Workspace, and its callers."""

    client: object
    api: GrafyApi
    matrix: Matrix
    a: UUID
    b: UUID
    project_a: UUID
    project_b: UUID
    folder_a: UUID
    folder_b: UUID
    sessions: dict[str, IssuedSession]
    pat_without_projects: str

    def projects(self, workspace_id: UUID):
        return self.api.workspace(workspace_id).projects

    def folders(self, workspace_id: UUID):
        return self.api.workspace(workspace_id).project_folders

    def secrets(self, workspace_id: UUID):
        return self.api.workspace(workspace_id).node_secrets

    def projects_get(self, workspace_id: UUID, project_id: UUID, who: str) -> Response:
        return self.projects(workspace_id).get(project_id, headers=self.as_(who))

    def projects_get_head(
        self, workspace_id: UUID, project_id: UUID, who: str
    ) -> Response:
        return self.projects(workspace_id).get_head(project_id, headers=self.as_(who))

    def projects_delete(
        self, workspace_id: UUID, project_id: UUID, who: str
    ) -> Response:
        return self.projects(workspace_id).delete(project_id, headers=self.as_(who))

    def as_(self, who: str) -> dict[str, str]:
        """Become one browser caller for the next request."""

        self.api.raw.cookies.clear()
        self.api.authenticate(self.sessions[who])
        return _csrf(self.sessions[who])

    def as_pat(self) -> dict[str, str]:
        """Drop the browser session so only the token authenticates the request."""

        self.api.raw.cookies.clear()
        return {"Authorization": f"Bearer {self.pat_without_projects}"}

    def scoped_token(
        self, label: str, *scopes: PersonalAccessTokenScope
    ) -> dict[str, str]:
        """Mint a Workspace token holding exactly these scopes, as bearer headers.

        Minted by `owner_a`, so every token here belongs to Workspace A and differs from
        the others only in its scope: a refusal can then only be about the scope.
        """

        issued = self.api.workspace(self.a).create_token_ok(
            PersonalAccessTokenCreateRequest(
                label=label,
                scopes=scopes,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            headers=self.as_("owner_a"),
        )
        self.api.raw.cookies.clear()
        return {"Authorization": f"Bearer {issued.token.get_secret_value()}"}


@contextmanager
def _stage(
    tmp_path: Path,
    database_url: str,
    matrix: Matrix,
    sessions: dict[str, IssuedSession],
) -> Iterator[Stage]:
    settings = with_setting_values(
        Settings(
            app=AppConfig(
                public_origin="http://testserver",
                database_url=SecretStr("sqlite+aiosqlite:///"),
            )
        ),
        database_url=SecretStr(database_url),
        workspace=tmp_path / "workbench",
    )
    # No identity override here: the routes have to answer to the session or token the
    # caller actually presented.
    with client_with_overrides(settings=settings) as client:
        api = GrafyApi(client)
        api.authenticate(sessions["owner_a"])
        projects_a = api.workspace(matrix.workspace_a.id).projects
        project_a = projects_a.create_ok(
            CreateProjectRequest(name="Project in A"),
            headers=_csrf(sessions["owner_a"]),
        )
        folder_a = api.workspace(matrix.workspace_a.id).project_folders.create_ok(
            ProjectFolderWriteRequest(name="Folder in A"),
            headers=_csrf(sessions["owner_a"]),
        )
        api.authenticate(sessions["owner_b"])
        project_b = api.workspace(matrix.workspace_b.id).projects.create_ok(
            CreateProjectRequest(name="Project in B"),
            headers=_csrf(sessions["owner_b"]),
        )
        folder_b = api.workspace(matrix.workspace_b.id).project_folders.create_ok(
            ProjectFolderWriteRequest(name="Folder in B"),
            headers=_csrf(sessions["owner_b"]),
        )
        api.authenticate(sessions["owner_a"])
        token = api.workspace(matrix.workspace_a.id).create_token_ok(
            PersonalAccessTokenCreateRequest(
                label="no-project-scopes",
                scopes=(PAT_WITHOUT_PROJECTS,),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            headers=_csrf(sessions["owner_a"]),
        )
        yield Stage(
            client=client,
            api=api,
            matrix=matrix,
            a=matrix.workspace_a.id,
            b=matrix.workspace_b.id,
            project_a=project_a.id,
            project_b=project_b.id,
            folder_a=folder_a.id,
            folder_b=folder_b.id,
            sessions=sessions,
            pat_without_projects=token.token.get_secret_value(),
        )


async def _sessions(
    settings: Settings, database: Database, matrix: Matrix
) -> dict[str, IssuedSession]:
    auth = _auth_service(settings, database)
    return {
        "owner_a": await auth.issue_session(matrix.owner_a.id),
        "viewer_a": await auth.issue_session(matrix.viewer_a.id),
        "editor_a": await auth.issue_session(matrix.editor_a.id),
        "owner_b": await auth.issue_session(matrix.owner_b.id),
        "both": await auth.issue_session(matrix.both.id),
    }


@contextmanager
def stage_for(tmp_path: Path, name: str) -> Iterator[Stage]:
    """One database, its seeded identities and sessions, and the app on top of it."""

    database_url = create_db_url(tmp_path, name)
    settings = with_setting_values(
        Settings(
            app=AppConfig(
                public_origin="http://testserver",
                database_url=SecretStr("sqlite+aiosqlite:///"),
            )
        ),
        database_url=SecretStr(database_url),
        workspace=tmp_path / "workbench",
    )

    async def prepare() -> tuple[Matrix, dict[str, IssuedSession]]:
        async with db(database_url) as database:
            matrix = await _seed_matrix(database)
            return matrix, await _sessions(settings, database, matrix)

    matrix, sessions = asyncio.run(prepare())
    with _stage(tmp_path, database_url, matrix, sessions) as stage:
        yield stage


# --- the routes, by name ------------------------------------------------------


@dataclass(frozen=True)
class Call:
    """One request, named for the assertion that failed on it."""

    name: str
    send: Callable[[Stage], Response]


def _commands(stage: Stage, workspace: UUID, project: UUID, who: str) -> Response:
    return stage.api.workspace(workspace).projects.submit_commands(
        project,
        SubmitProjectCommandRequest(
            command_id=uuid4(),
            room_epoch=uuid4(),
            observed_sequence=0,
            commands=(RenameProjectCommand(name="Moved", expected_name="Whatever"),),
        ),
        headers=stage.as_(who),
    )


def _checkpoint_request() -> CheckpointProjectRequest:
    return CheckpointProjectRequest(expected_room_epoch=uuid4(), expected_sequence=0)


def _where_the_head_is(head: ProjectHeadResponse) -> CheckpointProjectRequest:
    """A checkpoint request that agrees with where the head actually is."""

    return CheckpointProjectRequest(
        expected_room_epoch=head.room_epoch,
        expected_sequence=head.collaboration_sequence,
    )


def _rename_request(
    head: ProjectHeadResponse, name: str, expected_name: str
) -> SubmitProjectCommandRequest:
    return SubmitProjectCommandRequest(
        command_id=uuid4(),
        room_epoch=head.room_epoch,
        observed_sequence=head.collaboration_sequence,
        commands=(RenameProjectCommand(name=name, expected_name=expected_name),),
    )


def _secret_request() -> ConfigureNodeSecretRequest:
    return ConfigureNodeSecretRequest(
        value=SecretStr("provider-key"), expected_head_sequence=0
    )


# Made by `both`, a member of both Workspaces: the capability gate lets it through,
# so only tenancy can answer. Every one of these names a Project or folder that lives
# in Workspace A and is asked for under Workspace B.
FOREIGN: tuple[Call, ...] = (
    Call("get project", lambda s: s.projects_get(s.b, s.project_a, "both")),
    Call("delete project", lambda s: s.projects_delete(s.b, s.project_a, "both")),
    Call("read head", lambda s: s.projects_get_head(s.b, s.project_a, "both")),
    Call("submit commands", lambda s: _commands(s, s.b, s.project_a, "both")),
    Call(
        "checkpoint",
        lambda s: s.projects(s.b).checkpoint(
            s.project_a, _checkpoint_request(), headers=s.as_("both")
        ),
    ),
    Call(
        "list checkpoints",
        lambda s: s.projects(s.b).list_checkpoints(s.project_a, headers=s.as_("both")),
    ),
    Call(
        "read checkpoint",
        lambda s: s.projects(s.b).get_checkpoint(s.project_a, 1, headers=s.as_("both")),
    ),
    Call(
        "restore checkpoint",
        lambda s: s.projects(s.b).restore_checkpoint(
            s.project_a, 1, _checkpoint_request(), headers=s.as_("both")
        ),
    ),
    Call(
        "assign folder",
        lambda s: s.projects(s.b).assign_folder(
            s.project_a,
            AssignProjectFolderRequest(folder_id=None),
            headers=s.as_("both"),
        ),
    ),
    Call(
        "archive project",
        lambda s: s.projects(s.b).archive(s.project_a, headers=s.as_("both")),
    ),
    Call(
        "unarchive project",
        lambda s: s.projects(s.b).unarchive(s.project_a, headers=s.as_("both")),
    ),
    Call(
        "star project",
        lambda s: s.projects(s.b).star(s.project_a, headers=s.as_("both")),
    ),
    Call(
        "unstar project",
        lambda s: s.projects(s.b).unstar(s.project_a, headers=s.as_("both")),
    ),
    Call(
        "record open",
        lambda s: s.projects(s.b).record_open(s.project_a, headers=s.as_("both")),
    ),
    Call(
        "list node secrets",
        lambda s: s.secrets(s.b).list_secrets(s.project_a, headers=s.as_("both")),
    ),
    Call(
        "configure node secret",
        lambda s: s.secrets(s.b).configure_secret(
            s.project_a,
            MAIN,
            "llm",
            "api_key",
            _secret_request(),
            headers=s.as_("both"),
        ),
    ),
    Call(
        "delete node secret",
        lambda s: s.secrets(s.b).remove_secret(
            s.project_a, MAIN, "llm", "api_key", 0, headers=s.as_("both")
        ),
    ),
    Call(
        "rename a folder of another workspace",
        lambda s: s.folders(s.b).rename(
            s.folder_a,
            ProjectFolderWriteRequest(name="Taken"),
            headers=s.as_("both"),
        ),
    ),
    Call(
        "delete a folder of another workspace",
        lambda s: s.folders(s.b).delete(s.folder_a, headers=s.as_("both")),
    ),
    Call(
        "file a project into a folder of another workspace",
        lambda s: s.projects(s.a).assign_folder(
            s.project_a,
            AssignProjectFolderRequest(folder_id=s.folder_b),
            headers=s.as_("both"),
        ),
    ),
    Call(
        "create in a workspace the caller is not a member of",
        lambda s: s.projects(s.b).create(
            CreateProjectRequest(name="Elsewhere"), headers=s.as_("owner_a")
        ),
    ),
    Call(
        "copy from a workspace the caller is not a member of",
        lambda s: s.projects(s.b).copy(
            CopyExactHeadRequest(
                source_workspace_id=s.a,
                source_project_id=s.project_a,
                project_id=uuid4(),
                expected_room_epoch=uuid4(),
                expected_sequence=0,
                command_id=uuid4(),
            ),
            headers=s.as_("owner_b"),
        ),
    ),
)

# A viewer may read Projects and nothing else of them.
VIEWER_DENIED: tuple[Call, ...] = (
    Call(
        "create project",
        lambda s: s.projects(s.a).create(
            CreateProjectRequest(name="Viewer"), headers=s.as_("viewer_a")
        ),
    ),
    Call(
        "copy project",
        lambda s: s.projects(s.a).copy(
            CopyExactHeadRequest(
                source_workspace_id=s.a,
                source_project_id=s.project_a,
                project_id=uuid4(),
                expected_room_epoch=uuid4(),
                expected_sequence=0,
                command_id=uuid4(),
            ),
            headers=s.as_("viewer_a"),
        ),
    ),
    Call("submit commands", lambda s: _commands(s, s.a, s.project_a, "viewer_a")),
    Call(
        "checkpoint",
        lambda s: s.projects(s.a).checkpoint(
            s.project_a, _checkpoint_request(), headers=s.as_("viewer_a")
        ),
    ),
    Call(
        "restore checkpoint",
        lambda s: s.projects(s.a).restore_checkpoint(
            s.project_a, 1, _checkpoint_request(), headers=s.as_("viewer_a")
        ),
    ),
    Call(
        "assign folder",
        lambda s: s.projects(s.a).assign_folder(
            s.project_a,
            AssignProjectFolderRequest(folder_id=s.folder_a),
            headers=s.as_("viewer_a"),
        ),
    ),
    Call(
        "archive project",
        lambda s: s.projects(s.a).archive(s.project_a, headers=s.as_("viewer_a")),
    ),
    Call(
        "unarchive project",
        lambda s: s.projects(s.a).unarchive(s.project_a, headers=s.as_("viewer_a")),
    ),
    Call(
        "create folder",
        lambda s: s.folders(s.a).create(
            ProjectFolderWriteRequest(name="Viewer folder"), headers=s.as_("viewer_a")
        ),
    ),
    Call(
        "rename folder",
        lambda s: s.folders(s.a).rename(
            s.folder_a,
            ProjectFolderWriteRequest(name="Viewer"),
            headers=s.as_("viewer_a"),
        ),
    ),
    Call(
        "delete folder",
        lambda s: s.folders(s.a).delete(s.folder_a, headers=s.as_("viewer_a")),
    ),
)

# An editor may change a Project but not end it, and never holds a credential.
EDITOR_DENIED: tuple[Call, ...] = (
    Call("delete project", lambda s: s.projects_delete(s.a, s.project_a, "editor_a")),
    Call(
        "configure node secret",
        lambda s: s.secrets(s.a).configure_secret(
            s.project_a,
            MAIN,
            "llm",
            "api_key",
            _secret_request(),
            headers=s.as_("editor_a"),
        ),
    ),
    Call(
        "delete node secret",
        lambda s: s.secrets(s.a).remove_secret(
            s.project_a, MAIN, "llm", "api_key", 0, headers=s.as_("editor_a")
        ),
    ),
)

# Every read of the surface: a token with no Project scope cannot do them.
PAT_DENIED: tuple[Call, ...] = (
    Call("list projects", lambda s: s.projects(s.a).list(headers=s.as_pat())),
    Call("get project", lambda s: s.projects(s.a).get(s.project_a, headers=s.as_pat())),
    Call(
        "read head", lambda s: s.projects(s.a).get_head(s.project_a, headers=s.as_pat())
    ),
    Call(
        "list checkpoints",
        lambda s: s.projects(s.a).list_checkpoints(s.project_a, headers=s.as_pat()),
    ),
    Call(
        "read checkpoint",
        lambda s: s.projects(s.a).get_checkpoint(s.project_a, 1, headers=s.as_pat()),
    ),
    Call(
        "star project", lambda s: s.projects(s.a).star(s.project_a, headers=s.as_pat())
    ),
    Call(
        "unstar project",
        lambda s: s.projects(s.a).unstar(s.project_a, headers=s.as_pat()),
    ),
    Call(
        "record open",
        lambda s: s.projects(s.a).record_open(s.project_a, headers=s.as_pat()),
    ),
    Call(
        "list node secrets",
        lambda s: s.secrets(s.a).list_secrets(s.project_a, headers=s.as_pat()),
    ),
    Call("list folders", lambda s: s.folders(s.a).list(headers=s.as_pat())),
)


def _names(calls: Sequence[Call]) -> list[str]:
    return [call.name for call in calls]


def _find(calls: Sequence[Call], name: str) -> Call:
    return next(call for call in calls if call.name == name)


def _assert_status(response: Response, expected: int, context: str) -> None:
    assert response.status_code == expected, (
        context,
        f"expected {expected}, got {response.status_code}",
        str(response.request.url),
        response.text,
    )


# --- the tests ----------------------------------------------------------------


def test_every_project_route_is_absent_outside_its_workspace(
    tmp_path: Path,
) -> None:
    with stage_for(tmp_path, "tenancy.sqlite3") as stage:
        for call in FOREIGN:
            # Each request is its own browser session, so `as_` runs inside `send`.
            _assert_status(call.send(stage), 404, call.name)


def test_workspace_listings_never_carry_another_workspaces_projects(
    tmp_path: Path,
) -> None:
    with stage_for(tmp_path, "listings.sqlite3") as stage:
        in_b = stage.projects(stage.b).list_ok(headers=stage.as_("both"))
        in_a = stage.projects(stage.a).list_ok(headers=stage.as_("both"))

        assert [item.id for item in in_b.projects] == [stage.project_b]
        assert [item.id for item in in_a.projects] == [stage.project_a]
        assert [
            folder.id
            for folder in stage.folders(stage.b)
            .list_ok(headers=stage.as_("both"))
            .folders
        ] == [stage.folder_b]


def test_project_browser_lists_only_the_workspaces_the_caller_can_see(
    tmp_path: Path,
) -> None:
    with stage_for(tmp_path, "browser.sqlite3") as stage:
        owner_a_rows = stage.api.project_browser.list_ok(headers=stage.as_("owner_a"))
        owner_b_rows = stage.api.project_browser.list_ok(headers=stage.as_("owner_b"))
        both_rows = stage.api.project_browser.list_ok(headers=stage.as_("both"))
        assert [row.id for row in owner_a_rows.projects] == [stage.project_a]
        assert [row.id for row in owner_b_rows.projects] == [stage.project_b]
        assert {row.id for row in both_rows.projects} == {
            stage.project_a,
            stage.project_b,
        }
        assert {row.location.id for row in both_rows.projects} == {stage.a, stage.b}

        stage.api.raw.cookies.clear()
        anonymous = stage.api.raw.get("/v1/me/projects")
        assert anonymous.status_code == 401, anonymous.text


@pytest.mark.parametrize("name", _names(VIEWER_DENIED))
def test_viewer_is_forbidden_from_every_mutating_project_route(
    tmp_path: Path, name: str
) -> None:
    with stage_for(tmp_path, f"viewer-{name}.sqlite3") as stage:
        _assert_status(_find(VIEWER_DENIED, name).send(stage), 403, name)
        # The Project is untouched on the way out, not just refused on the way in.
        assert stage.projects(stage.a).get_ok(stage.project_a).name == "Project in A"


@pytest.mark.parametrize("name", _names(EDITOR_DENIED))
def test_editor_cannot_delete_a_project_or_hold_a_secret(
    tmp_path: Path, name: str
) -> None:
    with stage_for(tmp_path, f"editor-{name}.sqlite3") as stage:
        _assert_status(_find(EDITOR_DENIED, name).send(stage), 403, name)
        assert stage.projects(stage.a).get_ok(stage.project_a).name == "Project in A"


@pytest.mark.parametrize("name", _names(PAT_DENIED))
def test_a_token_without_project_scopes_is_forbidden_from_every_read(
    tmp_path: Path, name: str
) -> None:
    with stage_for(tmp_path, f"pat-{name}.sqlite3") as stage:
        _assert_status(_find(PAT_DENIED, name).send(stage), 403, name)


def test_a_token_reads_what_its_scopes_allow(tmp_path: Path) -> None:
    """The refusal above is about scope, not about tokens: the same route answers."""

    with stage_for(tmp_path, "pat-allowed.sqlite3") as stage:
        created = stage.api.workspace(stage.a).create_token_ok(
            PersonalAccessTokenCreateRequest(
                label="project-reader",
                scopes=(PersonalAccessTokenScope.VIEW_PROJECT,),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            headers=stage.as_("owner_a"),
        )
        stage.api.raw.cookies.clear()
        headers = {"Authorization": f"Bearer {created.token.get_secret_value()}"}

        listed = stage.projects(stage.a).list_ok(headers=headers)
        forbidden = stage.folders(stage.a).create(
            ProjectFolderWriteRequest(name="No"), headers=headers
        )

        assert [item.id for item in listed.projects] == [stage.project_a]
        assert forbidden.status_code == 403, forbidden.text


# --- scope, not role: what a token may do with a checkpoint ---------------------
#
# A restore is an edit that also lands as a checkpoint, and creating a Project
# checkpoints it on the way in. The service has always asked for `checkpoint_project` on
# both, but below the routes a token's scope is invisible and only the role is left to
# check against, so any token of an editor could do either however it was scoped.


def test_a_token_that_may_edit_but_not_checkpoint_cannot_restore(
    tmp_path: Path,
) -> None:
    with stage_for(tmp_path, "pat-restore.sqlite3") as stage:
        projects = stage.projects(stage.a)
        owner = stage.as_("owner_a")
        head = projects.get_head_ok(stage.project_a, headers=owner)
        projects.submit_commands_ok(
            stage.project_a,
            _rename_request(head, "Renamed", "Project in A"),
            headers=owner,
        )
        durable = projects.checkpoint_ok(
            stage.project_a,
            _where_the_head_is(projects.get_head_ok(stage.project_a, headers=owner)),
            headers=owner,
        )
        assert durable.checkpoint_revision == 2

        headers = stage.scoped_token(
            "editor-only",
            PersonalAccessTokenScope.VIEW_PROJECT,
            PersonalAccessTokenScope.EDIT_PROJECT,
        )
        before = projects.get_head_ok(stage.project_a, headers=headers)
        assert (
            projects.checkpoint(
                stage.project_a, _where_the_head_is(before), headers=headers
            ).status_code
            == 403
        ), (
            "the checkpoint route must refuse this token first, or the pair proves nothing"
        )

        refused = projects.restore_checkpoint(
            stage.project_a, 1, _where_the_head_is(before), headers=headers
        )

        _assert_status(refused, 403, "restore with an edit-only token")
        assert refused.json()["code"] == "identity.capability_denied"

        # The refusal is the whole outcome, not a step into a write: no half-applied
        # restore, no reopened room, no revision nobody asked for.
        after = projects.get_head_ok(stage.project_a, headers=headers)
        assert after == before
        assert after.name == "Renamed"
        assert after.room_epoch == before.room_epoch
        assert after.collaboration_sequence == before.collaboration_sequence
        assert after.checkpoint_revision == 2
        assert [
            item.revision
            for item in projects.list_checkpoints_ok(
                stage.project_a, headers=headers
            ).checkpoints
        ] == [1, 2]


def test_a_token_that_may_create_but_not_checkpoint_cannot_create(
    tmp_path: Path,
) -> None:
    """Opening a Project writes its first checkpoint, so it needs the scope for it."""

    with stage_for(tmp_path, "pat-create.sqlite3") as stage:
        headers = stage.scoped_token(
            "creator-only", PersonalAccessTokenScope.CREATE_PROJECT
        )

        refused = stage.projects(stage.a).create(
            CreateProjectRequest(name="Half a project"), headers=headers
        )

        _assert_status(refused, 403, "create with a create-only token")
        assert refused.json()["code"] == "identity.capability_denied"
        # Refused before opening anything, so the refusal leaves no Project to undo.
        assert [
            item.id
            for item in stage.projects(stage.a)
            .list_ok(headers=stage.as_("owner_a"))
            .projects
        ] == [stage.project_a]


def test_a_token_that_may_create_but_not_checkpoint_cannot_copy(
    tmp_path: Path,
) -> None:
    """A copy is an opening: it stages the copied document with its checkpoint 1."""

    with stage_for(tmp_path, "pat-copy.sqlite3") as stage:
        source = stage.projects(stage.a).get_head_ok(
            stage.project_a, headers=stage.as_("owner_a")
        )
        headers = stage.scoped_token(
            "creator-only",
            PersonalAccessTokenScope.VIEW_PROJECT,
            PersonalAccessTokenScope.CREATE_PROJECT,
        )

        refused = stage.projects(stage.a).copy(
            CopyExactHeadRequest(
                source_workspace_id=stage.a,
                source_project_id=stage.project_a,
                project_id=uuid4(),
                command_id=uuid4(),
                expected_room_epoch=source.room_epoch,
                expected_sequence=source.collaboration_sequence,
            ),
            headers=headers,
        )

        _assert_status(refused, 403, "copy with a create-only token")
        assert refused.json()["code"] == "identity.capability_denied"
        # Refused before staging anything, so no second Project was opened to undo.
        assert [
            item.id
            for item in stage.projects(stage.a).list_ok(headers=headers).projects
        ] == [stage.project_a]


def test_copy_rejects_a_token_without_view_scope(tmp_path: Path) -> None:
    with stage_for(tmp_path, "pat-copy-no-view.sqlite3") as stage:
        source = stage.projects(stage.a).get_head_ok(
            stage.project_a, headers=stage.as_("owner_a")
        )
        headers = stage.scoped_token(
            "create-checkpoint-no-view",
            PersonalAccessTokenScope.CREATE_PROJECT,
            PersonalAccessTokenScope.CHECKPOINT_PROJECT,
        )
        refused = stage.projects(stage.a).copy(
            CopyExactHeadRequest(
                source_workspace_id=stage.a,
                source_project_id=stage.project_a,
                project_id=uuid4(),
                command_id=uuid4(),
                expected_room_epoch=source.room_epoch,
                expected_sequence=source.collaboration_sequence,
            ),
            headers=headers,
        )
        _assert_status(refused, 403, "copy without view scope")
        assert refused.json()["code"] == "identity.capability_denied"
        assert [
            item.id
            for item in stage.projects(stage.a)
            .list_ok(headers=stage.as_("owner_a"))
            .projects
        ] == [stage.project_a]


def test_a_token_scoped_for_checkpointing_is_served_the_routes_that_need_it(
    tmp_path: Path,
) -> None:
    """The refusals above are about scope, not about tokens: the routes do answer."""

    with stage_for(tmp_path, "pat-checkpoint.sqlite3") as stage:
        projects = stage.projects(stage.a)
        owner = stage.as_("owner_a")
        head = projects.get_head_ok(stage.project_a, headers=owner)
        projects.submit_commands_ok(
            stage.project_a,
            _rename_request(head, "Renamed", "Project in A"),
            headers=owner,
        )
        projects.checkpoint_ok(
            stage.project_a,
            _where_the_head_is(projects.get_head_ok(stage.project_a, headers=owner)),
            headers=owner,
        )

        headers = stage.scoped_token(
            "checkpoint-scope",
            PersonalAccessTokenScope.VIEW_PROJECT,
            PersonalAccessTokenScope.CREATE_PROJECT,
            PersonalAccessTokenScope.EDIT_PROJECT,
            PersonalAccessTokenScope.CHECKPOINT_PROJECT,
        )
        restored = projects.restore_checkpoint_ok(
            stage.project_a,
            1,
            _where_the_head_is(projects.get_head_ok(stage.project_a, headers=headers)),
            headers=headers,
        )

        assert restored.checkpoint_revision == 3
        assert restored.head.name == "Project in A"
        created = projects.create_ok(
            CreateProjectRequest(name="Checkpointed at birth"), headers=headers
        )
        assert created.name == "Checkpointed at birth"
        copied = projects.copy_ok(
            CopyExactHeadRequest(
                source_workspace_id=stage.a,
                source_project_id=stage.project_a,
                project_id=uuid4(),
                command_id=uuid4(),
                name="Opened by a copy",
                expected_room_epoch=restored.head.room_epoch,
                expected_sequence=restored.head.collaboration_sequence,
            ),
            headers=headers,
        )
        assert copied.name == "Opened by a copy"
        assert {item.name for item in projects.list_ok(headers=headers).projects} == {
            "Project in A",
            "Checkpointed at birth",
            "Opened by a copy",
        }
