"""Outbound Agent turn notifications, and the coalescing in front of them (issue #202).

This module is the port; `grafy_api.realtime.agent_events` is the Project room adapter that
carries it. Nothing here knows what a socket is, because what the turn runtime needs is a
typed port it can publish through and a rule about how often, and those are the parts that
must be right whatever carries the frames:

* **A partial is transient and addressable, never authoritative.** It carries the turn id,
  the id of the assistant message being streamed, the character offset it starts at, and
  the text since the last one. A room that drops it costs a reader a stutter: the durable
  assistant message replaces whatever was streamed, and the offsets say where a dropped
  frame left the text.
* **A stored event is told, not inferred.** `event_appended` announces an event the runtime
  has just committed — the question, the answer, the ending — carrying the conversation
  sequence it took. Without it a reader would have to poll to learn that its own question
  was stored, and a second tab would show a turn waiting for an answer nobody can see.
* **Text is coalesced on a clock the runtime owns.** One frame per streamed token would
  turn a model's 200 chunks into 200 room frames and make the fastest subscriber the one
  that closes the room. The coalescer publishes at most once per interval *and only when
  there is new text*, so a stream that goes quiet costs nothing — which is also why there
  is no timer task, no polling and nothing to sleep through.
* **A failed subscriber is not the turn's problem.** The publisher port's contract is that
  it does not raise into the runtime; the runtime does not trust that and swallows and logs
  anyway, because the alternative is a dropped room connection rolling back a turn that had
  already written its final message.

`NullAgentTurnPublisher` exists for a composition that has no room to publish to — it counts
what it discarded, so a deployment that forgot to wire delivery has a number to find rather
than silence. The API composition root passes the Project room adapter.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from grafy_core.domain.agent_conversations import (
    AgentConversationEvent,
    AgentConversationTurnOutcome,
)
from grafy_core.domain.agent_turns import AgentTurn

logger = logging.getLogger(__name__)

AGENT_TEXT_PARTIAL_INTERVAL_SECONDS = 0.075
"""Roughly how often one turn's streamed text is published (~75 ms, issue #202)."""


@dataclass(frozen=True, slots=True)
class AgentTextPartial:
    """Streamed text that is not stored yet. Nobody may treat it as the answer."""

    workspace_id: UUID
    project_id: UUID
    graph_id: str
    agent_id: str
    conversation_id: UUID
    turn_id: UUID
    message_id: UUID
    # The offset this fragment starts at, in characters of the final message. A reader who
    # missed a frame can tell exactly how much it is missing.
    offset: int
    text: str

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.text)


@dataclass(frozen=True, slots=True)
class AgentTurnSnapshot:
    """What a surface needs about a turn, all of it readable or durable state."""

    turn: AgentTurn
    # The in-flight text of a running turn, and the offset it reaches. Both are empty for a
    # turn that is finished or belongs to another API owner.
    partial_text: str = ""
    partial_offset: int = 0
    partial_message_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AgentConversationNotice:
    """One event that has just become durable, with the room it belongs to.

    The event names its conversation and nothing above it, so the scope travels alongside:
    a Project room is addressed by ``(workspace_id, project_id)``, and a reader inside it
    needs the Graph and the Agent to know which card this thread is answering.
    """

    workspace_id: UUID
    project_id: UUID
    graph_id: str
    agent_id: str
    event: AgentConversationEvent


class AgentTurnPublisher(Protocol):
    """Fan-out for one conversation's turns. The Project room adapter implements this.

    Implementations must not raise into the turn: a failed publication is logged here and
    never reaches the run, and a turn's durable events are written whatever a subscriber
    does with them.

    The order the runtime calls these in is part of the contract: `turn_started`, the
    question's `event_appended`, the streamed `text_partial`s, the answer's and the ending's
    `event_appended`s, then `turn_finished`. A reader that has seen `turn_finished` has been
    told every durable event of that turn, and a reader that missed one of them recovers the
    same content from the conversation events the route serves.
    """

    async def turn_started(self, turn: AgentTurn) -> None: ...

    async def event_appended(self, notice: AgentConversationNotice) -> None: ...

    async def text_partial(self, partial: AgentTextPartial) -> None: ...

    async def turn_finished(
        self,
        turn: AgentTurn,
        *,
        outcome: AgentConversationTurnOutcome,
        detail: str | None,
    ) -> None: ...


class NullAgentTurnPublisher:
    """Drops every notification, and counts the dropping."""

    def __init__(self) -> None:
        self.dropped = 0

    async def turn_started(self, turn: AgentTurn) -> None:
        del turn
        self.dropped += 1

    async def event_appended(self, notice: AgentConversationNotice) -> None:
        del notice
        self.dropped += 1

    async def text_partial(self, partial: AgentTextPartial) -> None:
        del partial
        self.dropped += 1

    async def turn_finished(
        self,
        turn: AgentTurn,
        *,
        outcome: AgentConversationTurnOutcome,
        detail: str | None,
    ) -> None:
        del turn, outcome, detail
        self.dropped += 1


class AgentTextPartialCoalescer:
    """At most one publication per interval, and none for text nobody has sent yet.

    The clock is injected rather than read from the wall, so the rule "a frame goes out
    when the interval has passed and there is something new in it" is a decision a test can
    step through instead of a race against a timer. Nothing here waits: the turn loop calls
    `offer` as text arrives and `flush` when the turn ends, and an interval that has not
    passed simply leaves the buffer for the next chunk or for the final flush.
    """

    def __init__(
        self,
        *,
        publish: Callable[[AgentTextPartial], Awaitable[None]],
        interval_seconds: float = AGENT_TEXT_PARTIAL_INTERVAL_SECONDS,
        clock: Callable[[], float],
    ) -> None:
        if interval_seconds < 0:
            raise ValueError("the partial interval cannot be negative")
        self._publish = publish
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._buffer: list[str] = []
        self._published_chars = 0
        self._last_publish_at: float | None = None
        self._closed = False

    @property
    def pending_chars(self) -> int:
        return sum(len(chunk) for chunk in self._buffer)

    @property
    def published_chars(self) -> int:
        return self._published_chars

    async def offer(self, partial_base: AgentTextPartial, text: str) -> None:
        """Record streamed text, publishing it if the interval has passed.

        `partial_base` carries the identity (turn, message, scope); the coalescer owns the
        offset and the text, so a caller cannot publish the same characters twice by
        reusing a stale one.
        """

        if self._closed:
            raise RuntimeError("the partial coalescer is closed")
        self._buffer.append(text)
        if self._interval_elapsed():
            await self.flush(partial_base)

    async def flush(self, partial_base: AgentTextPartial) -> None:
        """Publish whatever has accumulated, as one frame."""

        if not self._buffer:
            return
        text = "".join(self._buffer)
        self._buffer.clear()
        # The frame is the caller's identity with this coalescer's offset and text, so a
        # stale base cannot make a reader see the same characters twice.
        partial = replace(
            partial_base,
            offset=self._published_chars,
            text=text,
        )
        self._published_chars += len(text)
        self._last_publish_at = self._clock()
        await self._emit(partial)

    async def close(self, partial_base: AgentTextPartial) -> None:
        """Flush what is left, and refuse anything after the turn's end.

        The durable assistant message event is what ends a message for a reader; this only
        makes sure no characters that arrived are stranded in the buffer.
        """

        if not self._closed:
            self._closed = True
            await self.flush(partial_base)

    async def _emit(self, partial: AgentTextPartial) -> None:
        try:
            await self._publish(partial)
        except Exception:
            # A subscriber that fails loses its frame and nothing else: the buffer is
            # already consumed, the offset has advanced, and the durable message is still
            # coming. Losing the turn to a broken room connection is the worse bug.
            logger.exception(
                "agent_turn_partial_publish_failed turn_id=%s offset=%s",
                partial.turn_id,
                partial.offset,
            )

    def _interval_elapsed(self) -> bool:
        if self._last_publish_at is None:
            # The first text of a turn goes out immediately: a reader waiting on an answer
            # should see the answer start, not wait out a window that has no purpose.
            return True
        return (self._clock() - self._last_publish_at) >= self._interval_seconds
