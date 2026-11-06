"""What an Agent can call: the tools its links make out of nodes (ADR 0021, issue #203).

An Agent tool link names a node of the Graph and the inputs of it the model may fill. The
toolbox turns each link into one tool definition a model is shown and, when the model calls
it, into one kernel computation with no instance to record (``RunService.call_tool``).

Four things are the toolbox's rule and not any caller's:

* **A model fills only what a model can write.** A port is offered as a parameter when its
  artifact type declares a materialized JSON type (text, integer), because a string or a
  number is all a tool call carries. A link that names any other port is not offered at all
  and says why in ``unavailable``: a half-offered tool would fail on its first call.
* **Equal arguments are the same artifact.** The argument artifacts come from a seam that
  addresses them by content, so two identical calls reach the kernel with identical origins
  and therefore one fingerprint, and compute once.
* **A bad call is an answer, not an exception.** Wrong or missing arguments, an unknown tool
  and a failing computation all come back as a failed result in the model's own vocabulary,
  so it can try again. Only cancellation travels as an exception.
* **The model is told what the model saw.** ``model_view`` is rendered once, stored in the
  result event, and is what the next turn's history replays.

Every toolbox also offers ``create_artifact``, which no link names: it is how a model hands
a person something it wrote, such as a Markdown note or an HTML page, as an artifact they can
drag out of the conversation. It computes nothing and needs no node.

Everything outside the kernel is a seam, so these rules are tested without a database, a
registry or a model.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import JsonValue

from grafy_api.runs.ports import RunRejectedError, ToolCallFailedError, ToolCallResult
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.agent_conversations import (
    ToolCallPayload,
    ToolResultArtifact,
    ToolResultPayload,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.graph_documents import (
    AgentToolLink,
    GraphAgent,
    GraphDocument,
    GraphNode,
    GraphOrigin,
)

type JsonType = Literal["string", "integer"]

CREATE_ARTIFACT_TOOL = "create_artifact"
CREATE_ARTIFACT_DESCRIPTION = (
    "Save text you wrote as an artifact the person can drag from this conversation onto "
    "the canvas. Use it when they ask you to create a document or a page, and do not "
    "repeat the content in your reply. A complete HTML document is rendered as a page, "
    "and Markdown can be read as Markdown. Rendered HTML runs no scripts and loads "
    "nothing from the network, so keep CSS in a style element and embed any image as a "
    "data: URL."
)
CREATE_ARTIFACT_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description": "The whole text to save."}
    },
    "required": ["content"],
    "additionalProperties": False,
}
MAX_CREATED_ARTIFACT_CHARS = 200_000
"""Stays well inside what a card reads, so a created page is always read whole."""


@dataclass(frozen=True, slots=True)
class PortFacts:
    """What the toolbox needs to know of one port of a node's contract."""

    name: str
    artifact_type: ArtifactTypeKey | None
    required: bool = True
    title: str | None = None
    description: str | None = None


class NodePorts(Protocol):
    """The ports of a node's operator, or ``None`` when this build does not know it."""

    def input_ports(self, node: GraphNode) -> Sequence[PortFacts] | None: ...

    def output_ports(self, node: GraphNode) -> Sequence[PortFacts] | None: ...

    def title(self, node: GraphNode) -> str: ...


class ArgumentArtifacts(Protocol):
    """Where a model-written value becomes an artifact, addressed by its content."""

    def json_type(self, key: ArtifactTypeKey) -> JsonType | None:
        """The JSON type a model writes for this artifact type, or ``None`` if none."""
        ...

    async def ref_for(
        self,
        *,
        workspace_id: UUID,
        key: ArtifactTypeKey,
        value: str | int,
    ) -> ArtifactRef:
        """The artifact holding ``value``: the same one every time for equal content."""
        ...


class ToolComputation(Protocol):
    """``RunService.call_tool``, with the Project already chosen."""

    async def __call__(
        self,
        *,
        graph_id: str,
        node_id: str,
        arguments: Sequence[GraphOrigin],
    ) -> ToolCallResult: ...


class ModelViews(Protocol):
    """How outputs read to a model: text for text, a preview for a table, and so on."""

    async def render(
        self,
        *,
        outputs: Mapping[str, ArtifactOutputValue],
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ToolParameter:
    port: str
    artifact_type: ArtifactTypeKey
    json_type: JsonType
    required: bool
    description: str


@dataclass(frozen=True, slots=True)
class PreparedTool:
    """One tool link resolved against the document: ready to show and ready to call."""

    link: AgentToolLink
    node: GraphNode
    parameters: tuple[ToolParameter, ...]
    description: str

    @property
    def json_schema(self) -> dict[str, JsonValue]:
        properties: dict[str, JsonValue] = {
            parameter.port: {
                "type": parameter.json_type,
                "description": parameter.description,
            }
            for parameter in self.parameters
        }
        return {
            "type": "object",
            "properties": properties,
            "required": [p.port for p in self.parameters if p.required],
            "additionalProperties": False,
        }


@dataclass(frozen=True, slots=True)
class UnavailableTool:
    """A link the toolbox could not offer, and the reason a person can act on."""

    tool_id: str
    name: str
    reason: str


class AgentToolbox:
    """The tools of one Agent on one Graph, for the length of one turn."""

    def __init__(
        self,
        *,
        tools: Sequence[PreparedTool],
        unavailable: Sequence[UnavailableTool],
        graph_id: str,
        workspace_id: UUID,
        computation: ToolComputation,
        artifacts: ArgumentArtifacts,
        views: ModelViews,
    ) -> None:
        self._tools = {tool.link.name: tool for tool in tools}
        self.unavailable = tuple(unavailable)
        self._graph_id = graph_id
        self._workspace_id = workspace_id
        self._computation = computation
        self._artifacts = artifacts
        self._views = views

    @property
    def tools(self) -> tuple[PreparedTool, ...]:
        return tuple(self._tools.values())

    def tool(self, name: str) -> PreparedTool | None:
        return self._tools.get(name)

    @classmethod
    def build(
        cls,
        *,
        agent: GraphAgent,
        document: GraphDocument,
        graph_id: str,
        workspace_id: UUID,
        node_ports: NodePorts,
        computation: ToolComputation,
        artifacts: ArgumentArtifacts,
        views: ModelViews,
    ) -> "AgentToolbox":
        nodes = {node.id: node for node in document.nodes}
        tools: list[PreparedTool] = []
        unavailable: list[UnavailableTool] = []
        for link in agent.tools:
            outcome = _prepare(link, nodes.get(link.node_id), node_ports, artifacts)
            if isinstance(outcome, str):
                unavailable.append(UnavailableTool(link.id, link.name, outcome))
            else:
                tools.append(outcome)
        return cls(
            tools=tools,
            unavailable=unavailable,
            graph_id=graph_id,
            workspace_id=workspace_id,
            computation=computation,
            artifacts=artifacts,
            views=views,
        )

    async def execute(self, call: ToolCallPayload) -> ToolResultPayload:
        """Run one call the model made, and say how it went."""
        tool = self._tools.get(call.tool_name)
        if tool is None:
            if call.tool_name == CREATE_ARTIFACT_TOOL:
                return await self._create_artifact(call)
            return _failed(call, f"There is no tool named {call.tool_name!r}.")
        try:
            origins = await self._origins(tool, call.arguments)
        except _BadArguments as error:
            return _failed(call, str(error))
        try:
            result = await self._computation(
                graph_id=self._graph_id,
                node_id=tool.node.id,
                arguments=origins,
            )
        except asyncio.CancelledError:
            raise
        except (RunRejectedError, ToolCallFailedError) as error:
            return _failed(call, str(error))
        returned = _returned(tool, result.outputs)
        return ToolResultPayload(
            call_id=call.call_id,
            tool_id=tool.link.id,
            tool_name=tool.link.name,
            ok=True,
            fingerprint=result.fingerprint,
            artifacts=tuple(
                ToolResultArtifact(port=port, artifact=value)
                for port, value in returned.items()
            ),
            model_view=await self._views.render(outputs=returned),
        )

    async def _create_artifact(self, call: ToolCallPayload) -> ToolResultPayload:
        content = call.arguments.get("content")
        if set(call.arguments) != {"content"} or not isinstance(content, str):
            return _failed(call, "This tool takes one string argument, 'content'.")
        if not content.strip():
            return _failed(call, "There is nothing in 'content' to save.")
        if len(content) > MAX_CREATED_ARTIFACT_CHARS:
            return _failed(
                call,
                f"'content' has {len(content)} characters; an artifact may have "
                f"{MAX_CREATED_ARTIFACT_CHARS}.",
            )
        ref = await self._artifacts.ref_for(
            workspace_id=self._workspace_id, key=TEXT_VALUE.key, value=content
        )
        return ToolResultPayload(
            call_id=call.call_id,
            tool_id=call.tool_id,
            tool_name=call.tool_name,
            ok=True,
            artifacts=(ToolResultArtifact(port="artifact", artifact=ref),),
            model_view=(
                f"Saved {len(content)} characters. The person can drag the artifact "
                "from this conversation onto the canvas."
            ),
        )

    async def _origins(
        self,
        tool: PreparedTool,
        arguments: Mapping[str, JsonValue],
    ) -> list[GraphOrigin]:
        known = {parameter.port: parameter for parameter in tool.parameters}
        unknown = sorted(set(arguments) - set(known))
        if unknown:
            raise _BadArguments(
                f"Unknown argument(s): {', '.join(unknown)}. This tool takes "
                f"{', '.join(sorted(known)) or 'no arguments'}."
            )
        # Every argument is checked before any is written, so a call that is refused
        # leaves no artifact behind.
        checked: list[tuple[ToolParameter, str | int]] = []
        for parameter in tool.parameters:
            if parameter.port not in arguments:
                if parameter.required:
                    raise _BadArguments(
                        f"Missing required argument {parameter.port!r}."
                    )
                continue
            value = arguments[parameter.port]
            if parameter.json_type == "string" and isinstance(value, str):
                checked.append((parameter, value))
            elif (
                parameter.json_type == "integer"
                and isinstance(value, int)
                and not isinstance(value, bool)
            ):
                checked.append((parameter, value))
            else:
                article = "an" if parameter.json_type == "integer" else "a"
                raise _BadArguments(
                    f"Argument {parameter.port!r} must be {article} "
                    f"{parameter.json_type}."
                )
        origins: list[GraphOrigin] = []
        for parameter, written in checked:
            ref = await self._artifacts.ref_for(
                workspace_id=self._workspace_id,
                key=parameter.artifact_type,
                value=written,
            )
            origins.append(
                GraphOrigin(
                    id=f"agent-argument-{parameter.port}",
                    to_node=tool.node.id,
                    to_port=parameter.port,
                    value=ref,
                )
            )
        return origins


class _BadArguments(ValueError):
    pass


def _failed(call: ToolCallPayload, reason: str) -> ToolResultPayload:
    return ToolResultPayload(
        call_id=call.call_id,
        tool_id=call.tool_id,
        tool_name=call.tool_name,
        ok=False,
        error=reason[:2_000],
    )


def _prepare(
    link: AgentToolLink,
    node: GraphNode | None,
    node_ports: NodePorts,
    artifacts: ArgumentArtifacts,
) -> PreparedTool | str:
    """The tool a link makes, or the reason it makes none."""
    if node is None:
        return "its node is no longer on this Graph"
    inputs = node_ports.input_ports(node)
    outputs = node_ports.output_ports(node)
    if inputs is None or outputs is None:
        return "this deployment does not have the node's operator"
    by_name = {port.name: port for port in inputs}
    parameters: list[ToolParameter] = []
    for name in link.filled_ports:
        port = by_name.get(name)
        if port is None:
            return f"the node has no input {name!r}"
        json_type = (
            None
            if port.artifact_type is None
            else artifacts.json_type(port.artifact_type)
        )
        if port.artifact_type is None or json_type is None:
            return f"input {name!r} takes something a model cannot write in a call"
        parameters.append(
            ToolParameter(
                port=name,
                artifact_type=port.artifact_type,
                json_type=json_type,
                required=port.required,
                description=port.description or port.title or name,
            )
        )
    output_names = {port.name for port in outputs}
    missing = [name for name in link.returned_ports if name not in output_names]
    if missing:
        return f"the node has no output {missing[0]!r}"
    description = link.description or node_ports.title(node)
    return PreparedTool(
        link=link, node=node, parameters=tuple(parameters), description=description
    )


def _returned(
    tool: PreparedTool,
    outputs: Mapping[str, ArtifactOutputValue],
) -> dict[str, ArtifactOutputValue]:
    if not tool.link.returned_ports:
        return dict(outputs)
    return {port: outputs[port] for port in tool.link.returned_ports if port in outputs}


__all__ = [
    "AgentToolbox",
    "ArgumentArtifacts",
    "CREATE_ARTIFACT_DESCRIPTION",
    "CREATE_ARTIFACT_SCHEMA",
    "CREATE_ARTIFACT_TOOL",
    "JsonType",
    "MAX_CREATED_ARTIFACT_CHARS",
    "ModelViews",
    "NodePorts",
    "PortFacts",
    "PreparedTool",
    "ToolComputation",
    "ToolParameter",
    "UnavailableTool",
]
