"""The Agent HTTP surface: tenancy, capability, idempotence and the write-only key (#202).

Every rule this suite checks is a rule a caller could otherwise break by accident:

* **The whole path is the scope.** A conversation found inside the caller's Workspace is not
  yet the conversation this URL is about: one Workspace holds many Projects, one Project many
  Graphs and one Graph many Agents. Each of those three mismatches is answered 404, the same
  answer a conversation of another Workspace gets, so nothing here confirms where a thread the
  caller guessed really lives.
* **The capability is checked before the conversation is touched**, and the route declares the
  one the service re-checks — `view_project` to read a thread, `start_run` to open, fork, send
  and cancel, `edit_project` for an Agent's model and key. Real sessions and real Personal
  Access Tokens drive this, with no identity override on the workspace seam: a scope is only
  proven against a caller that carries one.
* **A send is admitted once.** Same client turn id and same text returns the same turn with one
  user message and one model call; different text under one id is a conflict; a second question
  to a busy conversation names the turn it would have run behind. Cancel answers the same way
  however often it is asked.
* **The key never comes back.** Set it, read the configuration, clear it: the submitted value
  appears in no response, and no failure account repeats it.

The model is a scripted pydantic-ai `FunctionModel` behind the composition's own
`turn_model_factory` seam, so a turn streams, parks and finishes on the test's say-so and no
request leaves the process. `TestClient` runs the app on its own loop in another thread, so the
gates are `threading.Event` objects awaited through `asyncio.to_thread`, and every wait in this
file is on an event or a room frame — never on a clock.
"""

import asyncio
import base64
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from starlette.testclient import WebSocketTestSession

from grafy_api.app_state import get_resources
from grafy_api.realtime.agent_events import ProjectAgentEvents
from grafy_api.agents.turns import AgentService, AgentTurnModel
from grafy_api.settings import Settings
from grafy_api.v1.routes.agents.dependencies import agent_turn_service
from grafy_api.auth import AuthService, IssuedSession
from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreateRequest,
    PersonalAccessTokenScope,
)
from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.identity import IdentityService
from grafy_core.application.project_creation import MAIN_GRAPH_ID
from grafy_core.domain.collaboration import (
    AddAgentCommand,
    AddGraphCommand,
    InGraphCommand,
    ProjectCommand,
)
from grafy_core.domain.graph_documents import (
    CustomAgentModel,
    DeploymentAgentModel,
    GraphAgent,
    GraphDocument,
)
from grafy_core.domain.identity import ActorContext, User, WorkspaceRole
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig

from tests.integration.runs.support import Room
from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.testkit import client_with_overrides, create_db_url, db, with_setting_values

MAIN = MAIN_GRAPH_ID
NOTES = "notes"
RESEARCH = "research"
SCRIBE = "scribe"
ORIGIN = "http://testserver"
DEPLOYMENT_KEY = "deployment-key-0123456789abcdef"
AGENT_KEY = "agent-owned-key-0123456789abcdef"
CUSTOM_ENDPOINT = "https://models.example/v1"
WAIT_SECONDS = 20.0


class Script:
    """One turn's stream, driven from the test thread.

    `park_after` is how many chunks may go out before the stream waits on an event only the
    test can open — the honest way to put a turn in the state "running, half answered" that a
    busy refusal, a Stop and an in-flight read are all about. `finished` says the script ran
    out, which is what a test waits for before it reads the stored answer.
    """

    def __init__(self, chunks: Sequence[str], *, park_after: int | None = None) -> None:
        self.chunks = tuple(chunks)
        self.park_after = park_after
        self.calls = 0
        self.started = threading.Event()
        self.parked = threading.Event()
        self.finished = threading.Event()
        # Set on the way out of the turn, which the runtime does only after it has written the
        # turn's ending: a test that reads the conversation once this is set is reading the
        # committed answer rather than racing the task that writes it.
        self.handed_back = threading.Event()
        self.messages: list[list[ModelMessage]] = []
        self._release = threading.Event()

    def release(self) -> None:
        self._release.set()

    async def aclose(self) -> None:
        self.handed_back.set()

    def model(self) -> FunctionModel:
        async def stream(messages: list[ModelMessage], _info: AgentInfo) -> Any:
            self.calls += 1
            self.messages.append(list(messages))
            self.started.set()
            for index, chunk in enumerate(self.chunks):
                if self.park_after is not None and index >= self.park_after:
                    self.parked.set()
                    await asyncio.to_thread(self._release.wait)
                yield chunk
            self.finished.set()

        return FunctionModel(stream_function=stream)


class ScriptedTurns:
    """The composition seam: a turn dials a script instead of an endpoint."""

    def __init__(self) -> None:
        self.scripts: list[Script] = []
        self._next = 0

    def add(self, script: Script) -> Script:
        self.scripts.append(script)
        return script

    def take(self) -> Script:
        script = self.scripts[min(self._next, len(self.scripts) - 1)]
        self._next += 1
        return script

    def turn_model(self, _resolved: object) -> AgentTurnModel:
        """No credential, no transport: a script owns nothing but the test's attention."""

        script = self.take()
        return AgentTurnModel(chat_model=script.model(), close=script.aclose)

    def release_all(self) -> None:
        for script in self.scripts:
            script.release()


@dataclass
class Stage:
    """The live app, two Projects in one Workspace, one in another, and its callers."""

    client: TestClient
    api: GrafyApi
    settings: Settings
    workspace: UUID
    other_workspace: UUID
    project: UUID
    other_project: UUID
    foreign_project: UUID
    sessions: dict[str, IssuedSession]
    scripted: ScriptedTurns
    services: list[AgentService] = field(default_factory=list)
    open_rooms: list[WebSocketTestSession] = field(default_factory=list)

    @property
    def app(self) -> FastAPI:
        return cast(FastAPI, self.client.app)

    def path(self, suffix: str, *, project: UUID | None = None) -> str:
        return (
            f"/v1/workspaces/{self.workspace}/projects/"
            f"{project or self.project}{suffix}"
        )

    def scoped(self, agent_id: str = RESEARCH, graph_id: str = MAIN) -> str:
        return f"/graphs/{graph_id}/agents/{agent_id}"

    def as_(self, who: str) -> dict[str, str]:
        """Become one browser caller for the next request."""

        self.client.cookies.clear()
        issued = self.sessions[who]
        self.api.authenticate(issued)
        return {"Origin": ORIGIN, "X-CSRF-Token": issued.csrf_value}

    def token(
        self, label: str, *scopes: PersonalAccessTokenScope, who: str = "owner"
    ) -> dict[str, str]:
        """Mint a Workspace token with exactly these scopes and present nothing else.

        Minted by a member of this Workspace, so every token differs from the next only in
        scope: a refusal can then only be about the scope.
        """

        issued = self.api.workspace(self.workspace).create_token_ok(
            PersonalAccessTokenCreateRequest(
                label=label,
                scopes=scopes,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            headers=self.as_(who),
        )
        self.client.cookies.clear()
        return {"Authorization": f"Bearer {issued.token.get_secret_value()}"}

    # --- the surface, one method per route ------------------------------------

    def start(
        self,
        *,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
        project: UUID | None = None,
        title: str = "",
    ) -> Response:
        return self.client.post(
            self.path(self.scoped(agent, graph) + "/conversations", project=project),
            json={"title": title},
            headers=headers or self.as_("editor"),
        )

    def conversations(
        self,
        *,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
        project: UUID | None = None,
    ) -> Response:
        return self.client.get(
            self.path(self.scoped(agent, graph) + "/conversations", project=project),
            headers=headers or self.as_("editor"),
        )

    def conversation(
        self,
        conversation_id: UUID,
        *,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
        project: UUID | None = None,
    ) -> Response:
        return self.client.get(
            self.path(
                self.scoped(agent, graph) + f"/conversations/{conversation_id}",
                project=project,
            ),
            headers=headers or self.as_("editor"),
        )

    def events(
        self,
        conversation_id: UUID,
        *,
        query: str = "",
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
        project: UUID | None = None,
    ) -> Response:
        return self.client.get(
            self.path(
                self.scoped(agent, graph)
                + f"/conversations/{conversation_id}/events{query}",
                project=project,
            ),
            headers=headers or self.as_("editor"),
        )

    def fork(
        self,
        conversation_id: UUID,
        *,
        at_sequence: int,
        headers: dict[str, str] | None = None,
        title: str | None = None,
    ) -> Response:
        body: dict[str, Any] = {"at_sequence": at_sequence}
        if title is not None:
            body["title"] = title
        return self.client.post(
            self.path(self.scoped() + f"/conversations/{conversation_id}/fork"),
            json=body,
            headers=headers or self.as_("editor"),
        )

    def send(
        self,
        conversation_id: UUID,
        *,
        text: str,
        turn_id: str,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
        project: UUID | None = None,
    ) -> Response:
        return self.client.post(
            self.path(
                self.scoped(agent, graph) + f"/conversations/{conversation_id}/turns",
                project=project,
            ),
            json={"client_turn_id": turn_id, "text": text},
            headers=headers or self.as_("editor"),
        )

    def cancel(
        self,
        conversation_id: UUID,
        *,
        turn_id: str | None = None,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
        project: UUID | None = None,
    ) -> Response:
        return self.client.post(
            self.path(
                self.scoped(agent, graph) + f"/conversations/{conversation_id}/cancel",
                project=project,
            ),
            json={} if turn_id is None else {"turn_id": turn_id},
            headers=headers or self.as_("editor"),
        )

    def active(
        self,
        conversation_id: UUID,
        *,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
    ) -> Response:
        return self.client.get(
            self.path(
                self.scoped(agent, graph)
                + f"/conversations/{conversation_id}/active-turn"
            ),
            headers=headers or self.as_("editor"),
        )

    def model(
        self,
        *,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
    ) -> Response:
        return self.client.get(
            self.path(self.scoped(agent, graph) + "/model"),
            headers=headers or self.as_("editor"),
        )

    def put_key(
        self,
        value: str,
        *,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
    ) -> Response:
        return self.client.put(
            self.path(self.scoped(agent, graph) + "/key"),
            json={"value": value},
            headers=headers or self.as_("editor"),
        )

    def delete_key(
        self,
        *,
        headers: dict[str, str] | None = None,
        agent: str = RESEARCH,
        graph: str = MAIN,
    ) -> Response:
        return self.client.delete(
            self.path(self.scoped(agent, graph) + "/key"),
            headers=headers or self.as_("editor"),
        )

    def room(self, who: str = "editor", *, project: UUID | None = None) -> Room:
        """One participant of this Project's room, frames read on a bounded queue."""

        self.as_(who)
        session = self.client.websocket_connect(
            f"/v1/workspaces/{self.workspace}/projects/{project or self.project}/room",
            headers={"Origin": ORIGIN},
        )
        # The handshake is only half a room: `__enter__` is what starts the session's task on
        # the app loop, and a session that never entered has no portal to send or receive on.
        session.__enter__()
        self.open_rooms.append(session)
        room = Room(session)
        room.expect("room.ready")
        return room


@dataclass(frozen=True)
class Cast:
    owner: User
    editor: User
    viewer: User
    workspace: UUID
    other_workspace: UUID


async def _seed(database_url: str) -> Cast:
    async with db(database_url) as database:
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        owner = await seeder.user(email="owner@example.test", display_name="Owner")
        editor = await seeder.user(email="editor@example.test", display_name="Editor")
        viewer = await seeder.user(email="viewer@example.test", display_name="Viewer")
        workspace = await seeder.workspace(slug="team", name="Team")
        other = await seeder.workspace(slug="other", name="Other")
        for user, role in (
            (owner, WorkspaceRole.OWNER),
            (editor, WorkspaceRole.EDITOR),
            (viewer, WorkspaceRole.VIEWER),
        ):
            await seeder.membership(user=user, workspace=workspace, role=role)
        await seeder.membership(user=owner, workspace=other, role=WorkspaceRole.OWNER)
        return Cast(
            owner=owner,
            editor=editor,
            viewer=viewer,
            workspace=workspace.id,
            other_workspace=other.id,
        )


def _agent(agent_id: str, *, custom: bool = False) -> GraphAgent:
    """One Agent as the canvas would carry it.

    A custom-model Agent is included because that is the configuration whose key is its own,
    which is what the key routes and the `describe` answer are about. The endpoint is one the
    document schema accepts and no test ever dials: the turn runtime is given a script.
    """

    return GraphAgent(
        id=agent_id,
        name=agent_id.title(),
        instructions="Answer from the sources on the canvas.",
        model=(
            CustomAgentModel(endpoint=CUSTOM_ENDPOINT, model="gpt-5-mini")
            if custom
            else DeploymentAgentModel()
        ),
    )


async def _open_project(
    database_url: str,
    *,
    settings: Settings,
    cast: Cast,
    workspace_id: UUID,
    name: str,
    agents: Mapping[str, GraphAgent],
) -> UUID:
    """Open a Project and put one Agent on each of its Graphs.

    Through the real commands rather than by writing a document: an Agent gets onto a canvas by
    `add_agent`, a second Graph by `add_graph`, and those are the paths the routes under test
    then read the canvas through.
    """

    async with db(database_url) as database:
        service = CollaborationService(
            lambda: SqlAlchemyUnitOfWork(database.sessions),
            command_hmac_key=settings.keys.resolved_command_hmac_key(),
            command_hmac_key_version=settings.keys.command_hmac_key_version,
        )
        actor = ActorContext(user_id=cast.owner.id, credential_reference="test-seed")
        creation = await service.create_project(
            actor=actor, workspace_id=workspace_id, name=name
        )
        sequence = creation.head.collaboration_sequence
        if agents:
            commands: list[ProjectCommand] = []
            for graph_id, agent in agents.items():
                if graph_id != MAIN_GRAPH_ID:
                    commands.append(
                        AddGraphCommand(
                            graph_id=graph_id,
                            name=f"Graph {graph_id}",
                            document=GraphDocument(),
                        )
                    )
                commands.append(
                    InGraphCommand(
                        graph_id=graph_id,
                        command=AddAgentCommand(agent=agent),
                    )
                )
            await service.submit_commands(
                actor=actor,
                workspace_id=workspace_id,
                project_id=creation.project.id,
                command_id=uuid4(),
                observed_sequence=sequence,
                observed_room_epoch=creation.head.room_epoch,
                commands=tuple(commands),
            )
        return creation.project.id


async def _sessions(
    settings: Settings, database_url: str, cast: Cast
) -> dict[str, IssuedSession]:
    async with db(database_url) as database:

        def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(database.sessions)

        service = AuthService(
            auth=settings.auth,
            public_origin=settings.app.public_origin,
            unit_of_work_factory=unit_of_work_factory,
            identity_service=IdentityService(unit_of_work_factory),
        )
        return {
            "owner": await service.issue_session(cast.owner.id),
            "editor": await service.issue_session(cast.editor.id),
            "viewer": await service.issue_session(cast.viewer.id),
        }


@contextmanager
def stage(tmp_path: Path, name: str = "agents") -> Iterator[Stage]:
    database_url = create_db_url(tmp_path, f"{name}.sqlite3")
    settings = with_setting_values(
        Settings(app=AppConfig(public_origin=ORIGIN)),
        database_url=SecretStr(database_url),
        workspace=tmp_path / "workbench",
        credential_encryption_key=SecretStr(
            base64.b64encode(b"k" * 32).decode("ascii")
        ),
        agent_default_model="llama-4",
        agent_default_base_url="https://models.example/v1",
        agent_default_api_key=SecretStr(DEPLOYMENT_KEY),
    )

    async def prepare() -> tuple[Cast, dict[str, IssuedSession]]:
        cast = await _seed(database_url)
        return cast, await _sessions(settings, database_url, cast)

    cast, sessions = asyncio.run(prepare())
    project = asyncio.run(
        _open_project(
            database_url,
            settings=settings,
            cast=cast,
            workspace_id=cast.workspace,
            name="Sources",
            agents={MAIN: _agent(RESEARCH), NOTES: _agent(SCRIBE, custom=True)},
        )
    )
    other_project = asyncio.run(
        _open_project(
            database_url,
            settings=settings,
            cast=cast,
            workspace_id=cast.workspace,
            name="Other sources",
            agents={MAIN: _agent(RESEARCH)},
        )
    )
    foreign_project = asyncio.run(
        _open_project(
            database_url,
            settings=settings,
            cast=cast,
            workspace_id=cast.other_workspace,
            name="Elsewhere",
            agents={MAIN: _agent(RESEARCH)},
        )
    )

    scripted = ScriptedTurns()
    services: list[AgentService] = []

    def scripted_turn_service(request: Request) -> AgentService:
        """One turn runtime for the whole test, built on the app's own database and room.

        Built lazily and once: the first send creates it inside the app's loop, and every later
        request — including the Stop — has to reach the same instance, because a running turn
        is a task one owner holds. Everything else about it is the production composition: the
        same unit of work, the same resolver, the same Project room fan-out. Only the dialled
        model is a script.
        """

        if services:
            return services[0]
        resources = get_resources(request.app)
        service = AgentService(
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(
                resources.database.sessions, cleanups=resources.database.cleanups
            ),
            models=resources.agent_models,
            publisher=ProjectAgentEvents(hub=resources.project_room_hub),
            turn_model_factory=scripted.turn_model,
            partial_interval_seconds=0.0,
        )
        services.append(service)
        return service

    with client_with_overrides(
        settings=settings,
        overrides={agent_turn_service: scripted_turn_service},
    ) as client:
        api = GrafyApi(client)
        api.authenticate(sessions["owner"])
        live = Stage(
            client=client,
            api=api,
            settings=settings,
            workspace=cast.workspace,
            other_workspace=cast.other_workspace,
            project=project,
            other_project=other_project,
            foreign_project=foreign_project,
            sessions=sessions,
            scripted=scripted,
            services=services,
        )
        try:
            yield live
        finally:
            scripted.release_all()
            while live.open_rooms:
                session = live.open_rooms.pop()
                try:
                    session.__exit__(None, None, None)
                except BaseException:  # noqa: BLE001 - a cleanup cannot fail a test
                    pass
            # Stopped on the app's own loop, before that loop goes away: a turn is a task and
            # a task left behind outlives the claim the next test makes about its own state.
            portal = getattr(client, "portal", None)
            if services and portal is not None:
                try:
                    portal.call(_stop, services[0])
                except BaseException:  # noqa: BLE001 - the test has already reported
                    pass


async def _stop(service: AgentService) -> None:
    await service.close(timeout_seconds=0.5)
    await service.aclose()


def opened(stage: Stage, *, who: str = "editor", **kwargs: Any) -> dict[str, Any]:
    """Open a thread and fail the test with the response body if the route refused."""

    response = stage.start(headers=stage.as_(who), **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def settled(script: Script) -> Script:
    """Wait for the turn's ending to be written, then hand the script back.

    `finished` would be the model running out, which happens before the answer and the outcome
    are stored; `handed_back` is the runtime's own last act with the client, after the
    transaction. A test that reads the thread on this signal reads what was committed.
    """

    assert script.handed_back.wait(WAIT_SECONDS), "the scripted turn never handed back"
    return script


# --- the path is the scope ----------------------------------------------------


def test_a_thread_is_opened_read_and_listed_under_its_agent(tmp_path: Path) -> None:
    with stage(tmp_path) as live:
        thread = opened(live, title="The 1667 flood")
        assert thread["graph_id"] == MAIN
        assert thread["agent_id"] == RESEARCH
        assert thread["project_id"] == str(live.project)
        assert thread["last_sequence"] == 0
        conversation_id = UUID(thread["id"])

        fetched = live.conversation(conversation_id)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["title"] == "The 1667 flood"

        listed = live.conversations()
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()["conversations"]] == [
            str(conversation_id)
        ]

        # Another Agent of the same Project has nothing to do with this thread.
        assert (
            live.conversations(agent=SCRIBE, graph=NOTES).json()["conversations"] == []
        )
        assert (
            live.conversation(conversation_id, agent=SCRIBE, graph=NOTES).status_code
            == 404
        )

        empty = live.events(conversation_id)
        assert empty.status_code == 200, empty.text
        assert empty.json()["events"] == []
        assert empty.json()["last_sequence"] == 0

        idle = live.active(conversation_id)
        assert idle.status_code == 200, idle.text
        assert idle.json() is None


def test_a_conversation_is_only_here_when_the_whole_path_matches(
    tmp_path: Path,
) -> None:
    """The same Workspace, the same Project, the wrong card: all of them are 404.

    A Workspace-only lookup would answer these as if the caller had named the right thing, and
    the answer it gives would then be used to read a thread that belongs to another Agent.
    """

    with stage(tmp_path) as live:
        thread = UUID(opened(live)["id"])
        script = live.scripted.add(Script(["An answer."]))
        sent = live.send(thread, text="Asked here.", turn_id="client-1")
        assert sent.status_code == 201, sent.text
        settled(script)

        assert live.conversation(thread, project=live.other_project).status_code == 404
        assert live.conversation(thread, graph=NOTES, agent=SCRIBE).status_code == 404
        assert live.conversation(thread, agent=SCRIBE).status_code == 404
        # A Project of another Workspace reads the same way, from a member of both.
        headers = live.as_("owner")
        assert (
            live.conversation(
                thread, project=live.foreign_project, headers=headers
            ).status_code
            == 404
        )
        assert live.events(thread, graph=NOTES, agent=SCRIBE).status_code == 404
        assert live.active(thread, agent=SCRIBE).status_code == 404
        assert (
            live.send(
                thread, text="Elsewhere.", turn_id="client-2", graph=NOTES, agent=SCRIBE
            ).status_code
            == 404
        )
        assert live.cancel(thread, agent=SCRIBE).status_code == 404

        # The write that a body could aim somewhere else: a Stop carrying another thread's
        # turn id is refused rather than stopping that turn. Both threads are the same Agent,
        # so the only difference between them is the conversation in the path.
        elsewhere = UUID(opened(live)["id"])
        script_two = live.scripted.add(Script(["Half."], park_after=0))
        running = live.send(elsewhere, text="Second thread.", turn_id="other-1")
        assert running.status_code == 201, running.text
        assert script_two.parked.wait(WAIT_SECONDS)
        turn_id = running.json()["id"]
        refused = live.cancel(thread, turn_id=turn_id)
        assert refused.status_code == 404, refused.text
        assert running.json()["status"] == "running"
        assert live.cancel(elsewhere, turn_id=turn_id).status_code == 200
        script_two.release()


def test_a_conversation_of_another_workspace_is_not_here_at_all(tmp_path: Path) -> None:
    with stage(tmp_path) as live:
        headers = live.as_("owner")
        foreign = live.client.post(
            f"/v1/workspaces/{live.other_workspace}/projects/{live.foreign_project}"
            f"/graphs/{MAIN}/agents/{RESEARCH}/conversations",
            json={"title": "Elsewhere"},
            headers=headers,
        )
        assert foreign.status_code == 201, foreign.text
        foreign_id = UUID(foreign.json()["id"])

        # The same member, the same Agent name, the other Workspace's path: served.
        assert (
            live.client.get(
                f"/v1/workspaces/{live.other_workspace}/projects/{live.foreign_project}"
                f"/graphs/{MAIN}/agents/{RESEARCH}/conversations/{foreign_id}",
                headers=headers,
            ).status_code
            == 200
        )
        # Addressed from this Workspace, it is simply not there.
        assert live.conversation(foreign_id, headers=headers).status_code == 404


# --- send, its answer, and its idempotence ------------------------------------


def test_a_send_answers_a_receipt_and_the_answer_arrives_in_the_events(
    tmp_path: Path,
) -> None:
    """The route is the admission, the events are the answer, the room is the middle."""

    with stage(tmp_path) as live:
        room = live.room()
        thread = UUID(opened(live)["id"])
        script = live.scripted.add(Script(["The diary says ", "it rained."]))

        sent = live.send(thread, text="What did the diary say?", turn_id="client-1")
        assert sent.status_code == 201, sent.text
        receipt = sent.json()
        assert receipt["status"] == "running"
        assert receipt["client_turn_id"] == "client-1"
        assert receipt["user_message_sequence"] == 1
        assert receipt["model_name"] == "llama-4"
        assert receipt["model_source"] == "deployment"
        # The receipt is not the answer, and never carries the question's text or a credential.
        assert "text" not in receipt
        assert DEPLOYMENT_KEY not in sent.text

        started = room.until("agent.turn.started")
        assert started["turn"]["turn_id"] == receipt["id"]
        finished = room.until("agent.turn.finished")
        assert finished["turn_id"] == receipt["id"]
        assert finished["outcome"] == "completed"

        settled(script)
        events = live.events(thread).json()["events"]
        assert [event["payload"]["kind"] for event in events] == [
            "user_message",
            "assistant_message",
            "turn_outcome",
        ]
        assert events[1]["payload"]["text"] == "The diary says it rained."
        assert events[2]["payload"]["outcome"] == "completed"
        assert live.active(thread).json() is None


def test_a_repeated_send_answers_the_turn_it_already_made(tmp_path: Path) -> None:
    """One client turn id is one turn: no second question, no second event, no second call."""

    with stage(tmp_path) as live:
        thread = UUID(opened(live)["id"])
        script = live.scripted.add(Script(["One answer."]))
        first = live.send(thread, text="What happened?", turn_id="client-1")
        assert first.status_code == 201, first.text
        settled(script)

        again = live.send(thread, text="What happened?", turn_id="client-1")
        assert again.status_code == 201, again.text
        assert again.json()["id"] == first.json()["id"]
        assert script.calls == 1

        events = live.events(thread).json()["events"]
        assert [event["payload"]["kind"] for event in events] == [
            "user_message",
            "assistant_message",
            "turn_outcome",
        ]
        assert events[0]["payload"]["text"] == "What happened?"


def test_the_same_turn_id_with_different_text_is_a_conflict(tmp_path: Path) -> None:
    with stage(tmp_path) as live:
        thread = UUID(opened(live)["id"])
        script = live.scripted.add(Script(["An answer."]))
        first = live.send(thread, text="What happened?", turn_id="client-1")
        settled(script)
        assert first.status_code == 201, first.text

        mutated = live.send(
            thread, text="What happened? Be thorough.", turn_id="client-1"
        )
        assert mutated.status_code == 409, mutated.text
        assert mutated.json()["detail"]["code"] == "agent_turn_id_reused"
        assert mutated.json()["detail"]["turn_id"] == first.json()["id"]
        assert script.calls == 1
        assert len(live.events(thread).json()["events"]) == 3


def test_a_second_question_to_a_busy_conversation_names_the_turn_it_would_have_run_behind(
    tmp_path: Path,
) -> None:
    with stage(tmp_path) as live:
        thread = UUID(opened(live)["id"])
        parked = live.scripted.add(Script(["Half an answer."], park_after=0))
        first = live.send(thread, text="First", turn_id="client-1")
        assert first.status_code == 201, first.text
        assert parked.parked.wait(WAIT_SECONDS)

        busy = live.send(thread, text="Second", turn_id="client-2")
        assert busy.status_code == 409, busy.text
        assert busy.json()["detail"]["code"] == "agent_conversation_busy"
        assert busy.json()["detail"]["turn_id"] == first.json()["id"]
        assert parked.calls == 1

        in_flight = live.active(thread)
        assert in_flight.status_code == 200, in_flight.text
        body = in_flight.json()
        assert body is not None
        assert body["turn"]["id"] == first.json()["id"]
        assert body["partial_text"] == ""
        assert UUID(body["message_id"])

        stopped = live.cancel(thread)
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["id"] == first.json()["id"]
        assert stopped.json()["status"] == "cancelled"
        parked.release()


def test_a_stop_is_a_request_and_answering_twice_changes_nothing(
    tmp_path: Path,
) -> None:
    with stage(tmp_path) as live:
        thread = UUID(opened(live)["id"])
        script = live.scripted.add(Script(["Half."], park_after=0))
        sent = live.send(thread, text="Ask", turn_id="client-1")
        assert sent.status_code == 201, sent.text
        assert script.parked.wait(WAIT_SECONDS)

        first = live.cancel(thread)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "cancelled"
        second = live.cancel(thread)
        assert second.status_code == 200, second.text
        assert second.json() == first.json()

        events = live.events(thread).json()["events"]
        assert [event["payload"]["kind"] for event in events] == [
            "user_message",
            "turn_outcome",
        ]
        assert events[1]["payload"]["outcome"] == "cancelled"
        script.release()

        # And the thread is free again: the next question is a new turn, not a busy refusal.
        next_script = live.scripted.add(Script(["After the stop."]))
        again = live.send(thread, text="Again?", turn_id="client-2")
        assert again.status_code == 201, again.text
        settled(next_script)
        assert again.json()["id"] != first.json()["id"]


def test_the_events_route_resumes_where_a_reader_stopped(tmp_path: Path) -> None:
    with stage(tmp_path) as live:
        thread = UUID(opened(live)["id"])
        script = live.scripted.add(Script(["An answer."]))
        assert live.send(thread, text="Q", turn_id="client-1").status_code == 201
        settled(script)

        whole = live.events(thread).json()
        assert whole["last_sequence"] == 3
        assert [event["sequence"] for event in whole["events"]] == [1, 2, 3]

        resumed = live.events(thread, query="?after_sequence=2").json()
        assert [event["sequence"] for event in resumed["events"]] == [3]
        assert resumed["next_sequence"] == 3

        paged = live.events(thread, query="?limit=2").json()
        assert [event["sequence"] for event in paged["events"]] == [1, 2]
        assert paged["last_sequence"] == 3, "a page looked like the whole thread"
        assert live.events(thread, query="?after_sequence=99").json()["events"] == []


def test_a_fork_copies_the_prefix_and_refuses_a_sequence_it_does_not_have(
    tmp_path: Path,
) -> None:
    with stage(tmp_path) as live:
        thread = UUID(opened(live)["id"])
        script = live.scripted.add(Script(["First answer."]))
        assert live.send(thread, text="Q one", turn_id="client-1").status_code == 201
        settled(script)

        forked = live.fork(thread, at_sequence=1, title="Continue from the question")
        assert forked.status_code == 201, forked.text
        copy = forked.json()
        assert copy["id"] != str(thread)
        assert copy["source_conversation_id"] == str(thread)
        assert copy["source_sequence"] == 1
        # A fork continues the same Agent in the same Project; it is not a way to move a thread.
        assert copy["project_id"] == str(live.project)
        assert copy["graph_id"] == MAIN
        assert copy["agent_id"] == RESEARCH
        assert [
            event["sequence"]
            for event in live.events(UUID(copy["id"])).json()["events"]
        ] == [1]

        second = live.scripted.add(Script(["Second answer."]))
        assert (
            live.send(UUID(copy["id"]), text="Q two", turn_id="client-1").status_code
            == 201
        )
        settled(second)
        # The source keeps going untouched.
        assert [
            event["sequence"] for event in live.events(thread).json()["events"]
        ] == [1, 2, 3]
        # And the copy's next turn is built from only what it copied: the answer that arrived
        # after the cut is not in the history the model was given, and the question it was cut at
        # is. That is what "continue from here" has to mean for the model, not only for the list.
        seen_parts = [
            getattr(part, "content", None)
            for message in second.messages[0]
            for part in message.parts
        ]
        assert "Q one" in seen_parts
        assert "First answer." not in seen_parts

        refused = live.fork(thread, at_sequence=99)
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "agent_fork_sequence_unknown"
        assert live.fork(thread, at_sequence=0).status_code == 422


# --- configuration, and the key that never comes back -------------------------


def test_the_model_configuration_is_readable_and_the_key_write_only(
    tmp_path: Path,
) -> None:
    with stage(tmp_path) as live:
        deployment = live.model()
        assert deployment.status_code == 200, deployment.text
        assert deployment.json() == {
            "source": "deployment",
            "model_name": "llama-4",
            "base_url": "https://models.example/v1",
            "key_configured": True,
        }
        assert DEPLOYMENT_KEY not in deployment.text

        own = live.model(agent=SCRIBE, graph=NOTES)
        assert own.status_code == 200, own.text
        assert own.json()["source"] == "agent"
        assert own.json()["key_configured"] is False

        stored = live.put_key(AGENT_KEY, agent=SCRIBE, graph=NOTES)
        assert stored.status_code == 200, stored.text
        assert stored.json() == {"agent_id": SCRIBE, "configured": True}
        assert AGENT_KEY not in stored.text
        assert AGENT_KEY not in live.model(agent=SCRIBE, graph=NOTES).text
        assert live.model(agent=SCRIBE, graph=NOTES).json()["key_configured"] is True

        cleared = live.delete_key(agent=SCRIBE, graph=NOTES)
        assert cleared.status_code == 204, cleared.text
        assert cleared.content == b""
        assert live.model(agent=SCRIBE, graph=NOTES).json()["key_configured"] is False
        # Clearing twice is the same answer, because the state a person asked about is the same.
        assert live.delete_key(agent=SCRIBE, graph=NOTES).status_code == 204

        # A card that is not on the canvas has no configuration surface, only a 404.
        assert live.model(agent="absent").status_code == 404
        assert live.put_key(AGENT_KEY, agent="absent").status_code == 404


def test_an_agent_that_needs_a_key_it_does_not_have_says_so(tmp_path: Path) -> None:
    """The refusal is an operator's answer, and it strands nothing.

    Resolution happens before the receipt is written, so a turn that could never be dialled
    leaves no running row behind and holds no credential: the thread stays openable and the
    next question is answerable once the key is there.
    """

    with stage(tmp_path) as live:
        thread = UUID(opened(live, graph=NOTES, agent=SCRIBE)["id"])
        refused = live.send(
            thread,
            text="Ask the custom model",
            turn_id="client-1",
            graph=NOTES,
            agent=SCRIBE,
        )
        assert refused.status_code == 503, refused.text
        assert AGENT_KEY not in refused.text
        assert live.events(thread, graph=NOTES, agent=SCRIBE).json()["events"] == []
        assert live.active(thread, graph=NOTES, agent=SCRIBE).json() is None

        assert live.put_key(AGENT_KEY, agent=SCRIBE, graph=NOTES).status_code == 200
        script = live.scripted.add(Script(["With its own key."]))
        sent = live.send(
            thread,
            text="Ask the custom model",
            turn_id="client-1",
            graph=NOTES,
            agent=SCRIBE,
        )
        assert sent.status_code == 201, sent.text
        settled(script)
        assert live.delete_key(agent=SCRIBE, graph=NOTES).status_code == 204


# --- capabilities and scopes --------------------------------------------------


def test_reading_a_thread_is_view_project_and_sending_one_is_start_run(
    tmp_path: Path,
) -> None:
    with stage(tmp_path) as live:
        thread = UUID(opened(live, who="owner")["id"])
        script = live.scripted.add(Script(["An answer."]))
        assert (
            live.send(
                thread, text="Q", turn_id="client-1", headers=live.as_("owner")
            ).status_code
            == 201
        )
        settled(script)

        viewer = live.as_("viewer")
        assert live.conversations(headers=viewer).status_code == 200
        assert live.conversation(thread, headers=viewer).status_code == 200
        assert live.events(thread, headers=viewer).status_code == 200
        assert live.active(thread, headers=viewer).status_code == 200
        assert live.model(headers=viewer).status_code == 200

        refused = live.send(thread, text="Q2", turn_id="client-2", headers=viewer)
        assert refused.status_code == 403, refused.text
        assert live.start(headers=viewer).status_code == 403
        assert live.fork(thread, at_sequence=1, headers=viewer).status_code == 403
        assert live.cancel(thread, headers=viewer).status_code == 403
        assert live.put_key(AGENT_KEY, headers=viewer).status_code == 403
        assert live.delete_key(headers=viewer).status_code == 403
        # An editor, who holds start_run and edit_project, is served by all of them.
        editor = live.as_("editor")
        assert live.put_key(AGENT_KEY, headers=editor).status_code == 200
        assert live.delete_key(headers=editor).status_code == 204


def test_a_token_is_served_by_its_scopes_and_refused_by_the_rest(
    tmp_path: Path,
) -> None:
    """Role is not enough: below the route a token's scope is invisible, so the route is the gate.

    Each request is made with a token whose role would allow it, so a 200 can only have come
    from the scope and a 403 can only be about the scope.
    """

    with stage(tmp_path) as live:
        opened_id = UUID(opened(live, who="owner")["id"])
        script = live.scripted.add(Script(["An answer."]))
        assert (
            live.send(
                opened_id, text="Q", turn_id="client-1", headers=live.as_("owner")
            ).status_code
            == 201
        )
        settled(script)

        run_only = live.token("run-only", PersonalAccessTokenScope.START_RUN)
        assert live.conversation(opened_id, headers=run_only).status_code == 403

        reader = live.token("reader", PersonalAccessTokenScope.VIEW_PROJECT)
        assert live.conversations(headers=reader).status_code == 200
        assert live.conversation(opened_id, headers=reader).status_code == 200
        assert live.events(opened_id, headers=reader).status_code == 200
        assert live.model(headers=reader).status_code == 200
        assert (
            live.send(
                opened_id, text="Q2", turn_id="client-2", headers=reader
            ).status_code
            == 403
        )
        assert live.start(headers=reader).status_code == 403
        assert live.cancel(opened_id, headers=reader).status_code == 403
        assert live.put_key(AGENT_KEY, headers=reader).status_code == 403

        sender = live.token(
            "sender",
            PersonalAccessTokenScope.VIEW_PROJECT,
            PersonalAccessTokenScope.START_RUN,
        )
        second = live.scripted.add(Script(["Answered by a token."]))
        sent = live.send(opened_id, text="Q3", turn_id="client-3", headers=sender)
        assert sent.status_code == 201, sent.text
        settled(second)
        # A token that may send may not therefore configure the card it is sending to.
        assert live.put_key(AGENT_KEY, headers=sender).status_code == 403

        configurer = live.token(
            "configurer",
            PersonalAccessTokenScope.VIEW_PROJECT,
            PersonalAccessTokenScope.EDIT_PROJECT,
        )
        assert (
            live.put_key(
                AGENT_KEY, headers=configurer, agent=SCRIBE, graph=NOTES
            ).status_code
            == 200
        )
        assert (
            live.delete_key(headers=configurer, agent=SCRIBE, graph=NOTES).status_code
            == 204
        )
        assert (
            live.send(
                opened_id, text="Q4", turn_id="client-4", headers=configurer
            ).status_code
            == 403
        )
