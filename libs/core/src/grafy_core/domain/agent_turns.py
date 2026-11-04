"""The durable Turn receipt (ADR 0021, issue #202).

A turn is one user message and everything the Agent does until it answers, stops or is
cancelled. The runtime around it lives and dies with one API process; this record is what
survives it, and it exists because three promises cannot be kept from memory:

* **Send is idempotent.** The caller chooses `client_turn_id`, and the receipt is keyed by
  ``(workspace_id, conversation_id, client_turn_id)`` — a database uniqueness rule, not a
  lookup. A retry after a dropped response is the same turn rather than a second model
  call, and it is answered with what was already recorded.
* **One turn runs at a time per conversation.** `running` is a partial-unique state per
  conversation, so a second send is refused by the database rather than by whoever checked
  first. A conversation with a `running` row is busy; a restart moves those rows out of
  `running`, which is what releases the admission a month later.
* **What the turn was told is fixed at admission.** `instructions`, `model_source` and
  `model_name` are copied from the Agent when the turn is accepted. Editing the Agent
  afterwards does not rewrite what a running or already-stored turn was asked to be, and a
  reader of one turn's history can tell which model wrote the answer.

The key material is deliberately absent: `model_source` and `model_name` say *which* model,
never how to dial it. A credential belongs to the key owner (`grafy_api.agents.keys`) and
to the clients a live turn holds open, and it appears in no row, event, error or log line
this record can reach.

`request_digest` is a digest over the admitted user text and nothing else. It is how a
repeated send detects "same turn id, different message" — a client bug or a replay of a
mutated body — and answers it with a conflict instead of silently returning a receipt whose
text is not the one being sent. The text itself stays in the conversation event, which is
the record of what was asked; the receipt only points at it with `user_message_sequence`.

Statuses are the conversation's turn outcomes plus `running`, and they move in one
direction: `running` is the only non-terminal state, and only `running` rows are what
startup recovery claims.
"""

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_AGENT_CLIENT_TURN_ID_CHARS = 200
MAX_AGENT_TURN_INSTRUCTIONS_CHARS = 100_000
MAX_AGENT_TURN_DETAIL_CHARS = 2_000


class AgentTurnStatus(StrEnum):
    """Where one turn stands. `running` is the only state that holds a conversation."""

    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    """Left running when the API owner stopped; its events stay (ADR 0021)."""

    @property
    def is_terminal(self) -> bool:
        return self is not AgentTurnStatus.RUNNING


class AgentTurnValue(BaseModel):
    """A frozen, extra-forbidding value of the turn record."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def turn_request_digest(text: str) -> str:
    """The digest a repeated send is compared against. Hex SHA-256 of the user text.

    It is a fingerprint of the request, not of the model's answer: two sends of the same
    message under the same turn id are the same turn, and two different messages under one
    turn id cannot both be true.
    """

    return sha256(text.encode("utf-8")).hexdigest()


class AgentTurn(AgentTurnValue):
    """One accepted turn: its scope, its snapshot, and where its events were written."""

    id: UUID
    workspace_id: UUID
    project_id: UUID
    graph_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    agent_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    conversation_id: UUID
    client_turn_id: Annotated[
        str, StringConstraints(min_length=1, max_length=MAX_AGENT_CLIENT_TURN_ID_CHARS)
    ]
    requested_by_user_id: UUID
    status: AgentTurnStatus = AgentTurnStatus.RUNNING
    request_digest: Annotated[str, StringConstraints(min_length=64, max_length=64)]
    # The dense sequence the admitted user message took, so a receipt answers "which event
    # did this turn add" without a second read of history.
    user_message_sequence: Annotated[int, Field(ge=1)]
    instructions: Annotated[
        str, StringConstraints(max_length=MAX_AGENT_TURN_INSTRUCTIONS_CHARS)
    ]
    model_source: Literal["deployment", "agent"]
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    # What a surface may say about how it ended. Never the key, never a URL that could
    # carry one.
    outcome_detail: Annotated[
        str | None, StringConstraints(max_length=MAX_AGENT_TURN_DETAIL_CHARS)
    ] = None
    created_at: datetime
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def validate_terminal_stamp(self) -> Self:
        if self.status.is_terminal and self.finished_at is None:
            raise ValueError("A finished Agent turn records when it finished")
        if not self.status.is_terminal and self.finished_at is not None:
            raise ValueError("A running Agent turn has no finish stamp")
        return self

    @property
    def is_running(self) -> bool:
        return self.status is AgentTurnStatus.RUNNING

    @classmethod
    def admit(
        cls,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
        conversation_id: UUID,
        client_turn_id: str,
        requested_by_user_id: UUID,
        user_text: str,
        user_message_sequence: int,
        instructions: str,
        model_source: Literal["deployment", "agent"],
        model_name: str,
        turn_id: UUID | None = None,
        at: datetime | None = None,
    ) -> Self:
        """The receipt a send writes when it takes the conversation.

        A turn that outlives its Agent keeps the instructions and model it was accepted
        with: this constructor takes the snapshot rather than reading a canvas that may
        already have moved.
        """

        stamp = at or datetime.now(UTC)
        return cls(
            id=turn_id or uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id=graph_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            client_turn_id=client_turn_id,
            requested_by_user_id=requested_by_user_id,
            request_digest=turn_request_digest(user_text),
            user_message_sequence=user_message_sequence,
            instructions=instructions,
            model_source=model_source,
            model_name=model_name,
            created_at=stamp,
        )

    def finished(
        self,
        *,
        status: AgentTurnStatus,
        at: datetime,
        detail: str | None = None,
    ) -> Self:
        """This receipt after the turn stopped running, with the terminal detail if any.

        A turn already out of `running` is returned unchanged: cancelling twice, or
        finishing after recovery interrupted the turn, must not rewrite the first record of
        how it ended.
        """

        if self.status.is_terminal:
            return self
        return self.model_copy(
            update={"status": status, "finished_at": at, "outcome_detail": detail}
        )

    def matches_request(self, *, user_text: str) -> bool:
        """Whether a repeated send under this id is asking for the same turn."""

        return self.request_digest == turn_request_digest(user_text)


__all__ = [
    "MAX_AGENT_CLIENT_TURN_ID_CHARS",
    "MAX_AGENT_TURN_DETAIL_CHARS",
    "MAX_AGENT_TURN_INSTRUCTIONS_CHARS",
    "AgentTurn",
    "AgentTurnStatus",
    "AgentTurnValue",
    "turn_request_digest",
]
