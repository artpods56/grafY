"""Scaffolding for the Agent turn runtime tests (ADR 0021, issue #202).

A scripted pydantic-ai `FunctionModel` is the point of this file: the turn loop is driven
with real streaming events, real cancellation and real message reconstruction, and no
connection is ever opened. Three seams make that possible.

* `ScriptedResolver` answers with a fixed endpoint and key, so resolution is exercised
  without a deployment configuration or a sealed credential.
* `ScriptedModel.turn_model` hands the runtime a `FunctionModel` whose stream the test parks
  and releases, and reports whether the turn handed the client back. An Agent that gets a
  scripted in-process model owns nothing to close, which is why `AgentTurnModel.close` is
  optional in production too.
* `FakeClock` is what the ~75 ms coalescing rule is read from, so that rule is a decision
  under test rather than a delay a test hopes to land inside.

Nothing here waits on time. A stream blocks on an `asyncio.Event` the test owns, and every
notification is recorded for the test to read back.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import asyncio
import pytest
from pydantic import SecretStr
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.messages import ModelMessage

from grafy_api.agents.conversations import AgentConversationService
from grafy_api.agents.models import ResolvedAgentModel
from grafy_api.agents.publishing import AgentConversationNotice, AgentTextPartial
from grafy_api.agents.turns import AgentService, AgentTurnModel
from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    AgentConversationTurnOutcome,
    AssistantMessagePayload,
    TurnOutcomePayload,
    UserMessagePayload,
)
from grafy_core.domain.agent_turns import AgentTurn
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.graph_documents import (
    CustomAgentModel,
    DeploymentAgentModel,
    GraphAgent,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.graph_documents import GraphDocument, GraphNode
from grafy_api.agents.turns import AgentToolboxFactory
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork

WORKSPACE = UUID(int=801)
PROJECT = UUID(int=802)
EPOCH = UUID(int=803)
AUTHOR = UUID(int=804)
OTHER_WORKSPACE = UUID(int=805)
GRAPH_ID = "main"
AGENT_ID = "research"
DIAL_KEY = "sekrit-agent-dial-key-0123456789"
CUSTOM_ENDPOINT = "https://models.example/v1"
INSTRUCTIONS = "Answer from the sources."
T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
DEFAULT_INTERVAL = 0.075


def access(
    user_id: UUID = AUTHOR, role: WorkspaceRole = WorkspaceRole.EDITOR
) -> WorkspaceAccess:
    """One member's own rights. What a role grants is exactly what these two owners
    re-check; the narrower scope a token carries is the route's to intersect."""

    return WorkspaceAccess(
        actor=ActorContext(user_id=user_id),
        workspace_id=WORKSPACE,
        membership=WorkspaceMembership(
            workspace_id=WORKSPACE, user_id=user_id, role=role
        ),
    )


def other_workspace_access() -> WorkspaceAccess:
    return WorkspaceAccess(
        actor=ActorContext(user_id=AUTHOR),
        workspace_id=OTHER_WORKSPACE,
        membership=WorkspaceMembership(
            workspace_id=OTHER_WORKSPACE, user_id=AUTHOR, role=WorkspaceRole.OWNER
        ),
    )


def agent(
    *,
    agent_id: str = AGENT_ID,
    instructions: str = INSTRUCTIONS,
    model: object | None = None,
) -> GraphAgent:
    return GraphAgent(
        id=agent_id,
        name=agent_id.title(),
        instructions=instructions,
        model=DeploymentAgentModel() if model is None else model,  # type: ignore[arg-type]
    )


def custom_agent_model() -> CustomAgentModel:
    return CustomAgentModel(endpoint=CUSTOM_ENDPOINT, model="gpt-5-mini")


def head(
    *,
    agents: Sequence[GraphAgent] | None = None,
    nodes: Sequence[GraphNode] = (),
) -> ProjectHead:
    return ProjectHead(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        room_epoch=EPOCH,
        collaboration_sequence=3,
        checkpoint_sequence=0,
        checkpoint_revision=1,
        name="Agents",
        document=ProjectDocument(
            graphs=(
                GraphDefinition(
                    id=GRAPH_ID,
                    name="Main",
                    document=GraphDocument(
                        agents=tuple(agents if agents is not None else (agent(),)),
                        nodes=tuple(nodes),
                    ),
                ),
            )
        ),
    )


def with_document(head: ProjectHead, document: GraphDocument) -> ProjectHead:
    """The same head with one Graph's saved document replaced."""

    graphs = tuple(
        definition.model_copy(update={"document": document})
        if definition.id == GRAPH_ID
        else definition
        for definition in head.document.graphs
    )
    return replace(head, document=head.document.model_copy(update={"graphs": graphs}))


class ScriptedResolver:
    """The model a turn dials, answered without a deployment or a key store."""

    def __init__(
        self, *, source: str = "deployment", model_name: str = "llama-4"
    ) -> None:
        self.source = source
        self.model_name = model_name
        self.calls: list[str] = []

    async def resolve(
        self, *, workspace_id: UUID, project_id: UUID, graph_id: str, agent: GraphAgent
    ) -> ResolvedAgentModel:
        del workspace_id, project_id, graph_id
        self.calls.append(agent.id)
        return ResolvedAgentModel(
            source=self.source,  # type: ignore[arg-type]
            model_name=self.model_name,
            base_url=CUSTOM_ENDPOINT,
            api_key=SecretStr(DIAL_KEY),
        )


class BrokenResolver:
    """Nothing can be dialled: no deployment default, or an Agent's own key is gone."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def resolve(
        self, *, workspace_id: UUID, project_id: UUID, graph_id: str, agent: GraphAgent
    ) -> ResolvedAgentModel:
        del workspace_id, project_id, graph_id, agent
        self.calls += 1
        raise self.error


class FakeClock:
    """A clock the test moves, so coalescing is decided rather than raced."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class ScriptedModel:
    """A stream the test drives, plus what the runtime told it and gave back.

    `park_after` is how many chunks may go out before the stream parks itself on an event
    only the test can set. That is the whole trick behind "cancelled before the first
    chunk" and "cancelled with one chunk in hand": the runtime is put in that state and
    left there until the assertion is ready for it.
    """

    chunks: Sequence[str]
    # How many chunks may go out before the stream parks itself on an event only the test
    # can set. That is the whole trick behind "cancelled before the first chunk" and
    # "cancelled with one chunk in hand": the runtime is put in that state and left there
    # until the assertion is ready for it, instead of raced against.
    park_after: int | None = None
    # Moved between chunks when a test needs the clock to pass inside a stream, which is the
    # only honest way to say "these two chunks are not in the same window".
    chunk_interval: float | None = None
    clock: FakeClock | None = None
    error: Exception | None = None
    calls: int = 0
    closed: int = 0
    seen: list[tuple[str, list[tuple[str, object]]]] = field(default_factory=list)
    seen_instructions: list[str | None] = field(default_factory=list)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    parked: asyncio.Event = field(default_factory=asyncio.Event)
    completed: asyncio.Event = field(default_factory=asyncio.Event)
    _release: asyncio.Event = field(default_factory=asyncio.Event)

    def release(self) -> None:
        """Let a parked stream carry on."""

        self._release.set()

    def turn_model(self, resolved: ResolvedAgentModel | None = None) -> AgentTurnModel:
        """What the runtime gets instead of a dialled endpoint.

        The resolved model is ignored on purpose: a scripted stream needs no credential, no
        transport and nothing to close, which is exactly the case `AgentTurnModel` keeps
        `close` optional for.
        """

        del resolved
        return AgentTurnModel(chat_model=self.model(), close=self._close)

    async def _close(self) -> None:
        self.closed += 1

    def model(self) -> FunctionModel:
        async def stream(messages: list[ModelMessage], agent_info: AgentInfo):
            self.calls += 1
            self.seen_instructions.append(agent_info.instructions)
            self.seen = [
                (
                    type(message).__name__,
                    [
                        (part.part_kind, getattr(part, "content", None))
                        for part in message.parts
                    ],
                )
                for message in messages
            ]
            self.started.set()
            for index, chunk in enumerate(self.chunks):
                if self.chunk_interval is not None and self.clock is not None and index:
                    self.clock.advance(self.chunk_interval)
                if self.park_after is not None and index >= self.park_after:
                    self.parked.set()
                    await self._release.wait()
                yield chunk
            # The failure comes after the script, because that is the interesting case: a
            # provider that streamed something and then broke, so the runtime has text in
            # hand and an exception to explain.
            if self.error is not None:
                raise self.error
            self.completed.set()

        return FunctionModel(stream_function=stream)


@dataclass
class RecordingPublisher:
    """Everything the room would be told, in the order it was told it.

    `wait_for_*` is how a test knows a notification has landed rather than merely been
    started: a turn's start and finish are told on tasks of their own so a wedged room
    cannot slow a turn, and that separation is only worth having if a test can prove it.

    `order` is the same telling as one flat list, because the contract a reader depends on is
    an order: the buffered text goes out, then the stored answer, then the stored ending,
    then the finish. Asserting on four separate lists could not say that.
    """

    started: list[AgentTurn] = field(default_factory=list)
    events: list[AgentConversationNotice] = field(default_factory=list)
    partials: list[AgentTextPartial] = field(default_factory=list)
    finished: list[tuple[AgentTurn, AgentConversationTurnOutcome, str | None]] = field(
        default_factory=list
    )
    order: list[str] = field(default_factory=list)
    fail_partials: bool = False
    block: asyncio.Event | None = None
    _partial_arrived: asyncio.Event = field(default_factory=asyncio.Event)
    _finished_arrived: asyncio.Event = field(default_factory=asyncio.Event)
    _event_arrived: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def streamed_text(self) -> str:
        return "".join(partial.text for partial in self.partials)

    @property
    def stored_text(self) -> str:
        """The assistant message the room was told about, from the durable events."""

        return "".join(
            notice.event.payload.text
            for notice in self.events
            if isinstance(notice.event.payload, AssistantMessagePayload)
        )

    async def wait_for_partials(self, count: int = 1) -> None:
        while len(self.partials) < count:
            self._partial_arrived.clear()
            await self._partial_arrived.wait()

    async def wait_for_events(self, count: int = 1) -> None:
        while len(self.events) < count:
            self._event_arrived.clear()
            await self._event_arrived.wait()

    async def wait_for_finished(self) -> None:
        while not self.finished:
            self._finished_arrived.clear()
            await self._finished_arrived.wait()

    async def turn_started(self, turn: AgentTurn) -> None:
        await self._gate()
        self.started.append(turn)
        self.order.append("turn.started")

    async def event_appended(self, notice: AgentConversationNotice) -> None:
        await self._gate()
        self.events.append(notice)
        self.order.append(f"event.appended:{notice.event.payload.kind}")
        self._event_arrived.set()

    async def text_partial(self, partial: AgentTextPartial) -> None:
        await self._gate()
        if self.fail_partials:
            raise RuntimeError("the room connection is gone")
        self.partials.append(partial)
        self.order.append("delta")
        self._partial_arrived.set()

    async def turn_finished(
        self,
        turn: AgentTurn,
        *,
        outcome: AgentConversationTurnOutcome,
        detail: str | None,
    ) -> None:
        await self._gate()
        self.finished.append((turn, outcome, detail))
        self.order.append("turn.finished")
        self._finished_arrived.set()

    async def _gate(self) -> None:
        if self.block is not None:
            await self.block.wait()


def stored_text(event: AgentConversationEvent) -> str:
    """The characters a message event carries, with a failure that says what came instead.

    A test that reaches past the payload's type gets a wrong answer rather than a signal
    when the runtime writes a different event than the one it meant to, so the check is
    part of reading it.
    """

    payload = event.payload
    assert isinstance(payload, (UserMessagePayload, AssistantMessagePayload)), (
        f"expected a message event, got {payload.kind}"
    )
    return payload.text


def stored_outcome(event: AgentConversationEvent) -> AgentConversationTurnOutcome:
    """How a turn ended, from its outcome event."""

    payload = event.payload
    assert isinstance(payload, TurnOutcomePayload), (
        f"expected an outcome, got {payload.kind}"
    )
    return payload.outcome


class TurnHarness:
    """One Project, one Agent on a Graph, one conversation, and the service under test.

    `restart` is how a test says "a new process, the same database": a fresh service over
    the same store, with nothing carried over in memory, which is what a deployment
    actually does and the only honest way to test recovery.
    """

    def __init__(
        self,
        model: ScriptedModel | Sequence[ScriptedModel],
        *,
        agents: Sequence[GraphAgent] | None = None,
        publisher: RecordingPublisher | None = None,
        resolver: object | None = None,
        interval: float = DEFAULT_INTERVAL,
        clock: FakeClock | None = None,
        store: InMemoryDataStore | None = None,
        nodes: Sequence[GraphNode] = (),
        toolbox_factory: AgentToolboxFactory | None = None,
    ) -> None:
        self.toolbox_factory = toolbox_factory
        self.head = head(agents=agents, nodes=nodes)
        self.store = store if store is not None else InMemoryDataStore()
        self.clock = clock if clock is not None else FakeClock()
        self.publisher = publisher if publisher is not None else RecordingPublisher()
        self.resolver = resolver if resolver is not None else ScriptedResolver()
        # One script, or one per turn: a service builds its model per turn from a single
        # factory, so two turns whose scripts are told apart need two scripts.
        self.scripts = [model] if isinstance(model, ScriptedModel) else list(model)
        self.model: ScriptedModel = self.scripts[0]
        self._script_turns = 0
        self.conversations = AgentConversationService(
            unit_of_work_factory=lambda: InMemoryUnitOfWork(self.store)
        )
        self.conversation_id: UUID | None = None
        # Every service this test made. A turn is a task, and a test that leaves one parked
        # is lying about the next test, so the fixture stops them all.
        self.services: list[AgentService] = []
        _HARNESSES.append(self)
        # The interval and publisher are the test's, not the constructor's defaults: a test
        # that says "publish every chunk" means it.
        self.restart(model, interval=interval, publisher=self.publisher)

    def _turn_model(self, resolved: ResolvedAgentModel | None = None) -> AgentTurnModel:
        """The script for the turn now starting. The last one is reused after they run out.

        Handing out a script per turn is what lets a test say which turn asked for what;
        repeating the last script when a test starts more turns than it wrote scripts is a
        failure the reader should see in an assertion rather than a `IndexError` in a task.
        """

        script = self.scripts[min(self._script_turns, len(self.scripts) - 1)]
        self._script_turns += 1
        return script.turn_model(resolved)

    def restart(
        self,
        model: ScriptedModel | Sequence[ScriptedModel] | None = None,
        *,
        interval: float | None = None,
        publisher: RecordingPublisher | None = None,
    ) -> AgentService:
        """A service with nothing in its memory and the same durable state behind it.

        This is what "the API owner restarted" means for a test: a new process would carry
        no live turns, would read the receipts it finds, and would be wired with whatever
        the deployment says today rather than what it said when the turn was admitted.
        """
        """A service with nothing in its memory and the same durable state behind it.

        This is what "the API owner restarted" means for a test: a new process would carry
        no live turns, would read the receipts it finds, and would be wired with whatever
        the deployment says today, not what it said when the turn was admitted.
        """

        if model is not None:
            self.scripts = [model] if isinstance(model, ScriptedModel) else list(model)
            self.model = self.scripts[0]
            self._script_turns = 0
        if publisher is not None:
            self.publisher = publisher
        service = AgentService(
            unit_of_work_factory=lambda: InMemoryUnitOfWork(self.store),
            models=self.resolver,  # type: ignore[arg-type]
            publisher=self.publisher,
            turn_model_factory=self._turn_model,
            partial_interval_seconds=(
                DEFAULT_INTERVAL if interval is None else interval
            ),
            clock=self.clock,
            toolbox_factory=self.toolbox_factory,
        )
        self.services.append(service)
        self.service = service
        return service

    async def thread(self) -> AgentConversation:
        """The one conversation these tests send into, started once per test."""

        if self.conversation_id is None:
            async with InMemoryUnitOfWork(self.store) as unit_of_work:
                await unit_of_work.collaboration.add_head(self.head)
                await unit_of_work.commit()
            started = await self.conversations.start(
                workspace_id=WORKSPACE,
                project_id=PROJECT,
                graph_id=GRAPH_ID,
                agent_id=AGENT_ID,
                author_user_id=AUTHOR,
                title="Sources on the 1667 flood",
            )
            self.conversation_id = started.id
        return await self.conversations.get(
            workspace_id=WORKSPACE, conversation_id=self.conversation_id
        )

    async def other_thread(self) -> AgentConversation:
        """A second thread with the same Agent, for what is per conversation."""

        return await self.conversations.start(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
            author_user_id=AUTHOR,
            title="Another afternoon",
        )

    async def send_to(
        self, conversation_id: UUID, text: str, turn_id: str = "client-1"
    ) -> AgentTurn:
        return await self.service.send(
            access=access(),
            conversation_id=conversation_id,
            client_turn_id=turn_id,
            text=text,
        )

    async def send(
        self, text: str = "What did the diary say?", turn_id: str = "client-1"
    ) -> AgentTurn:
        conversation = await self.thread()
        return await self.service.send(
            access=access(),
            conversation_id=conversation.id,
            client_turn_id=turn_id,
            text=text,
        )

    async def settle(self, *, release: bool = True) -> AgentTurn:
        """This conversation's turn, after it has ended and recorded how.

        `release` is the other half of a parked stream: a test that parked the model to look
        at an intermediate state says so here and the turn carries on to its ending.
        """

        conversation = await self.thread()
        return await self.settle_conversation(conversation.id, release=release)

    async def settle_conversation(
        self, conversation_id: UUID, *, release: bool = True
    ) -> AgentTurn:
        if release:
            for script in self.scripts:
                script.release()
        settled = await self.service.wait_for_turn(
            access=access(), conversation_id=conversation_id
        )
        await self.service.wait_for_notifications(timeout_seconds=0.25)
        return settled

    async def events(self) -> list[AgentConversationEvent]:
        conversation = await self.thread()
        return await self.conversations.read_events(
            workspace_id=WORKSPACE, conversation_id=conversation.id
        )

    async def kinds(self) -> list[str]:
        return [event.payload.kind for event in await self.events()]

    async def outcome_events(self) -> list[AgentConversationEvent]:
        return [
            event
            for event in await self.events()
            if isinstance(event.payload, TurnOutcomePayload)
        ]

    async def edit_canvas(self, *agents: GraphAgent) -> None:
        """Replace the Graph's Agents, the way an accepted command would."""

        await self.thread()
        async with InMemoryUnitOfWork(self.store) as unit_of_work:
            stored = await unit_of_work.collaboration.get_head(WORKSPACE, PROJECT)
            assert stored is not None
            document = stored.document.get_graph(GRAPH_ID).document.model_copy(
                update={"agents": agents}
            )
            await unit_of_work.collaboration.save_head(with_document(stored, document))
            await unit_of_work.commit()

    async def drain(self) -> None:
        """Stop every task every service this test made ever started.

        A parked scripted stream will never finish on its own, and an async test that
        leaves a task running tells the next test something untrue. Recovery tests
        deliberately keep an abandoned service around — that is the restart — so the stop
        belongs here rather than in whatever the test happened to assert last.
        """

        for service in self.services:
            await service.close(timeout_seconds=0.05)
            await service.aclose()


_HARNESSES: list["TurnHarness"] = []


@pytest.fixture(autouse=True)
async def no_dangling_turns() -> AsyncIterator[None]:
    """One turn is one task; none of them may outlive the test that started it."""

    yield
    for harness in _HARNESSES:
        await harness.drain()
    _HARNESSES.clear()
    pending = [
        task
        for task in asyncio.all_tasks()
        if not task.done()
        and task.get_name().startswith(("agent-turn-", "agent-turn-notification"))
    ]
    assert pending == [], [task.get_name() for task in pending]


@pytest.fixture
async def no_dangling_tasks() -> AsyncIterator[None]:
    """A turn is a task. A test that leaves one running lies about the next one."""

    yield
    pending = [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith("agent-turn-") and not task.done()
    ]
    assert pending == [], [task.get_name() for task in pending]


__all__ = [
    "AGENT_ID",
    "AUTHOR",
    "DEFAULT_INTERVAL",
    "DIAL_KEY",
    "GRAPH_ID",
    "INSTRUCTIONS",
    "PROJECT",
    "T0",
    "WORKSPACE",
    "BrokenResolver",
    "FakeClock",
    "RecordingPublisher",
    "ScriptedModel",
    "stored_outcome",
    "stored_text",
    "ScriptedResolver",
    "OTHER_WORKSPACE",
    "TurnHarness",
    "access",
    "agent",
    "custom_agent_model",
    "head",
    "no_dangling_turns",
    "other_workspace_access",
    "with_document",
]
