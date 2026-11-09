"""The wire shapes of the Agent routes (issue #202).

Requests are `extra="forbid"` like the rest of the surface, and the secret-carrying one keeps
its value a `SecretStr` so nothing downstream prints it by accident. Responses carry the
conversation's own vocabulary — the same event payloads the room frames and the stored
history use — and never a key, a digest or an instructions blob belonging to a turn.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from grafy_core.domain.agent_conversations import (
    MAX_AGENT_CONVERSATION_TITLE_CHARS,
    AgentConversation,
    AgentConversationEvent,
    AgentConversationEventPayload,
)
from grafy_core.domain.agent_turns import (
    MAX_AGENT_CLIENT_TURN_ID_CHARS,
    AgentTurn,
    AgentTurnStatus,
)

from grafy_api.agents.keys import AgentKeyState
from grafy_api.agents.models import AgentModelDescription
from grafy_api.agents.publishing import AgentTurnSnapshot


class AgentApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class StartAgentConversationRequest(AgentApiModel):
    title: Annotated[
        str, StringConstraints(max_length=MAX_AGENT_CONVERSATION_TITLE_CHARS)
    ] = ""


class ForkAgentConversationRequest(AgentApiModel):
    """Continue the thread at one of its own events, in a new conversation."""

    at_sequence: int = Field(ge=1)
    title: Annotated[
        str | None, StringConstraints(max_length=MAX_AGENT_CONVERSATION_TITLE_CHARS)
    ] = None


class SendAgentTurnRequest(AgentApiModel):
    """One question, with the id that makes repeating this request the same turn.

    `client_turn_id` is the caller's, chosen once per send and reused on a retry: the receipt
    is keyed by it, so a retried send answers with the turn it already made instead of asking
    the model twice. Different text under one id is a conflict, not a replay.
    """

    client_turn_id: Annotated[
        str, StringConstraints(min_length=1, max_length=MAX_AGENT_CLIENT_TURN_ID_CHARS)
    ]
    text: str = Field(min_length=1, max_length=1_000_000)


class CancelAgentTurnRequest(AgentApiModel):
    """Stop the conversation's turn. With no `turn_id`, whatever is running now."""

    turn_id: UUID | None = None


class SetAgentKeyRequest(AgentApiModel):
    value: SecretStr


class AgentConversationResponse(AgentApiModel):
    """One thread: what it is addressed to, and where a reader resumes from."""

    id: UUID
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    agent_id: str
    author_user_id: UUID
    title: str
    source_conversation_id: UUID | None
    source_sequence: int | None
    last_sequence: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_conversation(
        cls, conversation: AgentConversation
    ) -> "AgentConversationResponse":
        return cls(
            id=conversation.id,
            workspace_id=conversation.workspace_id,
            project_id=conversation.project_id,
            graph_id=conversation.graph_id,
            agent_id=conversation.agent_id,
            author_user_id=conversation.author_user_id,
            title=conversation.title,
            source_conversation_id=conversation.source_conversation_id,
            source_sequence=conversation.source_sequence,
            last_sequence=conversation.last_sequence,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class AgentConversationListResponse(AgentApiModel):
    conversations: list[AgentConversationResponse]


class AgentConversationEventResponse(AgentApiModel):
    sequence: int
    turn_id: UUID
    payload: AgentConversationEventPayload
    created_at: datetime

    @classmethod
    def from_event(
        cls, event: AgentConversationEvent
    ) -> "AgentConversationEventResponse":
        return cls(
            sequence=event.sequence,
            turn_id=event.turn_id,
            payload=event.payload,
            created_at=event.created_at,
        )


class AgentConversationEventListResponse(AgentApiModel):
    """The events a reader asked for, and the sequence to resume at.

    `last_sequence` is what the conversation holds now, so a reader can tell a full catch-up
    from a page that stopped at its limit without asking again to find out.
    """

    events: list[AgentConversationEventResponse]
    next_sequence: int
    last_sequence: int

    @classmethod
    def from_events(
        cls,
        events: list[AgentConversationEvent],
        *,
        conversation_last_sequence: int,
    ) -> "AgentConversationEventListResponse":
        listed = [AgentConversationEventResponse.from_event(event) for event in events]
        highest = listed[-1].sequence if listed else conversation_last_sequence
        return cls(
            events=listed,
            next_sequence=highest,
            last_sequence=conversation_last_sequence,
        )


class AgentTurnResponse(AgentApiModel):
    """One turn's receipt. Its text is in the conversation, not here."""

    id: UUID
    conversation_id: UUID
    client_turn_id: str
    status: AgentTurnStatus
    model_source: str
    model_name: str
    requested_by_user_id: UUID
    user_message_sequence: int
    outcome_detail: str | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_turn(cls, turn: AgentTurn) -> "AgentTurnResponse":
        return cls(
            id=turn.id,
            conversation_id=turn.conversation_id,
            client_turn_id=turn.client_turn_id,
            status=turn.status,
            model_source=turn.model_source,
            model_name=turn.model_name,
            requested_by_user_id=turn.requested_by_user_id,
            user_message_sequence=turn.user_message_sequence,
            outcome_detail=turn.outcome_detail,
            created_at=turn.created_at,
            finished_at=turn.finished_at,
        )


class ActiveAgentTurnResponse(AgentApiModel):
    """The turn running now, and how far its text has got.

    `partial_text` is in-flight text and may be behind a frame a reader never received, so it
    is keyed by the message id the offsets belong to and ends when the stored message event
    arrives. A turn this API owner does not run — another process owns it — answers with its
    receipt and no partial, which is the truth rather than an empty answer that looks final.
    """

    turn: AgentTurnResponse
    message_id: UUID | None
    partial_offset: int
    partial_text: str

    @classmethod
    def from_snapshot(cls, snapshot: AgentTurnSnapshot) -> "ActiveAgentTurnResponse":
        return cls(
            turn=AgentTurnResponse.from_turn(snapshot.turn),
            message_id=snapshot.partial_message_id,
            partial_offset=snapshot.partial_offset,
            partial_text=snapshot.partial_text,
        )


class AgentModelResponse(AgentApiModel):
    """What an Agent will dial, and whether it has what that needs. No key material."""

    source: str
    model_name: str
    base_url: str
    key_configured: bool

    @classmethod
    def from_description(cls, described: AgentModelDescription) -> "AgentModelResponse":
        return cls(
            source=described.source,
            model_name=described.model_name,
            base_url=described.base_url,
            key_configured=described.key_configured,
        )


class AgentKeyResponse(AgentApiModel):
    agent_id: str
    configured: bool

    @classmethod
    def from_state(cls, state: AgentKeyState) -> "AgentKeyResponse":
        return cls(agent_id=state.agent_id, configured=state.configured)


__all__ = [
    "ActiveAgentTurnResponse",
    "AgentApiModel",
    "AgentConversationEventListResponse",
    "AgentConversationEventResponse",
    "AgentConversationListResponse",
    "AgentConversationResponse",
    "AgentKeyResponse",
    "AgentModelResponse",
    "AgentTurnResponse",
    "CancelAgentTurnRequest",
    "ForkAgentConversationRequest",
    "SendAgentTurnRequest",
    "SetAgentKeyRequest",
    "StartAgentConversationRequest",
]
