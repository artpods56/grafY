"""Agent turn fan-out to Project rooms (ADR 0021, issue #202).

The turn runtime owns what happened; this module owns who hears about it. Four frames carry
one turn, in the order the runtime produced them:

* ``agent.turn.started`` — a receipt exists and a model is being dialled.
* ``agent.event.appended`` — one event became durable: the question, the answer, the ending.
  This is the authoritative telling.
* ``agent.delta`` — text that is not stored yet, and might never be.
* ``agent.turn.finished`` — the turn is out of ``running`` and every event it will write has
  been told.

Two rules decide how each one travels, and they are the reason this adapter exists rather
than a call to the hub from inside the runtime:

* **Authoritative frames are queued, transient ones are offered.** A turn's start, its stored
  events and its finish are what a reader's thread is made of, so they go on the same path a
  command receipt does. A delta is worth one frame and nothing more, so it goes through the
  hub's drop-if-busy offer: a subscriber that has stopped draining loses the frame and keeps
  its connection, instead of being closed for slowness and taking everyone's room down with
  it. What a reader missed is in the conversation, and the offsets say how much.
* **A failed publication is a log line.** Nothing here may raise into a turn: the receipt and
  the events are already committed by the time the frame is built, so the only thing an
  exception could reach is the task writing the answer. That is the same rule the Run fan-out
  follows for the same reason.
"""

import logging

from grafy_api.agents.publishing import (
    AgentConversationNotice,
    AgentTextPartial,
)
from grafy_api.realtime.hub import ProjectRoomHub
from grafy_api.realtime.protocol import (
    AGENT_DELTA_MAX_TEXT_CHARS,
    AgentConversationEventEntry,
    AgentDeltaMessage,
    AgentEventAppendedMessage,
    AgentTurnFinishedMessage,
    AgentTurnStartedMessage,
    AgentTurnSummary,
)
from grafy_core.domain.agent_conversations import AgentConversationTurnOutcome
from grafy_core.domain.agent_turns import AgentTurn

logger = logging.getLogger(__name__)


def agent_turn_summary(turn: AgentTurn) -> AgentTurnSummary:
    """What a room may be told about one turn, read off its receipt.

    The scope is in every frame because a Project room holds several Graphs and a Graph holds
    several Agents: a reader routes a frame to the card that asked, and cannot do that from a
    turn id alone.
    """

    return AgentTurnSummary(
        turn_id=turn.id,
        conversation_id=turn.conversation_id,
        graph_id=turn.graph_id,
        agent_id=turn.agent_id,
        status=turn.status,
        model_source=turn.model_source,
        model_name=turn.model_name,
        requested_by_user_id=turn.requested_by_user_id,
        created_at=turn.created_at,
    )


class ProjectAgentEvents:
    """The ``AgentTurnPublisher`` the API composition root hands the turn runtime."""

    def __init__(
        self,
        *,
        hub: ProjectRoomHub,
        delta_char_cap: int = AGENT_DELTA_MAX_TEXT_CHARS,
    ) -> None:
        self._hub = hub
        self._delta_char_cap = delta_char_cap

    async def turn_started(self, turn: AgentTurn) -> None:
        try:
            await self._hub.publish_model(
                workspace_id=turn.workspace_id,
                project_id=turn.project_id,
                message=AgentTurnStartedMessage(turn=agent_turn_summary(turn)),
            )
        except Exception:
            logger.exception(
                "agent_turn_started_fanout_failed turn_id=%s project_id=%s",
                turn.id,
                turn.project_id,
            )

    async def event_appended(self, notice: AgentConversationNotice) -> None:
        event = notice.event
        try:
            await self._hub.publish_model(
                workspace_id=notice.workspace_id,
                project_id=notice.project_id,
                message=AgentEventAppendedMessage(
                    graph_id=notice.graph_id,
                    agent_id=notice.agent_id,
                    event=AgentConversationEventEntry(
                        conversation_id=event.conversation_id,
                        sequence=event.sequence,
                        turn_id=event.turn_id,
                        payload=event.payload,
                        created_at=event.created_at,
                    ),
                ),
            )
        except Exception:
            logger.exception(
                "agent_event_fanout_failed conversation_id=%s sequence=%s",
                event.conversation_id,
                event.sequence,
            )

    async def text_partial(self, partial: AgentTextPartial) -> None:
        if len(partial.text) > self._delta_char_cap:
            # Longer than one frame may carry: dropped, not truncated. A reader that is given
            # half the characters would believe it had the other half, and the whole message
            # arrives as a stored event either way.
            logger.warning(
                "agent_delta_frame_too_long turn_id=%s offset=%s chars=%s cap=%s",
                partial.turn_id,
                partial.offset,
                len(partial.text),
                self._delta_char_cap,
            )
            return
        try:
            await self._hub.publish_transient(
                workspace_id=partial.workspace_id,
                project_id=partial.project_id,
                message=AgentDeltaMessage(
                    graph_id=partial.graph_id,
                    agent_id=partial.agent_id,
                    conversation_id=partial.conversation_id,
                    turn_id=partial.turn_id,
                    message_id=partial.message_id,
                    offset=partial.offset,
                    text=partial.text,
                ),
            )
        except Exception:
            logger.exception(
                "agent_delta_fanout_failed turn_id=%s offset=%s",
                partial.turn_id,
                partial.offset,
            )

    async def turn_finished(
        self,
        turn: AgentTurn,
        *,
        outcome: AgentConversationTurnOutcome,
        detail: str | None,
    ) -> None:
        try:
            await self._hub.publish_model(
                workspace_id=turn.workspace_id,
                project_id=turn.project_id,
                message=AgentTurnFinishedMessage(
                    graph_id=turn.graph_id,
                    agent_id=turn.agent_id,
                    conversation_id=turn.conversation_id,
                    turn_id=turn.id,
                    outcome=outcome,
                    detail=detail,
                ),
            )
        except Exception:
            logger.exception(
                "agent_turn_finished_fanout_failed turn_id=%s project_id=%s",
                turn.id,
                turn.project_id,
            )


__all__ = ["ProjectAgentEvents", "agent_turn_summary"]
