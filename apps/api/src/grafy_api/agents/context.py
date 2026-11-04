"""What is connected to an Agent, read for one turn (ADR 0021, issue #203).

Context is connected by reference and read when a turn starts, never copied into the Agent
or the conversation: a node's output is whatever it holds now, a card shows whatever it
points at now, and a Library item is the item. What the model is told is therefore rebuilt
for every turn, and a thread that outlives an edit does not quote a document that moved.

A link that cannot be read is told to the model as unreadable instead of dropped, because a
model that was never told its source went missing would answer as if there had been none.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from grafy_core.domain.graph_documents import GraphAgent, GraphDocument


@dataclass(frozen=True, slots=True)
class ContextBlock:
    """One connected thing, as a heading and the text a model reads."""

    label: str
    text: str


class AgentContextReader(Protocol):
    async def read(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent: GraphAgent,
        document: GraphDocument,
    ) -> Sequence[ContextBlock]: ...


def instructions_with_context(
    instructions: str, blocks: Sequence[ContextBlock]
) -> str | None:
    """The Agent's instructions followed by its context, or ``None`` when both are empty."""

    if not blocks:
        return instructions or None
    sections = [instructions] if instructions else []
    sections.append(
        "# Context connected to you\n"
        "These were connected to you on the canvas and are read fresh for this turn.\n\n"
        + "\n\n".join(f"## {block.label}\n{block.text}" for block in blocks)
    )
    return "\n\n".join(sections)


__all__ = ["AgentContextReader", "ContextBlock", "instructions_with_context"]
