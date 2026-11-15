"""The toolbox's seams, wired to the deployment (ADR 0021, issue #203).

``toolbox.py`` decides what a tool is and what a call does, against four small seams. This
module is the one place those seams meet the registry, the artifact store, the file storage
and the Run service, so the toolbox stays testable without any of them:

* **Ports** are read from the operator contract the registry registers, resolved against the
  node's own artifact type bindings, so a generic port is offered as the type it is bound to.
* **Arguments are content-addressed.** A value the model wrote becomes an inline artifact
  whose id is derived from the Workspace, the type and the content, so the same text is the
  same artifact every time and the kernel sees equal origins for equal calls.
* **Model views** are plain text a model can read: the value of a scalar or markdown, the
  compact JSON of a JSON artifact, a page of rows of a table, and for a file that is not
  JSON a one-line description that says it was not shown. Each artifact is shown with its id.
* **The computation** is ``RunService.call_tool`` with the Project already chosen.
"""

from collections.abc import Callable, Sequence
from functools import partial
from uuid import UUID

from grafy_api.agents.project_context import (
    ProjectContextReader as ProjectContextReader,
)
from grafy_api.agents.tool_arguments import (
    ARGUMENT_ARTIFACT_NAMESPACE as ARGUMENT_ARTIFACT_NAMESPACE,
    ContentAddressedArguments as ContentAddressedArguments,
)
from grafy_api.agents.tool_ports import RegistryNodePorts as RegistryNodePorts
from grafy_api.agents.tool_views import (
    MAX_VIEW_CHARS as MAX_VIEW_CHARS,
    TABLE_VIEW_ROWS as TABLE_VIEW_ROWS,
    SEQUENCE_VIEW_ITEMS as SEQUENCE_VIEW_ITEMS,
    ArtifactModelViews as ArtifactModelViews,
)
from grafy_api.agents.toolbox import (
    AgentToolbox,
    ToolComputation,
)
from grafy_api.agents.turns import AgentToolboxFactory
from grafy_api.runs.ports import ToolCallResult
from grafy_api.runs.service import RunService
from grafy_core.domain.graph_documents import (
    GraphAgent,
    GraphDocument,
    GraphOrigin,
)
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort


class ProjectToolComputation(ToolComputation):
    """``RunService.call_tool`` for one Project, at the root call path."""

    def __init__(
        self, runs: RunService, *, workspace_id: UUID, project_id: UUID
    ) -> None:
        self._runs = runs
        self._workspace_id = workspace_id
        self._project_id = project_id

    async def __call__(
        self,
        *,
        graph_id: str,
        node_id: str,
        arguments: Sequence[GraphOrigin],
    ) -> ToolCallResult:
        return await self._runs.call_tool(
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            graph_id=graph_id,
            call_path=(),
            node_id=node_id,
            arguments=arguments,
        )


def build_toolbox_factory(
    *,
    registry: PluginRegistry,
    runs: RunService,
    unit_of_work_factory: Callable[[], UnitOfWorkPort],
    storage: FileStoragePort,
) -> AgentToolboxFactory:
    """The turn runtime's way to get the tools of one Agent on one Graph."""

    ports = RegistryNodePorts(registry)
    arguments = ContentAddressedArguments(
        registry=registry, unit_of_work_factory=unit_of_work_factory
    )

    return partial(
        _build_project_toolbox,
        ports=ports,
        arguments=arguments,
        runs=runs,
        registry=registry,
        unit_of_work_factory=unit_of_work_factory,
        storage=storage,
    )


def _build_project_toolbox(
    workspace_id: UUID,
    project_id: UUID,
    graph_id: str,
    agent: GraphAgent,
    document: GraphDocument,
    *,
    ports: RegistryNodePorts,
    arguments: ContentAddressedArguments,
    runs: RunService,
    registry: PluginRegistry,
    unit_of_work_factory: Callable[[], UnitOfWorkPort],
    storage: FileStoragePort,
) -> AgentToolbox | None:
    return AgentToolbox.build(
        agent=agent,
        document=document,
        graph_id=graph_id,
        workspace_id=workspace_id,
        node_ports=ports,
        computation=ProjectToolComputation(
            runs, workspace_id=workspace_id, project_id=project_id
        ),
        artifacts=arguments,
        views=ArtifactModelViews(
            registry=registry,
            unit_of_work_factory=unit_of_work_factory,
            storage=storage,
            workspace_id=workspace_id,
        ),
    )


__all__ = [
    "ARGUMENT_ARTIFACT_NAMESPACE",
    "ProjectContextReader",
    "ArtifactModelViews",
    "ContentAddressedArguments",
    "ProjectToolComputation",
    "RegistryNodePorts",
    "build_toolbox_factory",
]
