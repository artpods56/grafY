"""Talk to an Agent that lives on a canvas (ADR 0021).

An Agent answers in conversations; each message starts a turn that streams events
(text, tool calls of the Graph's nodes, results). These tools send a message and
read the events back, the way the Agent's chat panel does.
"""

import asyncio
from typing import Annotated, Any, Final
from uuid import UUID

from grafy_client import AgentConversationEvents, GrafyClient
from grafy_core.domain.agent_turns import AgentTurnStatus
from pydantic import Field

from grafy_api.mcp.context import EDIT, IDEMPOTENT_EDIT, READ, dump, grafy, tool

_POLL_SECONDS: Final = 0.5
_MAX_WAIT_SECONDS: Final = 300.0


async def list_agent_conversations(
    project_id: UUID, graph_id: str, agent_id: str
) -> list[dict[str, Any]]:
    """An Agent's conversations, newest first."""
    async with grafy() as (client, workspace_id):
        conversations = await client.agents.list_conversations(
            workspace_id, project_id, graph_id=graph_id, agent_id=agent_id
        )
    return [dump(conversation) for conversation in conversations]


async def _wait_for_turn(
    client: GrafyClient,
    workspace_id: UUID,
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    conversation_id: UUID,
    timeout: float,
) -> bool:
    """Poll until no turn is active or the timeout passes; True when finished."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        active = await client.agents.active_turn(
            workspace_id,
            project_id,
            graph_id=graph_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )
        if active is None or active.turn.status is not AgentTurnStatus.RUNNING:
            return True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(_POLL_SECONDS, remaining))


def _events(events: AgentConversationEvents) -> dict[str, Any]:
    return {
        "events": [
            {"sequence": event.sequence, **dump(event)["payload"]}
            for event in events.events
        ],
        "next_sequence": events.next_sequence,
        "last_sequence": events.last_sequence,
    }


async def send_agent_message(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    text: Annotated[str, Field(min_length=1)],
    conversation_id: Annotated[
        UUID | None,
        Field(description="Continue this conversation; default: start a new one"),
    ] = None,
    wait_seconds: Annotated[
        float,
        Field(ge=0, le=_MAX_WAIT_SECONDS, description="0 returns at once"),
    ] = 60.0,
) -> dict[str, Any]:
    """Send a message to a canvas Agent and, by default, wait for its reply.

    Returns the turn and every event it produced so far. If the turn is still
    running when the wait ends, read the rest with `read_agent_events` from
    `next_sequence`.
    """
    async with grafy() as (client, workspace_id):
        if conversation_id is None:
            conversation = await client.agents.start_conversation(
                workspace_id,
                project_id,
                graph_id=graph_id,
                agent_id=agent_id,
                title=text[:80],
            )
            conversation_id = conversation.id
            after_sequence = 0
        else:
            conversation = await client.agents.get_conversation(
                workspace_id,
                project_id,
                graph_id=graph_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
            )
            after_sequence = conversation.last_sequence
        turn = await client.agents.send_turn(
            workspace_id,
            project_id,
            graph_id=graph_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            text=text,
        )
        finished = True
        if wait_seconds > 0:
            finished = await _wait_for_turn(
                client,
                workspace_id,
                project_id,
                graph_id,
                agent_id,
                conversation_id,
                wait_seconds,
            )
        events = await client.agents.list_events(
            workspace_id,
            project_id,
            graph_id=graph_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            after_sequence=after_sequence,
        )
    return {
        "conversation_id": str(conversation_id),
        "turn": dump(turn),
        "finished": finished,
        **_events(events),
    }


async def read_agent_events(
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    conversation_id: UUID,
    after_sequence: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """A conversation's events after `after_sequence`: messages, tool calls and
    results, in order."""
    async with grafy() as (client, workspace_id):
        events = await client.agents.list_events(
            workspace_id,
            project_id,
            graph_id=graph_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            after_sequence=after_sequence,
        )
    return _events(events)


async def cancel_agent_turn(
    project_id: UUID, graph_id: str, agent_id: str, conversation_id: UUID
) -> dict[str, Any]:
    """Stop the Agent's running turn in a conversation."""
    async with grafy() as (client, workspace_id):
        turn = await client.agents.cancel_turn(
            workspace_id,
            project_id,
            graph_id=graph_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )
    return dump(turn)


TOOLS: Final = (
    tool(list_agent_conversations, READ, tags={"agents"}),
    tool(send_agent_message, EDIT, tags={"agents"}),
    tool(read_agent_events, READ, tags={"agents"}),
    tool(cancel_agent_turn, IDEMPOTENT_EDIT, tags={"agents"}),
)
