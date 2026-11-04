"""Agent conversations and their ordered events (ADR 0021, issue #202).

A conversation is the append-only history of one thread with one Agent. It belongs to a
Project, sits on one Graph next to one Agent, and remembers who started it. Events are
never edited, re-ordered or deleted: an append takes the sequence the conversation is
waiting for and moves the conversation on by one, so a hole or a reused sequence is a
lost race rather than a corrupt row. "Continue from here" is a *fork*: a new
conversation that copies the first ``n`` events and records the conversation and the
sequence it copied, which is what makes the copy explainable a month later.

These values are Grafy's own durable format. The agent library's message format is
rebuilt from events at the runtime boundary and is never stored here.

Message text is capped so one event cannot grow past the row that holds it; the cap is
generous because a historian pastes a source, and it is a domain rule rather than a
column limit so the in-memory and SQL adapters cannot disagree about it.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from grafy_core.domain.artifact_outputs import ArtifactOutputValue

MAX_AGENT_MESSAGE_CHARS = 1_000_000
"""The longest single message text one event may carry."""

MAX_AGENT_CONVERSATION_TITLE_CHARS = 500


class AgentConversationValue(BaseModel):
    """A frozen, extra-forbidding value of the conversation record."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class AgentConversationTurnOutcome(StrEnum):
    """How one Turn ended, as the last event the Turn writes."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    """Left running when the API owner stopped; its events stay (ADR 0021)."""


class UserMessagePayload(AgentConversationValue):
    kind: Literal["user_message"] = "user_message"
    text: Annotated[
        str, StringConstraints(min_length=1, max_length=MAX_AGENT_MESSAGE_CHARS)
    ]


class AssistantMessagePayload(AgentConversationValue):
    kind: Literal["assistant_message"] = "assistant_message"
    text: Annotated[
        str, StringConstraints(min_length=1, max_length=MAX_AGENT_MESSAGE_CHARS)
    ]


MAX_AGENT_TOOL_MODEL_VIEW_CHARS = 100_000
"""The most of one tool result a single event keeps: what the model was shown."""

_CallId = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class ToolCallPayload(AgentConversationValue):
    """The model asked to call one of the Agent's tools (ADR 0021).

    ``call_id`` is the model's own id for the call, which is what the result answers.
    ``arguments`` are exactly what the model gave; the artifacts built from them are
    named by the result, not copied here.
    """

    kind: Literal["tool_call"] = "tool_call"
    call_id: _CallId
    tool_id: _CallId
    tool_name: _CallId
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ToolResultArtifact(AgentConversationValue):
    """One output a tool call produced, which a person can drag out of the thread."""

    port: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    artifact: ArtifactOutputValue


class ToolResultPayload(AgentConversationValue):
    """How one tool call ended, and what the model was shown of it.

    ``fingerprint`` is the temporary instance's, so the call is traceable to the
    result store entry it used; ``artifacts`` carry what a person can take away.
    ``model_view`` is stored because it is what the model saw: rebuilding it from the
    artifacts later could differ from what it actually read.
    """

    kind: Literal["tool_result"] = "tool_result"
    call_id: _CallId
    tool_id: _CallId
    tool_name: _CallId
    ok: bool
    fingerprint: str | None = None
    artifacts: tuple[ToolResultArtifact, ...] = ()
    model_view: Annotated[
        str, StringConstraints(max_length=MAX_AGENT_TOOL_MODEL_VIEW_CHARS)
    ] = ""
    error: Annotated[str | None, StringConstraints(max_length=2_000)] = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.ok and self.error is not None:
            raise ValueError("A successful tool result carries no error")
        if not self.ok and self.artifacts:
            raise ValueError("A failed tool result carries no artifacts")
        return self


class ConfirmationRequestedPayload(AgentConversationValue):
    """The turn stopped before a further tool call, and asks a person to go on.

    The model wanted more calls than a turn may make unprompted. The call it asked
    for is not stored and not run; a person's reply is a new turn, which carries on
    from the results already in the conversation.
    """

    kind: Literal["confirmation_requested"] = "confirmation_requested"
    tool_calls: Annotated[int, Field(ge=1)]
    limit: Annotated[int, Field(ge=1)]


class TurnOutcomePayload(AgentConversationValue):
    kind: Literal["turn_outcome"] = "turn_outcome"
    outcome: AgentConversationTurnOutcome
    detail: Annotated[str | None, StringConstraints(max_length=2_000)] = None


AgentConversationEventPayload = Annotated[
    UserMessagePayload
    | AssistantMessagePayload
    | ToolCallPayload
    | ToolResultPayload
    | ConfirmationRequestedPayload
    | TurnOutcomePayload,
    Field(discriminator="kind"),
]

AGENT_CONVERSATION_EVENT_PAYLOAD_ADAPTER: TypeAdapter[AgentConversationEventPayload] = (
    TypeAdapter(AgentConversationEventPayload)
)


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"Agent conversation {field_name} must be timezone-aware")
    return value


class AgentConversationEvent(AgentConversationValue):
    """One entry of one conversation, addressed by its dense per-conversation sequence."""

    workspace_id: UUID
    conversation_id: UUID
    sequence: Annotated[int, Field(ge=1)]
    turn_id: UUID
    payload: AgentConversationEventPayload
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _aware(value, "created_at")


class AgentConversation(AgentConversationValue):
    """One thread with one Agent, and the sequence its next event will take."""

    id: UUID
    workspace_id: UUID
    project_id: UUID
    graph_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    agent_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    author_user_id: UUID
    title: Annotated[
        str, StringConstraints(max_length=MAX_AGENT_CONVERSATION_TITLE_CHARS)
    ] = ""
    source_conversation_id: UUID | None = None
    source_sequence: Annotated[int | None, Field(ge=1)] = None
    next_sequence: Annotated[int, Field(ge=1)] = 1
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        return _aware(value, "timestamp")

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.source_conversation_id is None) != (self.source_sequence is None):
            raise ValueError(
                "A forked Agent conversation records both its source and its source sequence"
            )
        if (
            self.source_conversation_id is not None
            and self.source_conversation_id == self.id
        ):
            raise ValueError("An Agent conversation cannot be its own source")
        return self

    @classmethod
    def new(
        cls,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
        author_user_id: UUID,
        title: str = "",
        conversation_id: UUID | None = None,
        at: datetime | None = None,
    ) -> Self:
        stamp = at or datetime.now(UTC)
        return cls(
            id=conversation_id or uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id=graph_id,
            agent_id=agent_id,
            author_user_id=author_user_id,
            title=title,
            created_at=stamp,
            updated_at=stamp,
        )

    @property
    def is_fork(self) -> bool:
        return self.source_conversation_id is not None

    @property
    def last_sequence(self) -> int:
        """The sequence of the stored event, or 0 when nothing has been appended."""

        return self.next_sequence - 1

    def fork(
        self,
        *,
        at_sequence: int,
        author_user_id: UUID,
        title: str | None = None,
        conversation_id: UUID | None = None,
        at: datetime | None = None,
    ) -> "AgentConversation":
        """The conversation that continues this one from ``at_sequence``.

        The fork keeps the Project, Graph and Agent the source belongs to and records
        where it was cut, so a later reader can tell a continuation from a fresh thread.
        """

        if at_sequence < 1 or at_sequence > self.last_sequence:
            raise ValueError(
                f"Cannot fork conversation {self.id} at sequence {at_sequence}: "
                f"it holds {self.last_sequence} event(s)"
            )
        stamp = at or datetime.now(UTC)
        return AgentConversation(
            id=conversation_id or uuid4(),
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            graph_id=self.graph_id,
            agent_id=self.agent_id,
            author_user_id=author_user_id,
            title=self.title if title is None else title,
            source_conversation_id=self.id,
            source_sequence=at_sequence,
            created_at=stamp,
            updated_at=stamp,
        )

    def appended(self, *, at: datetime) -> Self:
        """This conversation after one event has been stored at ``next_sequence``."""

        return self.model_copy(
            update={"next_sequence": self.next_sequence + 1, "updated_at": at}
        )

    def event(
        self,
        *,
        turn_id: UUID,
        payload: AgentConversationEventPayload,
        at: datetime | None = None,
    ) -> AgentConversationEvent:
        """The event that would append next to this conversation."""

        return AgentConversationEvent(
            workspace_id=self.workspace_id,
            conversation_id=self.id,
            sequence=self.next_sequence,
            turn_id=turn_id,
            payload=payload,
            created_at=at or datetime.now(UTC),
        )


def event_payload_from_storage(value: object) -> AgentConversationEventPayload:
    """Read one stored payload back through the discriminated union.

    Every member forbids extra keys, so a payload written by a future build is rejected
    here rather than silently read with a field missing.
    """

    return AGENT_CONVERSATION_EVENT_PAYLOAD_ADAPTER.validate_python(value)


def event_payload_to_storage(
    payload: AgentConversationEventPayload,
) -> dict[str, object]:
    return payload.model_dump(mode="json", exclude_none=False)


__all__ = [
    "AGENT_CONVERSATION_EVENT_PAYLOAD_ADAPTER",
    "MAX_AGENT_CONVERSATION_TITLE_CHARS",
    "MAX_AGENT_MESSAGE_CHARS",
    "AgentConversation",
    "AgentConversationEvent",
    "AgentConversationEventPayload",
    "AgentConversationTurnOutcome",
    "AgentConversationValue",
    "AssistantMessagePayload",
    "ConfirmationRequestedPayload",
    "MAX_AGENT_TOOL_MODEL_VIEW_CHARS",
    "ToolCallPayload",
    "ToolResultArtifact",
    "ToolResultPayload",
    "TurnOutcomePayload",
    "UserMessagePayload",
    "event_payload_from_storage",
    "event_payload_to_storage",
]
