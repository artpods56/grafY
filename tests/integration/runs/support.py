"""One harness for the Run route and Project room tests (ADR 0020).

Both suites need the same three things the composition cannot hand them:

* **A Project opened without HTTP.** The Project routes belong to another change, so
  Projects are opened through :class:`CollaborationService` over its own database
  handle, the way the identity seed already does.
* **A computation that moves only when the test says so.** The Run service installed
  here is the production ``RunService`` with the production document source, result
  store, fingerprint facts and room fan-out, and one substituted seam: the
  computation runner. ``concurrency`` is a harness argument because a test that wants
  two Runs running at once cannot share the deployment's budget.
* **Two actors in one room.** ``ActorSwitcher`` is the single browser-actor override,
  so "as the editor" is one call, and the raw ``TestClient`` is exposed because only
  it can open a WebSocket.

``TestClient`` runs the app on its own event loop in another thread, and the hub
hands every Run and instance publish to that loop, so the gates here are
``threading.Event`` objects awaited through ``asyncio.to_thread`` — never an
``asyncio.Event`` built in the test loop and set from the app loop.

Documents name ``value.integer``, a builtin this build really registers: fingerprints
are computed by the real facts factory, so an unknown operator would be rejected here
exactly as it is in production. Nothing here executes a node — the runner answers
instead, and what it answers is addressed by the fingerprint it was asked for.
"""

import asyncio
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.testclient import WebSocketTestSession

from grafy_api.app_state import AppResources, get_identity, get_resources
from grafy_api.realtime.run_events import ProjectRunEvents
from grafy_api.runs.facts import ApplicationFactsFactory
from grafy_api.runs.persistence import (
    PersistentResultStore,
    RepositoryProjectDocuments,
)
from grafy_api.runs.service import RunService
from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.collaboration.views import websocket_browser_actor
from grafy_core.application.collaboration import CollaborationService
from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.collaboration import AddGraphCommand, ProjectCommand
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
from grafy_core.kernel.implementation_identity import RegistryImplementationDigests
from grafy_core.kernel.scheduler import ComputationRequest
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.support.factories.identity import IdentitySeeder
from tests.support.identity import ActorSwitcher
from tests.testkit import client_with_overrides, create_db_url, db, with_setting_values

REPO_ROOT = Path(__file__).resolve().parents[3]
UV_LOCK = REPO_ROOT / "uv.lock"

MAIN_GRAPH_ID = "main"
FLOW_GRAPH_ID = "flow"
OPERATOR_ID = "value.integer"
OPERATOR_VERSION = 1


class GatedRunner:
    """A computation that begins when scheduled and ends when the test allows it.

    Gated by node id, the name a test has: one gate holds exactly the one computation
    the scheduler runs for that node, however many Runs demand it.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.released: list[str] = []
        self.cancelled: list[str] = []
        self._started: dict[str, threading.Event] = {}
        self._release: dict[str, threading.Event] = {}

    def started(self, node_id: str) -> threading.Event:
        return self._started.setdefault(node_id, threading.Event())

    def _release_gate(self, node_id: str) -> threading.Event:
        return self._release.setdefault(node_id, threading.Event())

    def release(self, *node_ids: str) -> None:
        for node_id in node_ids:
            self._release_gate(node_id).set()

    def release_everything(self) -> None:
        """Open every gate, so no worker thread outlives the test that held it."""

        for gate in self._release.values():
            gate.set()

    async def run(
        self,
        request: ComputationRequest,
    ) -> Mapping[str, ArtifactOutputValue]:
        node_id = request.instance.key.node_id
        self.calls.append(node_id)
        self.started(node_id).set()
        try:
            await asyncio.to_thread(self._release_gate(node_id).wait)
        except asyncio.CancelledError:
            self.cancelled.append(node_id)
            raise
        self.released.append(node_id)
        return {
            "result": ArtifactRef(
                artifact_id=UUID(int=0xD01),
                artifact_type="scalar.integer",
                schema_version=1,
                content_hash=request.fingerprint,
            )
        }


class GatedRunnerFactory:
    def __init__(self, runner: GatedRunner) -> None:
        self.runner = runner

    def for_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        store: object,
    ):
        del workspace_id, project_id, store
        return self.runner.run


def integer_node(node_id: str, *, value: int = 1) -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id=OPERATOR_ID,
        operator_version=OPERATOR_VERSION,
        config={"value": value},
        position=GraphPoint(x=0.0, y=0.0),
    )


def flow_document(node_ids: Sequence[str] = ("first", "second")) -> GraphDocument:
    """One Graph with an independent node per name: each is its own computation.

    The values differ per node on purpose. Two nodes of one operator with one config
    and no inputs share a fingerprint, and two instances that share a fingerprint are
    one computation, which would make a test about two computations say something
    else entirely.
    """

    return GraphDocument(
        nodes=tuple(
            integer_node(node_id, value=index + 1)
            for index, node_id in enumerate(node_ids)
        ),
    )


@dataclass(frozen=True, slots=True)
class RoomCast:
    """The seeded room cast: two Workspaces the owner belongs to, and its members."""

    workspace: Workspace
    other_workspace: Workspace
    owner: User
    editor: User
    viewer: User
    stranger: User


async def _seed_cast(database_url: str) -> RoomCast:
    async with db(database_url) as database:
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        owner = await seeder.user(email="owner@example.test", display_name="Owner")
        editor = await seeder.user(email="editor@example.test", display_name="Editor")
        viewer = await seeder.user(email="viewer@example.test", display_name="Viewer")
        stranger = await seeder.user(
            email="stranger@example.test", display_name="Stranger"
        )
        workspace = await seeder.workspace(slug="team", name="Team")
        other = await seeder.workspace(slug="other", name="Other")
        for user, role in (
            (owner, WorkspaceRole.OWNER),
            (editor, WorkspaceRole.EDITOR),
            (viewer, WorkspaceRole.VIEWER),
        ):
            await seeder.membership(user=user, workspace=workspace, role=role)
        # The stranger belongs to the other Workspace only, which is where the
        # tenancy tests read a foreign Project from: a member of neither would be a
        # 404 about the Workspace, not about the Project.
        await seeder.membership(user=owner, workspace=other, role=WorkspaceRole.OWNER)
        return RoomCast(
            workspace=workspace,
            other_workspace=other,
            owner=owner,
            editor=editor,
            viewer=viewer,
            stranger=stranger,
        )


async def _open_project(
    database_url: str,
    *,
    settings: Settings,
    actor_id: UUID,
    workspace_id: UUID,
    name: str,
    graphs: Mapping[str, GraphDocument],
) -> UUID:
    """Open a Project and its Graphs through the service layer, over its own handle."""

    async with db(database_url) as database:
        service = CollaborationService(
            lambda: SqlAlchemyUnitOfWork(database.sessions),
            command_hmac_key=settings.keys.resolved_command_hmac_key(),
            command_hmac_key_version=settings.keys.command_hmac_key_version,
        )
        actor = ActorContext(user_id=actor_id, credential_reference="test-seed")
        creation = await service.create_project(
            actor=actor,
            workspace_id=workspace_id,
            name=name,
        )
        if graphs:
            await service.submit_commands(
                actor=actor,
                workspace_id=workspace_id,
                project_id=creation.project.id,
                command_id=uuid4(),
                observed_sequence=creation.head.collaboration_sequence,
                observed_room_epoch=creation.head.room_epoch,
                commands=tuple(
                    AddGraphCommand(
                        graph_id=graph_id,
                        name=f"Graph {graph_id}",
                        document=document,
                    )
                    for graph_id, document in graphs.items()
                ),
            )
        return creation.project.id


@dataclass
class RoomHarness:
    """A live app, its gated Run service, and the way to talk to both."""

    client: TestClient
    switcher: ActorSwitcher
    cast: RoomCast
    runner: GatedRunner
    projects: dict[str, UUID]

    @property
    def app(self) -> FastAPI:
        return self.client.app  # type: ignore[no-any-return]

    @property
    def resources(self) -> AppResources:
        return get_resources(self.app)

    @property
    def workspace_id(self) -> UUID:
        return self.cast.workspace.id

    @property
    def project_id(self) -> UUID:
        """The Project of this Workspace that the room tests open."""

        return self.projects["room"]

    @property
    def foreign_workspace_id(self) -> UUID:
        """A Workspace the actor also belongs to, which holds no Project of ours."""

        return self.cast.other_workspace.id

    @property
    def foreign_project_id(self) -> UUID:
        """A Project of that other Workspace, named here to be asked for there."""

        return self.projects["elsewhere"]

    def as_user(self, user: User) -> None:
        self.switcher.as_user(user.id)

    def path(self, suffix: str, *, workspace_id: UUID | None = None) -> str:
        normalized = suffix if suffix.startswith("/") else f"/{suffix}"
        workspace = self.workspace_id if workspace_id is None else workspace_id
        return f"/v1/workspaces/{workspace}{normalized}"

    def get(self, suffix: str, **kwargs: Any) -> Any:
        return self.client.get(self.path(suffix), **kwargs)

    def post(self, suffix: str, **kwargs: Any) -> Any:
        return self.client.post(self.path(suffix), **kwargs)

    def connect_room(
        self,
        project_id: UUID,
        *,
        workspace_id: UUID | None = None,
        origin: str = "http://testserver",
    ):
        """Open the Project room as whoever the switcher is set to."""

        workspace = self.workspace_id if workspace_id is None else workspace_id
        return self.client.websocket_connect(
            f"/v1/workspaces/{workspace}/projects/{project_id}/room",
            headers={"Origin": origin},
        )

    def issue_token(self, scopes: Sequence[str]) -> str:
        """A Workspace PAT with exactly these scopes, as a bearer header value."""

        response = self.client.post(
            f"/v1/workspaces/{self.workspace_id}/personal-access-tokens",
            json={
                "label": "run-route-scope",
                "scopes": list(scopes),
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == 201, response.text
        return str(response.json()["token"])

    def bearer(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


def receive_until(
    websocket: WebSocketTestSession, message_type: str, /, *, limit: int = 40
) -> dict[str, Any]:
    """The next message of this type, failing the test when none arrives."""

    for _ in range(limit):
        message = websocket.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"did not receive {message_type!r} within {limit} messages")


def receive_next(
    websocket: WebSocketTestSession, expected_type: str, /
) -> dict[str, Any]:
    """The very next message, asserting its type.

    A room that sends anything else first is out of order, and an out-of-order room
    is the bug these tests exist for, so this never skips to what it wanted.
    """

    message = websocket.receive_json()
    assert message["type"] == expected_type, message
    return message


def command_batch(
    head: dict[str, Any],
    commands: Sequence[ProjectCommand],
    *,
    command_id: UUID | None = None,
) -> dict[str, Any]:
    """A ``project.command.submit`` observed against the head a participant holds.

    ``head`` is either a ``room.ready`` message or its ``head`` member, so a test can
    submit its second batch from the sequence the first one was accepted at.
    """

    observed = head["head"] if "head" in head else head
    return {
        "protocol_version": 1,
        "type": "project.command.submit",
        "command_id": str(command_id or uuid4()),
        "room_epoch": observed["room_epoch"],
        "observed_sequence": observed["collaboration_sequence"],
        "commands": [command.model_dump(mode="json") for command in commands],
    }


def accepted_head(accepted: dict[str, Any]) -> dict[str, Any]:
    """The head a participant holds after one accepted batch, for its next batch."""

    return {
        "room_epoch": accepted["room_epoch"],
        "collaboration_sequence": accepted["sequence"],
    }


def install_gated_run_service(
    app: FastAPI,
    *,
    concurrency: int,
) -> GatedRunner:
    """Replace the composed Run service with one whose computations are gated.

    Every other seam stays production: the same database, the same hub, the same
    fingerprint facts, so a Run started over HTTP is announced to the room by the
    same code a deployment runs.
    """

    resources = get_resources(app)
    identity = get_identity(app)
    uow_factory = identity.identity_uow_factory
    runner = GatedRunner()
    registry = resources.workbench.plugin_registry
    resources.runs = RunService(
        documents=RepositoryProjectDocuments(uow_factory=uow_factory),
        uow_factory=uow_factory,
        result_store_factory=lambda workspace_id: PersistentResultStore(
            workspace_id=workspace_id, uow_factory=uow_factory
        ),
        facts=ApplicationFactsFactory(
            registry=registry,
            digests=RegistryImplementationDigests.from_registry(
                registry, uv_lock=UV_LOCK
            ),
            secrets=resources.node_secrets,
        ),
        runners=GatedRunnerFactory(runner),
        events=ProjectRunEvents(
            hub=resources.project_room_hub,
            uow_factory=_collaboration_uow_factory(app),
        ),
        concurrency=concurrency,
    )
    return runner


def _collaboration_uow_factory(app: FastAPI):
    """The identity unit of work, which also carries the collaboration repositories."""

    return get_identity(app).identity_uow_factory


def _actor_or_token(switcher: ActorSwitcher):
    """A ``workspace_actor`` replacement that keeps the Personal Access Token path.

    The browser half stays the switcher override every suite here already uses, so no
    test has to log in. The bearer half stays production: a token is verified by the
    real auth service and carries its own scopes, which is the only way to ask a route
    what it does when the credential is narrower than the role — permission is
    role ∩ PAT scope ∩ capability, and an override of the whole seam would hide the
    middle term.
    """

    async def resolve(request: Request, workspace_id: UUID):
        authorization = request.headers.get("authorization")
        if authorization is None:
            return switcher.actor()
        principal = await get_identity(
            request.app
        ).auth_service.require_workspace_pat_principal(
            request,
            authorization,
        )
        if principal.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found",
            )
        return principal

    return resolve


@contextmanager
def room_harness(
    tmp_path: Path,
    settings: Settings,
    *,
    heartbeat_seconds: float = 0.0,
    concurrency: int = 4,
    graphs: Mapping[str, GraphDocument] | None = None,
) -> Iterator[RoomHarness]:
    """A booted app with two seeded Projects and a gated Run service.

    One Project lives in the Workspace the tests act in, one in a second Workspace the
    same actor belongs to: the difference between them is the only way to ask a route
    for a Project its Workspace does not own.
    """

    database_url = create_db_url(tmp_path, "room.sqlite3")
    cast = asyncio.run(_seed_cast(database_url))
    document = flow_document() if graphs is None else graphs
    project_id = asyncio.run(
        _open_project(
            database_url,
            settings=settings,
            actor_id=cast.owner.id,
            workspace_id=cast.workspace.id,
            name="Room project",
            graphs={FLOW_GRAPH_ID: document},
        )
    )
    foreign_project_id = asyncio.run(
        _open_project(
            database_url,
            settings=settings,
            actor_id=cast.owner.id,
            workspace_id=cast.other_workspace.id,
            name="Elsewhere",
            graphs={FLOW_GRAPH_ID: document},
        )
    )
    switcher = ActorSwitcher(cast.owner.id)
    with client_with_overrides(
        settings=with_setting_values(
            settings,
            database_url=SecretStr(database_url),
            workspace=tmp_path / "workbench",
            graph_room_heartbeat_seconds=heartbeat_seconds,
        ),
        overrides={
            browser_actor: switcher.actor,
            workspace_actor: _actor_or_token(switcher),
            websocket_browser_actor: switcher.actor,
        },
    ) as client:
        runner = install_gated_run_service(client.app, concurrency=concurrency)  # type: ignore[arg-type]
        harness = RoomHarness(
            client=client,
            switcher=switcher,
            cast=cast,
            runner=runner,
            projects={"room": project_id, "elsewhere": foreign_project_id},
        )
        try:
            yield harness
        finally:
            # A gate left shut keeps its worker thread waiting, and the portal loop
            # this app runs on cannot stop until its threads have.
            runner.release_everything()


__all__ = [
    "FLOW_GRAPH_ID",
    "MAIN_GRAPH_ID",
    "OPERATOR_ID",
    "RoomCast",
    "RoomHarness",
    "accepted_head",
    "command_batch",
    "flow_document",
    "integer_node",
    "receive_next",
    "receive_until",
    "room_harness",
]
