"""Grafy history in, pydantic-ai messages out (ADR 0021, issue #202).

Grafy's event union is the durable record and the library's message format is a request
shape, so the two meet here and nowhere else: nothing in this package stores a pydantic-ai
message, and nothing in pydantic-ai is trusted to remember a conversation.

The rebuild is deliberately literal about what actually happened, because a model reading
its own history draws conclusions from what is *missing* too:

* A user message is a user message, in order, whatever the turn's outcome was. A question
  that got no answer is still a question that was asked — hiding it would silently rewrite
  what the person typed.
* An assistant message is what was stored, which for a cancelled or failed turn is the text
  that had arrived. It is kept: the model said it, and dropping it would make the next
  answer pretend the transcript was shorter than it is.
* A turn that did not complete is *labelled*, in a system part beside the next request, so
  the model knows the reply above was cut short rather than finished. The label is added
  here, at the boundary, and never written into the stored event — the event says what
  arrived, and only the outcome says whether that was all of it.
* A forked conversation needs no special case. A fork copies the source's events, so
  "continue from here" rebuilds exactly the history the source had at the cut, and the
  source keeps its own.

A tool call and its result are rebuilt the way the model produced and read them: the
calls of one response are one response, the results that answered them are one request.
Text the model wrote before calling is part of that same response, so a provider that
wants a response to end in its calls sees one. A confirmation request adds nothing: the
call it stopped was never stored, so the results above it are the whole of what
happened and the person's reply is simply the next message.
"""

from grafy_core.domain.agent_conversations import (
    AgentConversationEvent,
    AgentConversationTurnOutcome,
    AssistantMessagePayload,
    ConfirmationRequestedPayload,
    ToolCallPayload,
    ToolResultPayload,
    TurnOutcomePayload,
    UserMessagePayload,
)
from grafy_core.domain.agent_turns import AgentTurn, AgentTurnStatus
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ModelResponsePart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

_CUT_SHORT_NOTE = {
    AgentTurnStatus.CANCELLED: (
        "Your previous reply to this conversation was cancelled before it finished, so "
        "the text above is only what had been written."
    ),
    AgentTurnStatus.FAILED: (
        "Your previous reply to this conversation failed before it finished, so the text "
        "above may stop in the middle of a sentence."
    ),
    AgentTurnStatus.INTERRUPTED: (
        "Your previous reply to this conversation was interrupted when the server "
        "restarted, so the text above is only what had been written."
    ),
}


def history_messages(
    events: list[AgentConversationEvent],
) -> list[ModelMessage]:
    """The stored history as messages, oldest event first.

    A conversation whose last event is a user message ends on a request, which is the
    shape of a question that is still waiting: the runtime sends the new message as the
    prompt rather than folding it in here.
    """

    messages: list[ModelMessage] = []
    # What the model said and what it was told back alternate; each run of one kind
    # is one message, closed by the first event of the other.
    said: list[ModelResponsePart] = []
    told: list[ModelRequestPart] = []

    def close_said() -> None:
        if said:
            messages.append(ModelResponse(parts=list(said)))
            said.clear()

    def close_told() -> None:
        if told:
            messages.append(ModelRequest(parts=list(told)))
            told.clear()

    for event in events:
        payload = event.payload
        match payload:
            case UserMessagePayload(text=text):
                close_said()
                close_told()
                messages.append(ModelRequest(parts=[UserPromptPart(content=text)]))
            case AssistantMessagePayload(text=text):
                close_told()
                said.append(TextPart(content=text))
            case ToolCallPayload() as call:
                close_told()
                said.append(
                    ToolCallPart(
                        tool_name=call.tool_name,
                        args=call.arguments,
                        tool_call_id=call.call_id,
                    )
                )
            case ToolResultPayload() as result:
                close_said()
                told.append(
                    ToolReturnPart(
                        tool_name=result.tool_name,
                        content=result.model_view
                        if result.ok
                        else f"The tool call failed: {result.error or 'no reason given'}",
                        tool_call_id=result.call_id,
                        outcome="success" if result.ok else "failed",
                    )
                )
            case ConfirmationRequestedPayload():
                close_said()
                close_told()
            case TurnOutcomePayload(outcome=outcome):
                close_said()
                close_told()
                # A completed turn needs no comment beside it. Anything else says so here, at
                # the boundary, because the stored event cannot: it records what arrived, and
                # only the outcome knows whether that was all of it.
                if outcome is AgentConversationTurnOutcome.COMPLETED:
                    continue
                note = _CUT_SHORT_NOTE.get(AgentTurnStatus(outcome.value))
                if note is not None:
                    messages.append(
                        ModelRequest(parts=[SystemPromptPart(content=note)])
                    )
        # A payload this rebuild does not know yet matches no case above and so adds
        # nothing to the model's view of the past, which is what an unknown part of a
        # conversation deserves: nothing said about it rather than something guessed.
    close_said()
    close_told()
    return messages


def instructions_for(turn: AgentTurn) -> str:
    """What the turn was told it is, taken from the receipt and not from the canvas.

    An empty instruction is passed as nothing rather than as an empty system message: a
    blank instruction line is what a model is asked to reconcile with its own behaviour,
    and an Agent with no instructions has none.
    """

    return turn.instructions


__all__ = ["history_messages", "instructions_for"]
