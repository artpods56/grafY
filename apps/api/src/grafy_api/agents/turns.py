"""The Agent turn runtime (ADR 0021, issue #202).

One send, one turn, one task. Everything the routes and the room will need about running a
turn goes through here, and four things are deliberately this owner's rather than the
caller's:

* **The task outlives the request.** `send` admits the turn, starts a task this service
  owns, and returns the receipt. A tab that closes, a proxy that times out or a client that
  retries does not stop a model that has already started talking, and the answer lands in
  the conversation for whoever is reading it.
* **Admission is a database fact.** The receipt and the turn's user message are written in
  one transaction, so a send is either fully admitted or not admitted at all, and a
  conversation's busy state is a row another writer cannot miss rather than a flag in this
  process's memory. A repeated send is answered from the receipt: the same id with the same
  text returns the same turn, with no model call and no second event; the same id with
  different text is a conflict rather than a silent replay of a message nobody just sent; a
  fresh id against a conversation that is already running is refused.
* **What a turn was told is fixed when it is accepted.** The Agent's instructions and model
  are snapshotted into the receipt and the history is rebuilt from Grafy's stored events at
  that moment, so an Agent renamed or re-pointed mid-turn cannot rewrite a turn in flight —
  and pydantic-ai messages are never persisted, only derived per turn and thrown away.
* **Text that streamed is worth keeping.** A completed, cancelled, failed and interrupted
  turn all store what arrived, followed by the outcome that says whether it was the whole
  answer. That is what lets the next turn's history be rebuilt from the durable record
  alone, which is the only record that survives a restart.

Reading is authorised by ``view_project`` and sending and cancelling by ``start_run``,
re-checked here on the caller's ``WorkspaceAccess``. The route above must declare the same
capability: a service re-check consults the role only, and a scoped token would otherwise
slip under it.

Cancelling is a request, not a kill. The turn's own task is asked to stop, unwinds the run,
keeps the text that had arrived, writes the terminal outcome and closes the client it
opened. Nothing is cancelled in the middle of a database write, which is why a cancel that
races a finishing answer leaves one record of how it ended rather than two.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic_ai import (
    Agent,
    CancellationToken,
    DeferredToolRequests,
    DeferredToolResults,
    ExternalToolset,
    RunCancelled,
    ToolDefinition,
)
from pydantic_ai.messages import ModelMessage, PartDeltaEvent, PartStartEvent
from pydantic_ai.models import Model
from pydantic_ai.run import AgentRunResultEvent

from grafy_api.agents.history import history_messages
from grafy_api.agents.toolbox import AgentToolbox
from grafy_api.agents.models import (
    AgentModelReader,
    OwnedAgentChatModel,
    ResolvedAgentModel,
)
from grafy_api.agents.publishing import (
    AGENT_TEXT_PARTIAL_INTERVAL_SECONDS,
    AgentConversationNotice,
    AgentTextPartial,
    AgentTextPartialCoalescer,
    AgentTurnPublisher,
    AgentTurnSnapshot,
    NullAgentTurnPublisher,
)
from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    AgentConversationEventPayload,
    AgentConversationTurnOutcome,
    AssistantMessagePayload,
    ConfirmationRequestedPayload,
    ToolCallPayload,
    ToolResultPayload,
    TurnOutcomePayload,
    UserMessagePayload,
)
from grafy_core.domain.agent_turns import AgentTurn, AgentTurnStatus
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.graph_documents import GraphAgent, GraphDocument
from grafy_core.domain.identity import WorkspaceAccess, WorkspaceCapability
from grafy_core.kernel.project import ProjectDocumentError
from grafy_core.ports.agent_turns import (
    AgentTurnAlreadyAdmittedError,
    AgentTurnBusyError,
    AgentTurnUnitOfWorkPort,
)

logger = logging.getLogger(__name__)

type AgentToolboxFactory = Callable[
    [UUID, UUID, str, GraphAgent, GraphDocument], AgentToolbox | None
]
"""``(workspace, project, graph, agent, graph document)`` to the tools the Agent may call.

``None`` or a toolbox with no tools means a turn with no tools, which is every Agent that
has none connected and every deployment that has not wired tools in."""

MAX_AGENT_TURN_ERROR_DETAIL_CHARS = 2_000
"""How much of a failure the durable record and the log line may carry."""

MAX_AGENT_TURN_NOTIFICATIONS_QUEUED = 256
"""How far behind its readers fan-out may fall before frames start being lost.

At the default coalescing interval that is a couple of seconds of one turn's text, or a
hundred turns' start-and-finish tellings: enough for a reconnect, and bounded so a room that
has stopped reading costs a fixed amount of memory instead of as much as the model emits.
"""

MAX_AGENT_TURN_TOOL_CALLS = 10
"""How many tool calls a turn makes before it asks a person to go on.

A model with a tool and a vague question can call it for a long time. The limit is on the
calls a turn has already made, checked before a batch runs: the batch that would pass it is
not run and not stored, a confirmation request is, and the person's reply is the next turn.
"""

SHUTDOWN_STOP_TIMEOUT_SECONDS = 10.0
"""How long an owned turn is asked to stop on its own before it is cancelled."""

INTERRUPTED_DETAIL = "the API owner restarted while this turn was running"
ORPHANED_CANCEL_DETAIL = "cancelled with no turn running in this API owner"

# A turn's status and the outcome event it ends with are the same four words plus
# `running`, which never reaches a conversation: only a claimed terminal turn writes one.
_OUTCOME_EVENTS: dict[AgentTurnStatus, AgentConversationTurnOutcome] = {
    AgentTurnStatus.COMPLETED: AgentConversationTurnOutcome.COMPLETED,
    AgentTurnStatus.CANCELLED: AgentConversationTurnOutcome.CANCELLED,
    AgentTurnStatus.FAILED: AgentConversationTurnOutcome.FAILED,
    AgentTurnStatus.INTERRUPTED: AgentConversationTurnOutcome.INTERRUPTED,
}


class AgentTurnRequestError(ValueError):
    """The send is not something this conversation can be asked to run."""


class AgentTurnConflictError(AgentTurnRequestError):
    """This client turn id was already admitted with different content.

    It names the turn it collided with rather than answering with it: the caller's id is
    not the message that is stored, and pretending otherwise would make a client bug look
    like a successful send.
    """

    def __init__(self, turn_id: UUID) -> None:
        super().__init__(
            f"Client turn {turn_id} was already admitted with a different message"
        )
        self.turn_id = turn_id


class AgentTurnStoppingError(RuntimeError):
    """This API owner is shutting down and will not take a new turn."""


@dataclass(frozen=True, slots=True)
class AgentTurnScope:
    """The Project, Graph and Agent a request addressed its conversation to.

    A Workspace holds many Projects, so the Workspace a receipt was read under answers
    nothing on its own: the conversation the caller's id found also has to sit in the Project
    named in the path, on the Graph named there, and next to the Agent named there. The route
    checks this before it calls down and the runtime checks it again on the row it loaded, so
    the rule is a property of the owner rather than a convention each new caller has to
    remember. Anything outside the scope reads as absent, which is how the rest of the
    tenancy rules answer a guess.
    """

    project_id: UUID
    graph_id: str
    agent_id: str

    def covers(self, scope: "AgentTurnScope") -> bool:
        return (
            self.project_id == scope.project_id
            and self.graph_id == scope.graph_id
            and self.agent_id == scope.agent_id
        )


def redact_agent_turn_error(detail: str, secrets: Sequence[str] = ()) -> str:
    """A failure account that is safe to store in an event, a log line and a response.

    A provider SDK puts the request it made into its exceptions, and an OpenAI-compatible
    request carries the credential in a header. So every account of a failed turn comes
    through here: what this process dialled with is replaced, and what is left is capped.
    An account that names the endpoint without naming the key is still worth reading a week
    later, which is the point of storing one at all.
    """

    text = detail
    for secret in secrets:
        value = secret.strip()
        if len(value) >= 4:
            text = text.replace(value, "[redacted]")
    return (
        text[:MAX_AGENT_TURN_ERROR_DETAIL_CHARS]
        if len(text) > MAX_AGENT_TURN_ERROR_DETAIL_CHARS
        else text
    )


@dataclass(frozen=True, slots=True)
class AgentTurnModel:
    """What the runtime needs from a dialled model, and how to hand it back.

    `close` is optional so a test can hand in a scripted in-process model that owns
    nothing; a model that dials a network always brings one, and every path out of a turn
    calls it.
    """

    chat_model: Model
    close: Callable[[], Awaitable[None]] | None = None

    async def aclose(self) -> None:
        if self.close is not None:
            await self.close()


def resolved_agent_model_turn_model(resolved: ResolvedAgentModel) -> AgentTurnModel:
    """The production wiring: dial the resolved endpoint, and own its client.

    `OwnedAgentChatModel` is the shape that can be closed, so the credential and the
    connection it opened leave with the turn instead of outliving the conversation that
    needed them.
    """

    owned: OwnedAgentChatModel = resolved.build_owned_chat_model()
    return AgentTurnModel(chat_model=owned.chat_model, close=owned.aclose)


@dataclass
class _RunningTurn:
    """One live turn: its identity, the text it has streamed, and the handle that stops it."""

    turn: AgentTurn
    user_text: str
    history: list[ModelMessage]
    model: AgentTurnModel
    partial: AgentTextPartial
    coalescer: AgentTextPartialCoalescer
    message_id: UUID
    token: CancellationToken = field(default_factory=CancellationToken)
    task: asyncio.Task[None] | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    stop_requested: AgentTurnStatus | None = None
    text: list[str] = field(default_factory=list)
    published_chars: int = 0
    secrets: tuple[str, ...] = ()
    toolbox: AgentToolbox | None = None
    tool_calls: int = 0
    tool_work: "asyncio.Future[list[ToolResultPayload]] | None" = None

    @property
    def received_text(self) -> str:
        return "".join(self.text)

    def snapshot(self) -> AgentTurnSnapshot:
        return AgentTurnSnapshot(
            turn=self.turn,
            partial_text=self.received_text,
            partial_offset=self.published_chars,
            partial_message_id=self.message_id,
        )


@dataclass(frozen=True, slots=True)
class _Admission:
    """What one admitted send decided.

    The user message is part of the answer rather than a detail of the transaction: a reader
    of the thread has to be told the question was stored, and `turn_started` on its own looks
    like an answer with nothing behind it.
    """

    turn: AgentTurn
    resolved: ResolvedAgentModel
    history: Sequence[AgentConversationEvent]
    user_message: AgentConversationEvent
    user_text: str
    agent: GraphAgent
    graph_document: GraphDocument


class AgentService:
    """Turns: their durable receipts, their streaming, their ending."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], AgentTurnUnitOfWorkPort],
        models: AgentModelReader,
        publisher: AgentTurnPublisher | None = None,
        turn_model_factory: Callable[[ResolvedAgentModel], AgentTurnModel]
        | None = None,
        partial_interval_seconds: float = AGENT_TEXT_PARTIAL_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        toolbox_factory: AgentToolboxFactory | None = None,
    ) -> None:
        self._toolbox_factory = toolbox_factory
        self._unit_of_work_factory = unit_of_work_factory
        self._models = models
        self._publisher: AgentTurnPublisher = (
            publisher if publisher is not None else NullAgentTurnPublisher()
        )
        self._turn_model_factory = (
            turn_model_factory
            if turn_model_factory is not None
            else resolved_agent_model_turn_model
        )
        self._partial_interval_seconds = partial_interval_seconds
        self._clock = clock
        # Fan-out travels on a queue of its own, in the order the turns produced it, and a
        # bounded one: a room that has stopped reading loses frames and counts them, and is
        # never the reason a turn waits, a receipt goes unwritten or shutdown runs out.
        self._notifications: asyncio.Queue[
            Callable[[AgentTurnPublisher], Awaitable[None]]
        ] = asyncio.Queue(maxsize=MAX_AGENT_TURN_NOTIFICATIONS_QUEUED)
        self._notification_pump: asyncio.Task[None] | None = None
        self._notifications_dropped = 0
        # The live turns of this process, keyed by conversation. The receipt is the rule;
        # this is who is obeying it, and what a cancel, a partial read or a shutdown finds.
        self._active: dict[UUID, _RunningTurn] = {}
        self._stopping = False

    @property
    def running_turn_ids(self) -> tuple[UUID, ...]:
        """The turns this process is running right now. For lifecycle tests and logs."""

        return tuple(entry.turn.id for entry in self._active.values())

    # Send ------------------------------------------------------------------

    async def send(
        self,
        *,
        access: WorkspaceAccess,
        conversation_id: UUID,
        client_turn_id: str,
        text: str,
        scope: AgentTurnScope | None = None,
    ) -> AgentTurn:
        """Admit one turn and run it, or answer with the turn this send already made.

        The conversation names the scope: its row carries the Project, the Graph and the
        Agent, so there is nothing for a caller to get wrong about who will answer and no
        way to address a conversation of another Workspace. A *new* turn does need the Agent
        still on the canvas, because its instructions and model are what the turn is built
        from: history outlives the canvas, a fresh question addressed to a removed Agent does
        not.

        `scope` is what the caller addressed rather than what it hoped for: a conversation
        that turns out to live in another Project of the same Workspace, or under another
        Agent, is answered as the absence the path claims.
        """

        access.require(WorkspaceCapability.START_RUN)
        if not text.strip():
            raise AgentTurnRequestError("An Agent turn needs a message to send")
        if self._stopping:
            raise AgentTurnStoppingError("this API owner is stopping")

        admitted = await self._admit(
            access=access,
            conversation_id=conversation_id,
            client_turn_id=client_turn_id,
            text=text,
            scope=scope,
        )
        if admitted is None:
            # A send this conversation already has. The receipt was read inside `_admit`,
            # which is also where it decided replay from conflict.
            replay = await self._replay(access, conversation_id, client_turn_id, text)
            return replay
        self._start(admitted)
        # The question is durable now, so the thread is told about it: a reader that only
        # saw `turn_started` would be watching an answer arrive for a question it cannot see.
        self._publish(_announce(admitted.turn, admitted.user_message))
        return admitted.turn

    async def _admit(
        self,
        *,
        access: WorkspaceAccess,
        conversation_id: UUID,
        client_turn_id: str,
        text: str,
        scope: AgentTurnScope | None,
    ) -> _Admission | None:
        """Write the receipt and the user message together, or write nothing.

        The conversation row is locked first: it is the row whose sequence the message
        takes, so the lock is what makes "is this conversation busy, and at which sequence"
        one decision instead of two reads with a window between them.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            store = unit_of_work.agent_conversations
            turns = unit_of_work.agent_turns
            conversation = await store.lock(access.workspace_id, conversation_id)
            if conversation is None:
                raise NotFoundError("Agent conversation", str(conversation_id))
            if scope is not None and not scope.covers(
                _conversation_scope(conversation)
            ):
                raise NotFoundError("Agent conversation", str(conversation_id))
            already = await turns.get_by_client_turn_id(
                access.workspace_id, conversation_id, client_turn_id
            )
            if already is not None:
                # Deliberately no model call and no event: a retry is answered from what
                # the first send recorded. `_replay` decides whether it is the same request.
                return None
            active = self._active.get(conversation_id)
            if active is not None:
                raise AgentTurnBusyError(conversation_id, active.turn.id)

            head = await unit_of_work.collaboration.get_head(
                access.workspace_id, conversation.project_id
            )
            if head is None:
                raise NotFoundError("Project", str(conversation.project_id))
            agent = _agent_on_graph(head, conversation)
            history = await store.list_events(
                access.workspace_id, conversation_id, after_sequence=0
            )
            resolved = await self._models.resolve(
                workspace_id=access.workspace_id,
                project_id=conversation.project_id,
                graph_id=conversation.graph_id,
                agent=agent,
            )
            at = datetime.now(UTC)
            turn_id = uuid4()
            event = conversation.event(
                turn_id=turn_id, payload=UserMessagePayload(text=text), at=at
            )
            await store.append(event)
            turn = AgentTurn.admit(
                workspace_id=access.workspace_id,
                project_id=conversation.project_id,
                graph_id=conversation.graph_id,
                agent_id=conversation.agent_id,
                conversation_id=conversation_id,
                client_turn_id=client_turn_id,
                requested_by_user_id=access.actor.user_id,
                user_text=text,
                user_message_sequence=event.sequence,
                instructions=agent.instructions,
                model_source=resolved.source,
                model_name=resolved.model_name,
                turn_id=turn_id,
                at=at,
            )
            try:
                await turns.add(turn)
            except (AgentTurnAlreadyAdmittedError, AgentTurnBusyError):
                # Another send committed inside the window above. This transaction wrote
                # neither receipt nor message, so the loser's answer comes from a fresh
                # read of the winner's, not from a guess here.
                await unit_of_work.rollback()
                return await self._lose_admission_race(
                    access=access,
                    conversation_id=conversation_id,
                    client_turn_id=client_turn_id,
                    text=text,
                )
            await unit_of_work.commit()
            return _Admission(
                turn=turn,
                resolved=resolved,
                history=history,
                user_message=event,
                user_text=text,
                agent=agent,
                graph_document=head.document.get_graph(conversation.graph_id).document,
            )

    async def _lose_admission_race(
        self,
        *,
        access: WorkspaceAccess,
        conversation_id: UUID,
        client_turn_id: str,
        text: str,
    ) -> None:
        raced = await self._receipt_by_client_turn_id(
            access.workspace_id, conversation_id, client_turn_id
        )
        if raced is None:
            # The refusal was the busy rule, not the id: the conversation has a live turn
            # and this send is not it.
            running = await self._running(access.workspace_id, conversation_id)
            raise AgentTurnBusyError(conversation_id, running.id if running else None)
        if not raced.matches_request(user_text=text):
            raise AgentTurnConflictError(raced.id)
        return None

    async def _replay(
        self,
        access: WorkspaceAccess,
        conversation_id: UUID,
        client_turn_id: str,
        text: str,
    ) -> AgentTurn:
        already = await self._receipt_by_client_turn_id(
            access.workspace_id, conversation_id, client_turn_id
        )
        if already is None:
            raise NotFoundError("Agent turn", f"{client_turn_id} of {conversation_id}")
        if not already.matches_request(user_text=text):
            raise AgentTurnConflictError(already.id)
        if already.is_running and not any(
            entry.turn.id == already.id for entry in self._active.values()
        ):
            # A receipt that says running with nothing running it here: either this owner
            # restarted over it, or another owner holds it. Both are worth a log line,
            # because the send that follows will be refused by the busy rule.
            logger.warning(
                "agent_turn_receipt_running_without_task workspace_id=%s "
                "conversation_id=%s turn_id=%s",
                access.workspace_id,
                conversation_id,
                already.id,
            )
        return already

    def _start(self, admission: _Admission) -> None:
        """Hand an admitted turn to a task this service owns until it ends."""

        turn = admission.turn
        message_id = uuid4()
        partial = AgentTextPartial(
            workspace_id=turn.workspace_id,
            project_id=turn.project_id,
            graph_id=turn.graph_id,
            agent_id=turn.agent_id,
            conversation_id=turn.conversation_id,
            turn_id=turn.id,
            message_id=message_id,
            offset=0,
            text="",
        )
        entry = _RunningTurn(
            turn=turn,
            user_text=admission.user_text,
            history=history_messages(list(admission.history)),
            model=self._turn_model_factory(admission.resolved),
            partial=partial,
            coalescer=AgentTextPartialCoalescer(
                publish=self._publish_partial,
                interval_seconds=self._partial_interval_seconds,
                clock=self._clock,
            ),
            message_id=message_id,
            secrets=_dial_secrets(admission.resolved),
            toolbox=self._toolbox_for(turn, admission),
        )
        self._active[turn.conversation_id] = entry
        entry.task = asyncio.create_task(self._run(entry), name=f"agent-turn-{turn.id}")
        entry.task.add_done_callback(lambda _task: self._forget(turn, entry))
        self._publish(lambda publisher: publisher.turn_started(turn))

    def _toolbox_for(
        self, turn: AgentTurn, admission: _Admission
    ) -> AgentToolbox | None:
        """The tools this turn may call, fixed when it starts like its instructions are."""

        if self._toolbox_factory is None or not admission.agent.tools:
            return None
        toolbox = self._toolbox_factory(
            turn.workspace_id,
            turn.project_id,
            turn.graph_id,
            admission.agent,
            admission.graph_document,
        )
        return toolbox if toolbox is not None and toolbox.tools else None

    def _forget(self, turn: AgentTurn, entry: _RunningTurn) -> None:
        """Let go of a finished turn, so its conversation can be sent to again."""

        if self._active.get(turn.conversation_id) is entry:
            del self._active[turn.conversation_id]
        entry.done.set()

    # The turn task ---------------------------------------------------------

    async def _run(self, entry: _RunningTurn) -> None:
        """Stream one turn, then store what it produced and how it ended.

        A cancel does not cancel this task, so the terminal write happens in a task that
        can finish the database work it started. Any other failure ends the same way: keep
        the text that arrived, record the outcome, close the client. A turn that fails
        before any text exists writes only the outcome — an empty assistant message is not
        history, and the payload union would be right to refuse one.
        """

        status = AgentTurnStatus.COMPLETED
        detail: str | None = None
        final_text: str | None = None
        try:
            final_text = await self._stream(entry)
        except asyncio.CancelledError:
            # Somebody cancelled the task itself: a shutdown that ran out of patience. What
            # streamed is still worth keeping, and the turn did not finish.
            status = entry.stop_requested or AgentTurnStatus.INTERRUPTED
            await self._finish(
                entry, status, text=entry.received_text, detail=INTERRUPTED_DETAIL
            )
            logger.warning("agent_turn_task_cancelled turn_id=%s", entry.turn.id)
            raise
        except RunCancelled:
            status = entry.stop_requested or AgentTurnStatus.CANCELLED
            if status is AgentTurnStatus.INTERRUPTED:
                # The owner stopped this one, not the person in the thread, and the receipt
                # says so: the same account a restart leaves behind, whichever way the stop
                # was delivered.
                detail = INTERRUPTED_DETAIL
        except Exception as error:  # noqa: BLE001 - any model failure ends the turn failed
            status = AgentTurnStatus.FAILED
            detail = redact_agent_turn_error(
                f"{type(error).__name__}: {error}", entry.secrets
            )
            # The class is the log line, never the message: an exception a provider SDK
            # raises can carry the credential this process dialled with.
            logger.warning(
                "agent_turn_model_failed turn_id=%s conversation_id=%s error_class=%s",
                entry.turn.id,
                entry.turn.conversation_id,
                type(error).__name__,
            )

        if status is AgentTurnStatus.COMPLETED and final_text:
            # The run's own result is authoritative over the accumulated deltas: it is what
            # the SDK says the message was, and a provider that ends a response without a
            # closing chunk would otherwise store less than the model sent.
            entry.text = [final_text]

        await self._finish(entry, status, text=entry.received_text, detail=detail)

    async def _stream(self, entry: _RunningTurn) -> str:
        """The turn's pydantic-ai runs: the model speaks, may call tools, and speaks again.

        With no tools this is one run whose text goes to the coalescer as it arrives. With
        tools the model's calls end a run (they are external: the run stops at them), the
        calls are executed through the kernel and stored, and a new run resumes with the
        results, until the model answers in text, the turn has made as many calls as it may
        unprompted, or it is stopped. What the model said before calling is stored as its
        own message, ahead of its calls, so the conversation reads in the order it happened.
        """

        toolbox = entry.toolbox
        agent: Agent[None, str | DeferredToolRequests] = Agent(
            entry.model.chat_model,
            # The instructions are the receipt's snapshot, so the canvas can move and this
            # turn still says what it was told.
            instructions=entry.turn.instructions or None,
            toolsets=[ExternalToolset(_definitions(toolbox))] if toolbox else None,
            output_type=[str, DeferredToolRequests] if toolbox else str,
        )
        prompt: str | None = entry.user_text
        history = entry.history
        deferred: DeferredToolResults | None = None
        while True:
            result: str | DeferredToolRequests = ""
            messages: list[ModelMessage] = history
            async with agent.run_stream_events(
                prompt,
                message_history=history,
                deferred_tool_results=deferred,
                cancellation_token=entry.token,
            ) as events:
                async for event in events:
                    if isinstance(event, PartStartEvent):
                        # The first characters of a message arrive here rather than as a
                        # delta whenever a provider sends a complete part before streaming
                        # the rest. A reader that only followed deltas would start every
                        # answer one chunk late, and so would the stored message.
                        part = event.part
                        if part.part_kind != "text":
                            continue
                        await self._accept(
                            entry, _part_text(getattr(part, "content", ""))
                        )
                    elif isinstance(event, PartDeltaEvent):
                        await self._accept(
                            entry, _part_text(getattr(event.delta, "content_delta", ""))
                        )
                    elif isinstance(event, AgentRunResultEvent):
                        # The run's own answer, which the SDK says in full: the accumulated
                        # deltas are what the readers saw, this is what the message was.
                        result = event.result.output
                        messages = event.result.all_messages()
            if not isinstance(result, DeferredToolRequests):
                return result
            if toolbox is None:
                raise RuntimeError("the model called a tool this turn was not given")
            deferred = await self._call_tools(entry, toolbox, result)
            if deferred is None:
                return ""
            prompt, history = None, messages

    async def _call_tools(
        self,
        entry: _RunningTurn,
        toolbox: AgentToolbox,
        requests: DeferredToolRequests,
    ) -> DeferredToolResults | None:
        """Run the calls one response asked for, and answer them. ``None`` ends the turn.

        What was said so far and the calls themselves are stored before anything runs, so a
        turn that dies mid-call leaves the call on record rather than nothing. The batch
        that would take the turn past its limit is neither run nor stored: the confirmation
        request stands in for it, and the person's reply starts the next turn from the
        results already there.
        """

        calls = [
            ToolCallPayload(
                call_id=call.tool_call_id,
                tool_id=(
                    prepared.link.id
                    if (prepared := toolbox.tool(call.tool_name)) is not None
                    else call.tool_name
                ),
                tool_name=call.tool_name,
                arguments=call.args_as_dict(),
            )
            for call in requests.calls
        ]
        said = await self._take_segment(entry)
        if entry.tool_calls + len(calls) > MAX_AGENT_TURN_TOOL_CALLS:
            await self._append_events(
                entry,
                [
                    *said,
                    ConfirmationRequestedPayload(
                        tool_calls=entry.tool_calls, limit=MAX_AGENT_TURN_TOOL_CALLS
                    ),
                ],
            )
            return None
        await self._append_events(entry, [*said, *calls])
        entry.tool_calls += len(calls)
        entry.tool_work = asyncio.gather(*(toolbox.execute(call) for call in calls))
        try:
            results: list[ToolResultPayload] = await entry.tool_work
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if (
                entry.stop_requested is not None
                and task is not None
                and task.cancelling() == 0
            ):
                # The stop came through `_request_stop`, which withdrew the calls, and not
                # from somebody cancelling this task: it is a stop, not a shutdown.
                raise RunCancelled("the turn was stopped during a tool call") from None
            raise
        finally:
            entry.tool_work = None
        await self._append_events(entry, results)
        return DeferredToolResults(
            calls={
                result.call_id: (
                    result.model_view
                    if result.ok
                    else f"The tool call failed: {result.error or 'no reason given'}"
                )
                for result in results
            }
        )

    async def _take_segment(
        self, entry: _RunningTurn
    ) -> list[AgentConversationEventPayload]:
        """Close the text the model has said so far, as a message of its own.

        The readers are told the last of the stream, the stored message will replace it, and
        the next stretch of text starts a message of its own, so a turn that talks, calls and
        talks again is three things in the conversation and not one run-on paragraph.
        """

        await self._publish_final(entry)
        text = entry.received_text
        entry.text = []
        entry.published_chars = 0
        message_id = uuid4()
        entry.message_id = message_id
        entry.partial = replace(entry.partial, message_id=message_id, offset=0, text="")
        entry.coalescer = AgentTextPartialCoalescer(
            publish=self._publish_partial,
            interval_seconds=self._partial_interval_seconds,
            clock=self._clock,
        )
        return [AssistantMessagePayload(text=text)] if text else []

    async def _append_events(
        self,
        entry: _RunningTurn,
        payloads: Sequence[AgentConversationEventPayload],
    ) -> None:
        """Append events to the conversation while the turn is still the one running.

        The turn row is read in the same transaction: a turn that was cancelled has had its
        ending written already, and an event appended behind its ending would read as
        something that happened after the turn was over.
        """

        if not payloads:
            return
        turn = entry.turn
        at = datetime.now(UTC)
        appended: list[AgentConversationEvent] = []
        async with self._unit_of_work_factory() as unit_of_work:
            current = await unit_of_work.agent_turns.get(turn.workspace_id, turn.id)
            if current is None or current.status is not AgentTurnStatus.RUNNING:
                await unit_of_work.rollback()
                return
            store = unit_of_work.agent_conversations
            conversation = await store.lock(turn.workspace_id, turn.conversation_id)
            if conversation is None:
                await unit_of_work.rollback()
                return
            for payload in payloads:
                event = conversation.event(turn_id=turn.id, payload=payload, at=at)
                await store.append(event)
                appended.append(event)
                conversation = conversation.appended(at=at)
            await unit_of_work.commit()
        for event in appended:
            self._publish(_announce(turn, event))

    async def _accept(self, entry: _RunningTurn, text: str) -> None:
        if not text:
            return
        entry.text.append(text)
        await entry.coalescer.offer(entry.partial, text)

    # Ending a turn ---------------------------------------------------------

    async def _finish(
        self,
        entry: _RunningTurn,
        status: AgentTurnStatus,
        *,
        text: str,
        detail: str | None,
    ) -> None:
        """Write one turn's ending, once, whoever else is trying to end it.

        The order is deliberate. The tail of the stream is published before the durable
        event exists, so a reader sees the last text and then the message, never a complete
        message replaced by a partial one. Then the receipt's conditional move out of
        ``running`` picks the single writer of the ending, and only that writer appends.
        The model client goes back on every path, including the one where the database
        write itself failed.
        """

        try:
            await self._publish_final(entry)
            recorded = await self._record_outcome(
                entry.turn, status, text=text, detail=detail
            )
        finally:
            with suppress(Exception):
                await entry.model.aclose()
        if recorded is None:
            logger.info(
                "agent_turn_outcome_already_recorded turn_id=%s attempted_status=%s",
                entry.turn.id,
                status.value,
            )
            return
        wrote, events = recorded
        # The stored answer and its ending are told before the turn is called finished, so a
        # reader that stops on `turn_finished` has been told everything the conversation now
        # holds. The buffered text went out ahead of both, in `_publish_final`.
        for event in events:
            self._publish(_announce(wrote, event))
        self._publish(
            lambda publisher: publisher.turn_finished(
                wrote,
                outcome=_OUTCOME_EVENTS[wrote.status],
                detail=wrote.outcome_detail,
            )
        )

    async def _publish_final(self, entry: _RunningTurn) -> None:
        """Flush what is buffered, for the last time. A lost frame loses only the frame."""

        try:
            await entry.coalescer.close(entry.partial)
        except Exception:
            logger.exception(
                "agent_turn_partial_flush_failed turn_id=%s", entry.turn.id
            )
        entry.published_chars = entry.coalescer.published_chars

    async def _record_outcome(
        self,
        turn: AgentTurn,
        status: AgentTurnStatus,
        *,
        text: str,
        detail: str | None,
    ) -> tuple[AgentTurn, list[AgentConversationEvent]] | None:
        """Claim the turn's terminal state and append its events in one transaction.

        The claim is the first write, so a turn someone else already finished costs this
        transaction nothing at all rather than a rolled-back pair of events. The events are
        written against the locked conversation, so the sequence they take is the one that
        row is waiting for even if another turn was admitted in the meantime. The appended
        events come back with the claim because the room is told about each one, in order,
        once the transaction that wrote them has committed.
        """

        at = datetime.now(UTC)
        appended: list[AgentConversationEvent] = []
        async with self._unit_of_work_factory() as unit_of_work:
            claimed = await unit_of_work.agent_turns.finish(
                turn.workspace_id, turn.id, status=status, at=at, detail=detail
            )
            if claimed is None:
                await unit_of_work.rollback()
                return None
            store = unit_of_work.agent_conversations
            conversation = await store.lock(turn.workspace_id, turn.conversation_id)
            if conversation is not None:
                if text:
                    event = conversation.event(
                        turn_id=turn.id,
                        payload=AssistantMessagePayload(text=text),
                        at=at,
                    )
                    await store.append(event)
                    appended.append(event)
                    conversation = conversation.appended(at=at)
                outcome_event = conversation.event(
                    turn_id=turn.id,
                    payload=TurnOutcomePayload(
                        outcome=_OUTCOME_EVENTS[status], detail=detail
                    ),
                    at=at,
                )
                await store.append(outcome_event)
                appended.append(outcome_event)
            await unit_of_work.commit()
        return claimed, appended

    # Cancel ----------------------------------------------------------------

    async def cancel(
        self,
        *,
        access: WorkspaceAccess,
        conversation_id: UUID,
        turn_id: UUID | None = None,
        scope: AgentTurnScope | None = None,
    ) -> AgentTurn:
        """Stop a turn, and answer the same way however often it is asked.

        With no `turn_id` this stops whatever the conversation is running, which is what a
        Stop button means. A turn this process runs is asked to stop and awaited, so the
        caller gets the record the turn wrote itself, text included. A turn that is already
        terminal is returned untouched, which is what makes a button pressed twice, or a
        retry after a dropped response, harmless. A receipt still marked running with
        nothing running it here is an orphan of an earlier owner, and this call is the one
        allowed to close it: leaving it running would hold the conversation busy with
        nothing left to stop.

        `scope` is the caller's address, not a hint: a `turn_id` that belongs to another
        Project, Graph or Agent is refused as the absence it is, because a Workspace holds
        many Projects and a Stop pressed on one card must not stop a turn on another.
        """

        access.require(WorkspaceCapability.START_RUN)
        turn = (
            await self._receipt(access.workspace_id, turn_id)
            if turn_id is not None
            else await self._running(access.workspace_id, conversation_id)
        )
        if turn is None:
            # Nothing is running any more. A Stop pressed a second time, or a retry whose
            # first answer was lost on the way back, lands here - and it means the ending
            # the first press already produced, so answer with what the conversation last
            # did instead of refusing, and say "there is nothing here" only when that too
            # would be a lie.
            turn = await self._latest(access.workspace_id, conversation_id)
            if turn is None:
                raise NotFoundError("Agent turn for conversation", str(conversation_id))
        elif turn.conversation_id != conversation_id:
            # A Stop sent to one thread cannot stop another's turn, and the ids are the only
            # thing a body carries: the receipt has to belong to the conversation in the path
            # before its conversation's capability means anything about it.
            raise NotFoundError("Agent turn", str(turn.id))
        if scope is not None and not scope.covers(_turn_scope(turn)):
            raise NotFoundError("Agent turn", str(turn.id))
        if not turn.is_running:
            return turn
        entry = self._active.get(turn.conversation_id)
        if entry is not None and entry.turn.id == turn.id:
            self._request_stop(entry, AgentTurnStatus.CANCELLED)
            await entry.done.wait()
            finished = await self._receipt(access.workspace_id, turn.id)
            if finished is not None:
                return finished
            return turn.finished(
                status=AgentTurnStatus.CANCELLED, at=datetime.now(UTC), detail=None
            )
        return await self._close_orphan(
            turn, AgentTurnStatus.CANCELLED, detail=ORPHANED_CANCEL_DETAIL
        )

    def _request_stop(self, entry: _RunningTurn, status: AgentTurnStatus) -> None:
        """Ask a live turn to end. Idempotent, and the first request names the ending.

        A turn the person cancelled should not be rewritten as an interruption because the
        server also happened to stop while it was going, so a later request only re-issues
        the cancellation and leaves the recorded status alone.
        """

        if entry.stop_requested is None:
            entry.stop_requested = status
        entry.token.cancel()
        if entry.tool_work is not None and not entry.tool_work.done():
            # A tool call in flight is the turn's work too: withdrawing it is what lets the
            # kernel drop a computation nobody else wants.
            entry.tool_work.cancel()

    async def _close_orphan(
        self, turn: AgentTurn, status: AgentTurnStatus, *, detail: str
    ) -> AgentTurn:
        """End a receipt no task in this process is behind."""

        at = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            claimed = await unit_of_work.agent_turns.finish(
                turn.workspace_id, turn.id, status=status, at=at, detail=detail
            )
            if claimed is not None:
                store = unit_of_work.agent_conversations
                conversation = await store.lock(turn.workspace_id, turn.conversation_id)
                if conversation is not None:
                    await store.append(
                        conversation.event(
                            turn_id=turn.id,
                            payload=TurnOutcomePayload(
                                outcome=_OUTCOME_EVENTS[status], detail=detail
                            ),
                            at=at,
                        )
                    )
            await unit_of_work.commit()
        if claimed is None:
            raced = await self._receipt(turn.workspace_id, turn.id)
            return raced or turn
        self._publish(
            lambda publisher: publisher.turn_finished(
                claimed,
                outcome=_OUTCOME_EVENTS[claimed.status],
                detail=claimed.outcome_detail,
            )
        )
        return claimed

    # Reading ---------------------------------------------------------------

    async def get_turn(self, *, access: WorkspaceAccess, turn_id: UUID) -> AgentTurn:
        """One turn's receipt, for whoever may read the conversation it belongs to."""

        access.require(WorkspaceCapability.VIEW_PROJECT)
        turn = await self._receipt(access.workspace_id, turn_id)
        if turn is None:
            raise NotFoundError("Agent turn", str(turn_id))
        return turn

    async def list_turns(
        self,
        *,
        access: WorkspaceAccess,
        conversation_id: UUID,
        limit: int | None = None,
    ) -> list[AgentTurn]:
        """This conversation's sends, newest first — the receipts behind the events."""

        access.require(WorkspaceCapability.VIEW_PROJECT)
        async with self._unit_of_work_factory() as unit_of_work:
            store = unit_of_work.agent_conversations
            if await store.get(access.workspace_id, conversation_id) is None:
                raise NotFoundError("Agent conversation", str(conversation_id))
            return await unit_of_work.agent_turns.list_for_conversation(
                access.workspace_id, conversation_id, limit=limit
            )

    async def wait_for_turn(
        self, *, access: WorkspaceAccess, conversation_id: UUID
    ) -> AgentTurn:
        """Wait for this conversation's turn here to end, and return its receipt.

        Whoever must not proceed until a turn is over — a shutdown sequence, an import that
        wants the answer in the thread before it continues — asks for this instead of reading
        the service's bookkeeping. A conversation with nothing running here is answered from
        the durable receipt, which by then is all there is and all there needs to be.
        """

        access.require(WorkspaceCapability.VIEW_PROJECT)
        entry = self._active.get(conversation_id)
        if entry is not None:
            await entry.done.wait()
        still_running = await self._running(access.workspace_id, conversation_id)
        if still_running is not None:
            return still_running
        async with self._unit_of_work_factory() as unit_of_work:
            store = unit_of_work.agent_conversations
            if await store.get(access.workspace_id, conversation_id) is None:
                raise NotFoundError("Agent conversation", str(conversation_id))
            turns = await unit_of_work.agent_turns.list_for_conversation(
                access.workspace_id, conversation_id, limit=1
            )
        if not turns:
            raise NotFoundError("Agent turn of conversation", str(conversation_id))
        return turns[0]

    async def active_turn_snapshot(
        self, *, access: WorkspaceAccess, conversation_id: UUID
    ) -> AgentTurnSnapshot | None:
        """The turn running now, with the text streamed so far. Nothing when idle.

        This is what a reader who joined mid-turn asks for. The durable events say what a
        turn ended with; this says what it has said so far, and whose message id the
        offsets belong to. A turn another API owner runs has no in-flight text to show, so
        the receipt is answered without one rather than with an empty answer that looks
        finished.
        """

        access.require(WorkspaceCapability.VIEW_PROJECT)
        entry = self._active.get(conversation_id)
        if entry is not None:
            return entry.snapshot()
        async with self._unit_of_work_factory() as unit_of_work:
            if (
                await unit_of_work.agent_conversations.get(
                    access.workspace_id, conversation_id
                )
            ) is None:
                raise NotFoundError("Agent conversation", str(conversation_id))
            running = await unit_of_work.agent_turns.running_for_conversation(
                access.workspace_id, conversation_id
            )
        return None if running is None else AgentTurnSnapshot(turn=running)

    # Recovery and shutdown -------------------------------------------------

    async def recover_after_restart(self) -> list[AgentTurn]:
        """Mark every turn this database still believes is running interrupted.

        The task that streamed a turn died with the process that owned it and its buffered
        text died with the task, so the record is the user message — committed at admission,
        which is why admission writes it durably — plus the outcome appended here. The
        conditional claim makes that happen exactly once per turn however often recovery
        runs, and moving the row out of ``running`` is what releases the conversation for
        the next send, which is the whole reason a restart is survivable rather than a
        conversation permanently stuck busy.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            running = await unit_of_work.agent_turns.list_running()
            # Read only. Each turn's ending is its own transaction below, so one turn that
            # fails to be written does not take the others' interruptions back with it.
            await unit_of_work.rollback()
        interrupted: list[AgentTurn] = []
        for turn in running:
            claimed = await self._close_orphan(
                turn, AgentTurnStatus.INTERRUPTED, detail=INTERRUPTED_DETAIL
            )
            if claimed.status is AgentTurnStatus.INTERRUPTED:
                interrupted.append(claimed)
        if interrupted:
            logger.info(
                "interrupted_agent_turns count=%s",
                [turn.id for turn in interrupted],
            )
        return interrupted

    async def close(
        self, *, timeout_seconds: float = SHUTDOWN_STOP_TIMEOUT_SECONDS
    ) -> None:
        """Stop owning every turn, and wait for the ones that were running.

        Ask, wait, then insist. A task cancelled out of a database write can abandon the
        connection it was holding, which is how a restart becomes a hang; so each turn is
        first asked to stop where it stands and writes its own ending, and only a task still
        alive after the deadline is cancelled, and named in the log. The clients are the
        turns' own to close, and each of them closes its client on the way out — including
        a turn that ends because this deadline did.
        """

        self._stopping = True
        entries = list(self._active.values())
        self._active.clear()
        for entry in entries:
            self._request_stop(entry, AgentTurnStatus.INTERRUPTED)
        tasks = [entry.task for entry in entries if entry.task is not None]
        pending: set[asyncio.Task[None]] = set()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        # Whatever those turns had to tell the room is still this owner's to deliver, and a
        # wedged subscriber must not be the reason shutdown runs out.
        await self.wait_for_notifications(timeout_seconds=timeout_seconds)
        await self._stop_notification_pump()
        if not pending:
            return
        for task in pending:
            logger.warning(
                "agent_turn_close_timeout task=%s deadline_seconds=%s",
                task.get_name(),
                timeout_seconds,
            )
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _stop_notification_pump(self) -> None:
        """Stop the fan-out task, once what was queued has gone or has been given up on."""

        pump = self._notification_pump
        self._notification_pump = None
        if pump is None or pump.done():
            return
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)

    async def aclose(self) -> None:
        """Give up on this service: stop the fan-out task, drop what nobody delivered.

        Whoever is finished with an `AgentService` for good — a test that is finished with
        it, or a shutdown that has already stopped its turns — says so here, so nothing is
        left waiting on a room that will not be read again.
        """

        await self._stop_notification_pump()
        while True:
            try:
                self._notifications.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._notifications.task_done()

    # Internals -------------------------------------------------------------

    async def _receipt(self, workspace_id: UUID, turn_id: UUID) -> AgentTurn | None:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_turns.get(workspace_id, turn_id)

    async def _receipt_by_client_turn_id(
        self, workspace_id: UUID, conversation_id: UUID, client_turn_id: str
    ) -> AgentTurn | None:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_turns.get_by_client_turn_id(
                workspace_id, conversation_id, client_turn_id
            )

    async def _running(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentTurn | None:
        entry = self._active.get(conversation_id)
        if entry is not None:
            return entry.turn
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_turns.running_for_conversation(
                workspace_id, conversation_id
            )

    async def _latest(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentTurn | None:
        """The conversation's most recent turn, running or finished, if it has one."""

        async with self._unit_of_work_factory() as unit_of_work:
            turns = await unit_of_work.agent_turns.list_for_conversation(
                workspace_id, conversation_id, limit=1
            )
        return turns[0] if turns else None

    async def _publish_partial(self, partial: AgentTextPartial) -> None:
        entry = self._active.get(partial.conversation_id)
        if entry is not None:
            entry.published_chars = partial.next_offset
        self._publish(lambda publisher: publisher.text_partial(partial))

    async def wait_for_notifications(self, *, timeout_seconds: float = 5.0) -> None:
        """Wait for the fan-out this service has queued to land.

        Nothing about a turn waits on its reader: the receipt and the events are the facts,
        and a partial frame or a start-or-finish telling is only what someone sees. A reader
        that must know the telling has happened - a test, or a shutdown that would like the
        room caught up - says so here, with a deadline, because "eventually" is not a
        promise anyone can keep when the subscriber is wedged.
        """

        try:
            await asyncio.wait_for(self._notifications.join(), timeout_seconds)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning(
                "agent_turn_notifications_undelivered queued=%s dropped=%s",
                self._notifications.qsize(),
                self._notifications_dropped,
            )

    def _publish(self, notify: Callable[[AgentTurnPublisher], Awaitable[None]]) -> None:
        """Queue one telling, in order, behind everything this service has already queued.

        The notification is never a turn's fact: the receipt and the events are, and a
        publisher that raises, blocks or is not there at all changes what a reader sees and
        not what happened. So the queue is bounded and the overflow is dropped: backpressure
        that reached the turn would be the worse bug, and a reader who joins late reads the
        durable events and the in-flight snapshot rather than a frame nobody kept.
        """

        try:
            self._notifications.put_nowait(notify)
        except asyncio.QueueFull:
            self._notifications_dropped += 1
            logger.warning(
                "agent_turn_notification_dropped queued=%s dropped=%s",
                self._notifications.qsize(),
                self._notifications_dropped,
            )
            return
        if self._notification_pump is None or self._notification_pump.done():
            self._notification_pump = asyncio.create_task(
                self._deliver_notifications(), name="agent-turn-notifications"
            )

    async def _deliver_notifications(self) -> None:
        while True:
            notify = await self._notifications.get()
            try:
                await notify(self._publisher)
            except Exception:
                # A subscriber that fails loses its telling and nothing else: the next one
                # goes out, the turn keeps running, and the durable record is unaffected.
                logger.exception("agent_turn_notification_failed")
            finally:
                self._notifications.task_done()


def _announce(
    turn: AgentTurn, event: AgentConversationEvent
) -> Callable[[AgentTurnPublisher], Awaitable[None]]:
    """One queued telling that a conversation grew by one stored event.

    The notice is built here instead of at delivery, and the notification closes over it
    rather than over a loop variable: a turn appends its answer and its ending back to back,
    and a reader told about the same sequence twice would conclude the other one never
    landed. The room it reaches is the turn's, which is the scope the conversation was read
    under in the first place.
    """

    notice = AgentConversationNotice(
        workspace_id=turn.workspace_id,
        project_id=turn.project_id,
        graph_id=turn.graph_id,
        agent_id=turn.agent_id,
        event=event,
    )

    async def notify(publisher: AgentTurnPublisher) -> None:
        await publisher.event_appended(notice)

    return notify


def _conversation_scope(conversation: AgentConversation) -> AgentTurnScope:
    return AgentTurnScope(
        project_id=conversation.project_id,
        graph_id=conversation.graph_id,
        agent_id=conversation.agent_id,
    )


def _turn_scope(turn: AgentTurn) -> AgentTurnScope:
    return AgentTurnScope(
        project_id=turn.project_id,
        graph_id=turn.graph_id,
        agent_id=turn.agent_id,
    )


def _agent_on_graph(head: ProjectHead, conversation: AgentConversation) -> GraphAgent:
    try:
        graph = head.document.get_graph(conversation.graph_id)
    except ProjectDocumentError as exc:
        raise NotFoundError("Graph", conversation.graph_id) from exc
    agent = next(
        (agent for agent in graph.document.agents if agent.id == conversation.agent_id),
        None,
    )
    if agent is None:
        raise NotFoundError("Agent", conversation.agent_id)
    return agent


def _definitions(toolbox: AgentToolbox | None) -> list[ToolDefinition]:
    """The tools a model is shown: external, so the run stops at a call and Grafy runs it."""

    if toolbox is None:
        return []
    return [
        ToolDefinition(
            name=tool.link.name,
            description=tool.description,
            parameters_json_schema=dict(tool.json_schema),
            kind="external",
        )
        for tool in toolbox.tools
    ]


def _part_text(value: object) -> str:
    """The characters a streamed part carries, when it carries characters.

    A content delta is a string for a text part and a structure for the multimodal and
    thinking parts this runtime does not store yet, so anything that is not text contributes
    nothing here rather than being coerced into the message.
    """

    return value if isinstance(value, str) else ""


def _dial_secrets(resolved: ResolvedAgentModel) -> tuple[str, ...]:
    """What must never appear in a failure account, named so the redaction has a list."""

    return (resolved.api_key.get_secret_value(),)


__all__ = [
    "INTERRUPTED_DETAIL",
    "MAX_AGENT_TURN_ERROR_DETAIL_CHARS",
    "AgentService",
    "AgentTurnConflictError",
    "AgentTurnModel",
    "AgentTurnRequestError",
    "AgentTurnScope",
    "AgentTurnStoppingError",
    "redact_agent_turn_error",
    "resolved_agent_model_turn_model",
]
