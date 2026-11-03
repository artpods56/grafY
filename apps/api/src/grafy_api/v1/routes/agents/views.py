"""Agent HTTP routes: threads, turns and configuration (ADR 0021, issue #202).

Eleven routes, all of them under one Project and one Graph and addressed to one Agent:

* ``POST   /graphs/{g}/agents/{a}/conversations``                 open a thread
* ``GET    /graphs/{g}/agents/{a}/conversations``                 list this Agent's threads
* ``GET    /graphs/{g}/agents/{a}/conversations/{c}``             read one thread
* ``GET    /graphs/{g}/agents/{a}/conversations/{c}/events``      its stored events
* ``POST   /graphs/{g}/agents/{a}/conversations/{c}/fork``        continue it in a new thread
* ``POST   /graphs/{g}/agents/{a}/conversations/{c}/turns``       send, idempotently
* ``POST   /graphs/{g}/agents/{a}/conversations/{c}/cancel``      stop the turn running now
* ``GET    /graphs/{g}/agents/{a}/conversations/{c}/active-turn`` what is running, so far
* ``GET    /graphs/{g}/agents/{a}/model``                          what it will dial
* ``PUT    /graphs/{g}/agents/{a}/key``                            give it a key of its own
* ``DELETE /graphs/{g}/agents/{a}/key``                            take that key away

Three rules hold on all of them, and each is enforced by an owner rather than by a route
remembering.

**The path is the scope.** A Workspace holds many Projects, a Project many Graphs and a Graph
many Agents, so a conversation id that resolves inside the caller's Workspace is not yet an
answer about *this* Agent: every conversation route reads the stored row and compares its
Project, Graph and Agent with the path, and the two write routes hand the same coordinates to
the runtime, which checks them again against the row it loaded. Anything outside reads as
absent — the same answer another Workspace's thread gets — so no response here confirms where
a thread really lives. A `turn_id` in a body is addressed the same way: a Stop pressed on one
card cannot stop a turn on another.

**The capability the route declares is the one the service re-checks.** Reading a thread is
``view_project``; sending, cancelling, opening and forking are ``start_run``; giving an Agent a
model of its own is ``edit_project``. Opening and forking a thread take ``start_run`` because a
thread exists to be sent to, and a person who may not send should not be able to grow a
Project's history. The declaration matters more than the re-check: below the route a Personal
Access Token's scope is gone, so a route that declared less would let a narrow token do what
only its wider scope permits (`tests/unit/architecture/test_capability_declarations.py`).

**No secret goes back out.** A key is submitted as a `SecretStr`, spent on the seal, and named
by nothing this surface returns, publishes or logs — the same rule the turn runtime holds itself
to in its own failure accounts.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import Response

from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.agents.turns import AgentTurnScope
from grafy_api.v1.routes.agents.dependencies import (
    AgentCollaborationDependency,
    AgentConversationDependency,
    AgentConversationsDependency,
    AgentKeysDependency,
    AgentModelsDependency,
    AgentTurnsDependency,
    agent_on_head,
    graph_on_head,
)
from grafy_api.v1.routes.agents.models import (
    ActiveAgentTurnResponse,
    AgentConversationEventListResponse,
    AgentConversationListResponse,
    AgentConversationResponse,
    AgentKeyResponse,
    AgentModelResponse,
    AgentTurnResponse,
    CancelAgentTurnRequest,
    ForkAgentConversationRequest,
    SendAgentTurnRequest,
    SetAgentKeyRequest,
    StartAgentConversationRequest,
)
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}",
    tags=["agents"],
)


def _scope(project_id: UUID, graph_id: str, agent_id: str) -> AgentTurnScope:
    """What the path addressed, handed down for the runtime to check against what it loaded."""

    return AgentTurnScope(project_id=project_id, graph_id=graph_id, agent_id=agent_id)


@router.post(
    "/graphs/{graph_id}/agents/{agent_id}/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentConversationResponse,
)
async def start_agent_conversation(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    payload: StartAgentConversationRequest,
    conversations: AgentConversationsDependency,
    access: require_workspace_capability(WorkspaceCapability.START_RUN),
) -> AgentConversationResponse:
    """Open a thread with one Agent that is on the canvas right now.

    The Agent has to be there because a thread is addressed to it. Its instructions and model
    are read from the head document when each turn is admitted rather than copied here, so
    editing the card later does not rewrite what this thread is called or what it was told.
    """

    conversation = await conversations.start(
        workspace_id=access.workspace_id,
        project_id=project_id,
        graph_id=graph_id,
        agent_id=agent_id,
        author_user_id=access.actor.user_id,
        title=payload.title,
    )
    return AgentConversationResponse.from_conversation(conversation)


@router.get(
    "/graphs/{graph_id}/agents/{agent_id}/conversations",
    response_model=AgentConversationListResponse,
)
async def list_agent_conversations(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    conversations: AgentConversationsDependency,
    collaboration: AgentCollaborationDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> AgentConversationListResponse:
    """Every thread with one Agent of this Graph, newest first — whoever started them.

    An Agent that has left the canvas still has threads to read: history outlives the card, and
    a person who opened a thread should be able to finish reading it. What the Graph has to
    exist for is the Graph, because this is the surface that lists what is on it.
    """

    head = await collaboration.get_head(
        actor=access.actor, workspace_id=access.workspace_id, project_id=project_id
    )
    graph_on_head(head, graph_id)
    listed = await conversations.list_for_agent(
        workspace_id=access.workspace_id,
        project_id=project_id,
        graph_id=graph_id,
        agent_id=agent_id,
    )
    return AgentConversationListResponse(
        conversations=[
            AgentConversationResponse.from_conversation(item) for item in listed
        ]
    )


@router.get(
    "/graphs/{graph_id}/agents/{agent_id}/conversations/{conversation_id}",
    response_model=AgentConversationResponse,
)
async def get_agent_conversation(
    conversation: AgentConversationDependency,
) -> AgentConversationResponse:
    """One thread the path addresses. The scope check is the route; there is nothing to add."""

    return AgentConversationResponse.from_conversation(conversation)


@router.get(
    "/graphs/{graph_id}/agents/{agent_id}/conversations/{conversation_id}/events",
    response_model=AgentConversationEventListResponse,
)
async def list_agent_conversation_events(
    conversation: AgentConversationDependency,
    conversations: AgentConversationsDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
    after_sequence: Annotated[
        int,
        Query(
            ge=0,
            description=(
                "Skip the events up to and including this conversation sequence. A reader "
                "resumes with the highest sequence it holds, so a resync repeats nothing."
            ),
        ),
    ] = 0,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
) -> AgentConversationEventListResponse:
    """The thread's stored events, oldest first — the authoritative recovery path.

    Room frames are how a thread looks live; this is what makes it right. A delta that was
    dropped, a `agent.event.appended` that arrived after a disconnect and a turn that ended
    while the tab was closed all resolve to reading this route, and `last_sequence` says
    whether the page that came back is the whole thread or stopped at the limit.
    """

    events = await conversations.read_events(
        workspace_id=access.workspace_id,
        conversation_id=conversation.id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return AgentConversationEventListResponse.from_events(
        list(events), conversation_last_sequence=conversation.last_sequence
    )


@router.post(
    "/graphs/{graph_id}/agents/{agent_id}/conversations/{conversation_id}/fork",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentConversationResponse,
)
async def fork_agent_conversation(
    conversation: AgentConversationDependency,
    conversations: AgentConversationsDependency,
    payload: ForkAgentConversationRequest,
    access: require_workspace_capability(WorkspaceCapability.START_RUN),
) -> AgentConversationResponse:
    """Continue this thread from one of its events, in a new thread beside the same Agent.

    "Continue from here" copies; it does not trim. The source keeps going, the copy records the
    conversation and the sequence it was cut at, and both keep the Project, Graph and Agent of
    the source — so a fork cannot move a thread's history to another card by addressing it
    somewhere else. A sequence the source does not have is refused as unprocessable, with the
    source's own `last_sequence` in the response for a client to aim at instead.
    """

    fork = await conversations.fork(
        workspace_id=access.workspace_id,
        conversation_id=conversation.id,
        at_sequence=payload.at_sequence,
        author_user_id=access.actor.user_id,
        title=payload.title,
    )
    return AgentConversationResponse.from_conversation(fork)


@router.post(
    "/graphs/{graph_id}/agents/{agent_id}/conversations/{conversation_id}/turns",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentTurnResponse,
)
async def send_agent_turn(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    conversation: AgentConversationDependency,
    turns: AgentTurnsDependency,
    payload: SendAgentTurnRequest,
    access: require_workspace_capability(WorkspaceCapability.START_RUN),
) -> AgentTurnResponse:
    """Ask this Agent one question, and get its turn's receipt before it has answered.

    The reply does not come back here: it streams on the Project room as ``agent.*`` frames and
    is stored as conversation events, both of which outlive this request. That is what makes
    the response a receipt — the question is durable by the time it is sent, the answer arrives
    whenever the model finishes, and a tab that closes does not stop a turn that has started.

    The send is idempotent by `client_turn_id`: the same id with the same text returns the same
    turn with no second model call and no second event, which is why a retry after a dropped
    response is safe. The same id with different text, and a fresh id against a conversation
    that is already running, are both conflicts rather than surprises.
    """

    turn = await turns.send(
        access=access,
        conversation_id=conversation.id,
        client_turn_id=payload.client_turn_id,
        text=payload.text,
        scope=_scope(project_id, graph_id, agent_id),
    )
    return AgentTurnResponse.from_turn(turn)


@router.post(
    "/graphs/{graph_id}/agents/{agent_id}/conversations/{conversation_id}/cancel",
    response_model=AgentTurnResponse,
)
async def cancel_agent_turn(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    conversation: AgentConversationDependency,
    turns: AgentTurnsDependency,
    access: require_workspace_capability(WorkspaceCapability.START_RUN),
    payload: CancelAgentTurnRequest | None = None,
) -> AgentTurnResponse:
    """Stop this thread's turn. Asking twice, or again after the answer, changes nothing.

    Cancelling is a request rather than a kill: the turn's own task unwinds the run, keeps the
    text that had arrived and writes its ending, so a Stop that races a finishing answer leaves
    one record of how it ended instead of two. A thread with nothing running answers with its
    last turn, which is what a retried Stop was asking for; a `turn_id` that belongs to another
    Project, Graph or Agent is the absence it appears to be.
    """

    turn = await turns.cancel(
        access=access,
        conversation_id=conversation.id,
        turn_id=None if payload is None else payload.turn_id,
        scope=_scope(project_id, graph_id, agent_id),
    )
    return AgentTurnResponse.from_turn(turn)


@router.get(
    "/graphs/{graph_id}/agents/{agent_id}/conversations/{conversation_id}/active-turn",
    response_model=ActiveAgentTurnResponse | None,
)
async def get_active_agent_turn(
    conversation: AgentConversationDependency,
    turns: AgentTurnsDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> ActiveAgentTurnResponse | None:
    """The turn running now and the text it has streamed, or nothing when the thread is idle.

    This exists because streamed text is stored nowhere: a reader that joined mid-turn can read
    the ending from the events, but only the process running the turn knows how far it has got.
    A turn another API owner runs answers with its receipt and no partial, which is the truth
    rather than an empty answer that looks finished.
    """

    snapshot = await turns.active_turn_snapshot(
        access=access, conversation_id=conversation.id
    )
    return None if snapshot is None else ActiveAgentTurnResponse.from_snapshot(snapshot)


@router.get(
    "/graphs/{graph_id}/agents/{agent_id}/model", response_model=AgentModelResponse
)
async def get_agent_model(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    collaboration: AgentCollaborationDependency,
    models: AgentModelsDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
) -> AgentModelResponse:
    """Which model this Agent will dial, and whether the key that needs is in place.

    Never the key: the endpoint, the model name, whether the choice came from the deployment or
    the Agent, and a yes-or-no about the credential is all a configuration surface can honestly
    show — and the whole reason reading it is `view_project` while setting it is `edit_project`.
    """

    head = await collaboration.get_head(
        actor=access.actor, workspace_id=access.workspace_id, project_id=project_id
    )
    agent = agent_on_head(head, graph_id, agent_id)
    described = await models.describe(
        access=access, project_id=project_id, graph_id=graph_id, agent=agent
    )
    return AgentModelResponse.from_description(described)


@router.put("/graphs/{graph_id}/agents/{agent_id}/key", response_model=AgentKeyResponse)
async def set_agent_key(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    keys: AgentKeysDependency,
    payload: SetAgentKeyRequest,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> AgentKeyResponse:
    """Give this Agent a key of its own. What comes back says only that one is there now.

    The plaintext is spent on the seal and appears in no response, no event, no stored row and
    no log line: the key service's failure accounts name the Agent, never the value, and a value
    that is not worth sealing is refused without repeating it. Setting a key twice replaces it,
    which is the reverse door `DELETE` below opens all the way.
    """

    state = await keys.set_key(
        access=access,
        project_id=project_id,
        graph_id=graph_id,
        agent_id=agent_id,
        value=payload.value,
    )
    return AgentKeyResponse.from_state(state)


@router.delete(
    "/graphs/{graph_id}/agents/{agent_id}/key",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_agent_key(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    keys: AgentKeysDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_PROJECT),
) -> Response:
    """Take the Agent's own key away, so a deployment-default Agent needs nothing of its own.

    Clearing does not read what was stored, and it is idempotent: an Agent with no key answers
    the same way whether it ever had one.
    """

    await keys.clear_key(
        access=access,
        project_id=project_id,
        graph_id=graph_id,
        agent_id=agent_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
