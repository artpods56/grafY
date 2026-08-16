from dataclasses import dataclass
from uuid import UUID

from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.module_library import ModulePublicationState
from grafy_core.domain.modules import (
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
    GraphModuleDefinition,
    GraphModuleDefinitionError,
    GraphModuleReference,
    GraphModuleReferenceError,
)
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_core.plugins import PluginRegistry, UnknownOperatorError

GRAPH_MODULE_PLUGIN_SLUG = "graph.module"
AGENT_AUTHORED_PLUGIN_SLUG = "generated.agent"

_MODULE_BOUNDARY_OPERATOR_IDS = frozenset(
    {
        MODULE_INPUT_OPERATOR_ID,
        MODULE_OUTPUT_OPERATOR_ID,
    }
)


class GraphModuleCatalogError(RuntimeError):
    """A saved graph cannot be resolved as an executable graph module."""


@dataclass(frozen=True, slots=True)
class GraphModuleCatalogEntry:
    definition: GraphModuleDefinition
    catalog_visible: bool
    module_id: UUID | None = None
    publication_state: ModulePublicationState | None = None
    is_current_library_release: bool = False


@dataclass(frozen=True, slots=True)
class UnavailableGraphModule:
    graph_id: UUID
    revision: int
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class GraphModuleCatalogListing:
    entries: list[GraphModuleCatalogEntry]
    unavailable: list[UnavailableGraphModule]


def document_has_module_boundary(document: SavedGraphDocument) -> bool:
    return any(
        node.operator_id in _MODULE_BOUNDARY_OPERATOR_IDS for node in document.nodes
    )


class GraphModuleCatalog:
    """Resolves published module releases for browse and any pin for execution."""

    def __init__(
        self,
        saved_graphs: SavedGraphService | None,
        plugin_registry: PluginRegistry,
        module_library: ModuleLibraryService | None = None,
    ) -> None:
        self._saved_graphs = saved_graphs
        self._plugin_registry = plugin_registry
        self._module_library = module_library

    async def list(self, workspace_id: UUID) -> GraphModuleCatalogListing:
        if self._module_library is None or self._saved_graphs is None:
            return GraphModuleCatalogListing(entries=[], unavailable=[])
        entries: list[GraphModuleCatalogEntry] = []
        for module, release, definition in await self._module_library.catalog_definitions(
            workspace_id
        ):
            try:
                await self._validate_optional_input_targets(
                    definition,
                    workspace_id=workspace_id,
                )
            except GraphModuleDefinitionError:
                continue
            is_current = module.current_library_release == release.revision
            entries.append(
                GraphModuleCatalogEntry(
                    definition=definition,
                    catalog_visible=is_current,
                    module_id=module.id,
                    publication_state=module.publication_state,
                    is_current_library_release=is_current,
                )
            )
        return GraphModuleCatalogListing(entries=entries, unavailable=[])

    async def get_definition(
        self,
        reference: GraphModuleReference,
        *,
        workspace_id: UUID,
    ) -> GraphModuleDefinition:
        if self._saved_graphs is None:
            raise GraphModuleCatalogError(
                "Saved graph modules are not configured for this workbench"
            )
        try:
            revision = await self._saved_graphs.get_revision(
                workspace_id,
                reference.graph_id,
                reference.revision,
            )
            definition = GraphModuleDefinition.from_saved_graph_revision(revision)
            await self._validate_optional_input_targets(
                definition,
                workspace_id=workspace_id,
            )
        except NotFoundError as exc:
            raise NotFoundError(
                "Saved graph module",
                f"{reference.graph_id}@{reference.revision}",
            ) from exc
        except GraphModuleDefinitionError as exc:
            raise GraphModuleCatalogError(
                f"Saved graph {reference.graph_id} revision {reference.revision} "
                f"is not a valid module: {exc}"
            ) from exc
        return definition

    async def _validate_optional_input_targets(
        self,
        definition: GraphModuleDefinition,
        *,
        workspace_id: UUID,
    ) -> None:
        nodes_by_id = {node.id: node for node in definition.document.nodes}
        for public_port in definition.input_ports:
            if public_port.required:
                continue
            for edge in definition.document.edges:
                if not edge.enabled or edge.from_node != public_port.boundary_node_id:
                    continue
                target_node = nodes_by_id[edge.to_node]
                try:
                    target_reference = GraphModuleReference.try_from_operator_identity(
                        target_node.operator_id,
                        target_node.operator_version,
                    )
                except GraphModuleReferenceError as exc:
                    raise GraphModuleDefinitionError(
                        f"Graph module {definition.reference.graph_id} revision "
                        f"{definition.reference.revision} optional public input "
                        f"{public_port.name!r} edge {edge.id!r} targets invalid "
                        f"graph module operator {target_node.operator_id}@"
                        f"{target_node.operator_version}: {exc}"
                    ) from exc

                if target_reference is not None:
                    if self._saved_graphs is None:
                        raise GraphModuleDefinitionError(
                            f"Graph module {definition.reference.graph_id} revision "
                            f"{definition.reference.revision} optional public input "
                            f"{public_port.name!r} edge {edge.id!r} cannot resolve "
                            "its target graph module because saved graphs are not "
                            "configured"
                        )
                    try:
                        target_revision = await self._saved_graphs.get_revision(
                            workspace_id,
                            target_reference.graph_id,
                            target_reference.revision,
                        )
                        target_definition = (
                            GraphModuleDefinition.from_saved_graph_revision(
                                target_revision
                            )
                        )
                        target_port = target_definition.input_port(edge.to_port)
                    except (GraphModuleDefinitionError, NotFoundError) as exc:
                        raise GraphModuleDefinitionError(
                            f"Graph module {definition.reference.graph_id} revision "
                            f"{definition.reference.revision} optional public input "
                            f"{public_port.name!r} edge {edge.id!r} cannot resolve "
                            f"target input {target_node.id!r}.{edge.to_port!r} "
                            f"({target_node.operator_id}@"
                            f"{target_node.operator_version}): {exc}"
                        ) from exc
                    target_required = target_port.required
                else:
                    try:
                        registration = self._plugin_registry.node_registration(
                            target_node.operator_id,
                            target_node.operator_version,
                        )
                    except UnknownOperatorError as exc:
                        raise GraphModuleDefinitionError(
                            f"Graph module {definition.reference.graph_id} revision "
                            f"{definition.reference.revision} optional public input "
                            f"{public_port.name!r} edge {edge.id!r} targets unknown "
                            f"operator {target_node.operator_id}@"
                            f"{target_node.operator_version}"
                        ) from exc
                    target_port = registration.node_class.input_contract.ports.get(
                        edge.to_port
                    )
                    if target_port is None:
                        raise GraphModuleDefinitionError(
                            f"Graph module {definition.reference.graph_id} revision "
                            f"{definition.reference.revision} optional public input "
                            f"{public_port.name!r} edge {edge.id!r} targets missing "
                            f"input {target_node.id!r}.{edge.to_port!r} "
                            f"({target_node.operator_id}@"
                            f"{target_node.operator_version})"
                        )
                    target_required = target_port.required

                if target_required:
                    raise GraphModuleDefinitionError(
                        f"Graph module {definition.reference.graph_id} revision "
                        f"{definition.reference.revision} optional public input "
                        f"{public_port.name!r} edge {edge.id!r} targets required "
                        f"input {target_node.id!r}.{edge.to_port!r} "
                        f"({target_node.operator_id}@{target_node.operator_version})"
                    )


__all__ = [
    "AGENT_AUTHORED_PLUGIN_SLUG",
    "GRAPH_MODULE_PLUGIN_SLUG",
    "GraphModuleCatalog",
    "GraphModuleCatalogEntry",
    "GraphModuleCatalogError",
    "GraphModuleCatalogListing",
    "UnavailableGraphModule",
    "document_has_module_boundary",
]
