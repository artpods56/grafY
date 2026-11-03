"""Agent route dependencies: the owners, and the scope the path promised (issue #202).

Two things are impossible to skip through here.

The Agent services resolve to the ones this API owner composed at startup, which is the same
`AgentService` the Project room publishes through — so a turn sent over HTTP is the turn whose
frames the room carries, and a Stop pressed in one tab stops the task another tab started.

Every route that names a conversation resolves it through `conversation_in_project`, which
compares the stored row with the whole path. A Workspace holds many Projects, a Project many
Graphs and a Graph many Agents, so a Workspace-scoped lookup proves only that the caller may
see *a* thread; the one this URL is about has to be the one at this Agent.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from grafy_core.application.collaboration import CollaborationService
from grafy_core.domain.agent_conversations import AgentConversation
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.graph_documents import GraphAgent
from grafy_core.kernel.project import ProjectDocumentError

from grafy_api.agents.conversations import AgentConversationService
from grafy_api.agents.keys import AgentKeyService
from grafy_api.agents.models import AgentModelResolver
from grafy_api.agents.turns import AgentService
from grafy_api.app_state import get_resources


def agent_conversation_service(request: Request) -> AgentConversationService:
    return get_resources(request.app).agent_conversations


def agent_turn_service(request: Request) -> AgentService:
    return get_resources(request.app).agent_turns


def agent_key_service(request: Request) -> AgentKeyService:
    return get_resources(request.app).agent_keys


def agent_model_service(request: Request) -> AgentModelResolver:
    return get_resources(request.app).agent_models


def agent_collaboration_service(request: Request) -> CollaborationService:
    return get_resources(request.app).collaboration


async def conversation_in_project(
    workspace_id: UUID,
    project_id: UUID,
    graph_id: str,
    agent_id: str,
    conversation_id: UUID,
    conversations: AgentConversationsDependency,
) -> AgentConversation:
    """The conversation this path addresses, answered as the absence a wrong path is."""

    return await conversations.require_scoped(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id=graph_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )


def graph_on_head(head: ProjectHead, graph_id: str) -> None:
    """Refuse a Graph this Project's head does not hold, before its Agents are read."""

    try:
        head.document.get_graph(graph_id)
    except ProjectDocumentError as exc:
        raise NotFoundError("Graph", graph_id) from exc


def agent_on_head(head: ProjectHead, graph_id: str, agent_id: str) -> GraphAgent:
    """The Agent the path named, read off the Project's live head document.

    A configuration route that answered from the path alone would describe a card that is not
    on the canvas, and what it says — which endpoint, whether a key is in place — is exactly
    what a person then trusts. An Agent that has left the canvas keeps its readable history
    and loses its configuration surface, which is the same rule the turn runtime applies to a
    fresh question.
    """

    graph_on_head(head, graph_id)
    agent = next(
        (
            candidate
            for candidate in head.document.get_graph(graph_id).document.agents
            if candidate.id == agent_id
        ),
        None,
    )
    if agent is None:
        raise NotFoundError("Agent", agent_id)
    return agent


AgentConversationsDependency = Annotated[
    AgentConversationService, Depends(agent_conversation_service)
]
AgentTurnsDependency = Annotated[AgentService, Depends(agent_turn_service)]
AgentKeysDependency = Annotated[AgentKeyService, Depends(agent_key_service)]
AgentModelsDependency = Annotated[AgentModelResolver, Depends(agent_model_service)]
AgentCollaborationDependency = Annotated[
    CollaborationService, Depends(agent_collaboration_service)
]
AgentConversationDependency = Annotated[
    AgentConversation, Depends(conversation_in_project)
]


__all__ = [
    "AgentCollaborationDependency",
    "AgentConversationDependency",
    "AgentConversationsDependency",
    "AgentKeysDependency",
    "AgentModelsDependency",
    "AgentTurnsDependency",
    "agent_conversation_service",
    "agent_collaboration_service",
    "agent_key_service",
    "agent_model_service",
    "agent_on_head",
    "agent_turn_service",
    "conversation_in_project",
    "graph_on_head",
]
