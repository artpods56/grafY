from typing import cast
from uuid import UUID, uuid4

from .models import (
    ActiveAgentTurn,
    AgentConversation,
    AgentConversationEvents,
    AgentModel,
    AgentTurn,
)
from .transport import HttpTransport


def _items(payload: object) -> list[object]:
    if not isinstance(payload, list):
        raise TypeError(f"Expected a JSON array, got {type(payload).__name__}")
    return cast(list[object], payload)


def _mapping(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object, got {type(payload).__name__}")
    return cast(dict[str, object], payload)


class AgentClient:
    """Conversations, turns, events, and model info for an Agent on a Graph."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def _path(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
        suffix: str = "",
    ) -> str:
        return (
            f"/v1/workspaces/{workspace_id}/projects/{project_id}"
            f"/graphs/{graph_id}/agents/{agent_id}{suffix}"
        )

    async def start_conversation(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        agent_id: str,
        title: str = "",
    ) -> AgentConversation:
        payload = await self._transport.request_json(
            operation="start agent conversation",
            method="POST",
            path=self._path(
                workspace_id, project_id, graph_id, agent_id, "/conversations"
            ),
            json_payload={"title": title},
        )
        return AgentConversation.model_validate(payload)

    async def list_conversations(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        agent_id: str,
    ) -> list[AgentConversation]:
        payload = await self._transport.request_json(
            operation="list agent conversations",
            method="GET",
            path=self._path(
                workspace_id, project_id, graph_id, agent_id, "/conversations"
            ),
        )
        return [
            AgentConversation.model_validate(item)
            for item in _items(_mapping(payload)["conversations"])
        ]

    async def get_conversation(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        agent_id: str,
        conversation_id: UUID,
    ) -> AgentConversation:
        payload = await self._transport.request_json(
            operation="get agent conversation",
            method="GET",
            path=self._path(
                workspace_id,
                project_id,
                graph_id,
                agent_id,
                f"/conversations/{conversation_id}",
            ),
        )
        return AgentConversation.model_validate(payload)

    async def send_turn(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        agent_id: str,
        conversation_id: UUID,
        text: str,
        client_turn_id: str | None = None,
    ) -> AgentTurn:
        payload = await self._transport.request_json(
            operation="send agent turn",
            method="POST",
            path=self._path(
                workspace_id,
                project_id,
                graph_id,
                agent_id,
                f"/conversations/{conversation_id}/turns",
            ),
            json_payload={
                "client_turn_id": (
                    client_turn_id if client_turn_id is not None else str(uuid4())
                ),
                "text": text,
            },
        )
        return AgentTurn.model_validate(payload)

    async def active_turn(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        agent_id: str,
        conversation_id: UUID,
    ) -> ActiveAgentTurn | None:
        payload = await self._transport.request_json(
            operation="get active agent turn",
            method="GET",
            path=self._path(
                workspace_id,
                project_id,
                graph_id,
                agent_id,
                f"/conversations/{conversation_id}/active-turn",
            ),
        )
        if payload is None:
            return None
        return ActiveAgentTurn.model_validate(payload)

    async def list_events(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        agent_id: str,
        conversation_id: UUID,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> AgentConversationEvents:
        params: dict[str, str | int | list[str]] = {
            "after_sequence": after_sequence,
        }
        if limit is not None:
            params["limit"] = limit
        payload = await self._transport.request_json(
            operation="list agent conversation events",
            method="GET",
            path=self._path(
                workspace_id,
                project_id,
                graph_id,
                agent_id,
                f"/conversations/{conversation_id}/events",
            ),
            params=params,
        )
        return AgentConversationEvents.model_validate(payload)

    async def cancel_turn(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        agent_id: str,
        conversation_id: UUID,
        turn_id: UUID | None = None,
    ) -> AgentTurn:
        payload = await self._transport.request_json(
            operation="cancel agent turn",
            method="POST",
            path=self._path(
                workspace_id,
                project_id,
                graph_id,
                agent_id,
                f"/conversations/{conversation_id}/cancel",
            ),
            json_payload={"turn_id": str(turn_id)} if turn_id is not None else None,
        )
        return AgentTurn.model_validate(payload)

    async def get_model(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        graph_id: str,
        agent_id: str,
    ) -> AgentModel:
        payload = await self._transport.request_json(
            operation="get agent model",
            method="GET",
            path=self._path(workspace_id, project_id, graph_id, agent_id, "/model"),
        )
        return AgentModel.model_validate(payload)


__all__ = ["AgentClient"]
