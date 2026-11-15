import logging
from collections.abc import Callable, Sequence
from uuid import UUID
from grafy_api.agents.context import AgentContextReader, ContextBlock
from grafy_api.agents.toolbox import (
    output_artifact_refs,
)
from grafy_api.runs.service import RunService
from grafy_core.domain.graph_documents import (
    GraphAgent,
    GraphDocument,
)
from grafy_core.kernel.instances import InstanceKey
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_api.agents.tool_ports import RegistryNodePorts
from grafy_api.agents.tool_views import ArtifactModelViews


logger = logging.getLogger("grafy_api.agents.project_tools")


class ProjectContextReader(AgentContextReader):
    """The three things that can be connected to an Agent, read for one turn."""

    def __init__(
        self,
        *,
        runs: RunService,
        registry: PluginRegistry,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        storage: FileStoragePort,
    ) -> None:
        self._runs = runs
        self._registry = registry
        self._uow_factory = unit_of_work_factory
        self._storage = storage

    async def read(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent: GraphAgent,
        document: GraphDocument,
    ) -> Sequence[ContextBlock]:
        views = ArtifactModelViews(
            registry=self._registry,
            unit_of_work_factory=self._uow_factory,
            storage=self._storage,
            workspace_id=workspace_id,
        )
        viewers = {viewer.id: viewer for viewer in document.presentation.viewers}
        nodes = {node.id: node for node in document.nodes}
        titles = RegistryNodePorts(self._registry)
        blocks: list[ContextBlock] = []
        for link in agent.context:
            try:
                if link.kind == "node_output" and link.node_id and link.port:
                    node = nodes[link.node_id]
                    label = f"{titles.title(node)}, output {link.port}"
                    snapshot, stored = await self._runs.instance_result(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        key=InstanceKey(
                            project_id=str(project_id),
                            graph_id=graph_id,
                            call_path=(),
                            node_id=link.node_id,
                        ),
                    )
                    if stored is None or link.port not in stored.outputs:
                        text = f"[this node has no result to show yet; it is {snapshot.state.value}]"
                        refs = ()
                    else:
                        value = stored.outputs[link.port]
                        rendered = await views.render(outputs={link.port: value})
                        text = (
                            rendered.split(":\n", 1)[1]
                            if rendered.startswith(f"{link.port}:\n")
                            else rendered
                        )
                        refs = output_artifact_refs(value)
                    blocks.append(ContextBlock(label, text, artifacts=refs))
                elif link.kind == "card" and link.card_id:
                    viewer = viewers.get(link.card_id)
                    if viewer is None or viewer.artifact_ref is None:
                        blocks.append(ContextBlock("A card", "[this card is gone]"))
                    else:
                        value = viewer.artifact_ref
                        rendered = await views.render(outputs={"card": value})
                        # The view names a port. The heading already says it is a card.
                        body = (
                            rendered.split(":\n", 1)[1]
                            if rendered.startswith("card:\n")
                            else rendered
                        )
                        blocks.append(
                            ContextBlock(
                                "A card on the canvas",
                                body,
                                artifacts=output_artifact_refs(value),
                            )
                        )
                elif link.kind == "library_item" and link.library_item_id:
                    text, ref = await views.render_library_item(link.library_item_id)
                    blocks.append(
                        ContextBlock(
                            "A Library item",
                            text,
                            artifacts=() if ref is None else (ref,),
                        )
                    )
            except Exception:  # noqa: BLE001 - one unreadable link must not end the turn
                logger.warning(
                    "agent_context_unreadable agent=%s link=%s", agent.id, link.id
                )
                blocks.append(ContextBlock(f"Context {link.id}", "[could not be read]"))
        return blocks
