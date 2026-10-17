from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from grafy_core.domain.errors import NotFoundError
from grafy_core.application.identity import authorize_workspace
from grafy_core.domain.identity import ActorContext, WorkspaceCapability
from grafy_core.domain.module_library import (
    Module,
    ModuleLibraryError,
    ModuleRelease,
)
from grafy_core.domain.modules import (
    GraphModuleDefinition,
    GraphModuleDefinitionError,
    GraphModuleReference,
    GraphModuleReferenceError,
)
from grafy_core.ports.module_library import ModuleLibraryUnitOfWorkPort
from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort
from grafy_core.plugins import PluginRegistry, UnknownOperatorError


class ModuleLibraryService:
    """Publish reusable modules into a workspace library."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], ModuleLibraryUnitOfWorkPort],
        plugin_registry: PluginRegistry,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._plugin_registry = plugin_registry

    async def list_library(self, workspace_id: UUID) -> list[Module]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.modules.list_library(workspace_id)

    async def get(self, workspace_id: UUID, module_id: UUID) -> Module:
        async with self._unit_of_work_factory() as unit_of_work:
            module = await unit_of_work.modules.get(workspace_id, module_id)
        if module is None:
            raise NotFoundError("Module", str(module_id))
        return module

    async def get_by_source_graph(
        self,
        workspace_id: UUID,
        source_graph_id: UUID,
    ) -> Module | None:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.modules.get_by_source_graph(
                workspace_id,
                source_graph_id,
            )

    async def list_releases(
        self,
        workspace_id: UUID,
        module_id: UUID,
    ) -> list[ModuleRelease]:
        async with self._unit_of_work_factory() as unit_of_work:
            module = await unit_of_work.modules.get(workspace_id, module_id)
            if module is None:
                raise NotFoundError("Module", str(module_id))
            return await unit_of_work.modules.list_releases(workspace_id, module_id)

    async def publish_release(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        source_graph_id: UUID,
        revision: int | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> tuple[Module, ModuleRelease, GraphModuleDefinition]:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.PUBLISH_MODULE,
            )
            graph = await unit_of_work.graphs.get(workspace_id, source_graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(source_graph_id))
            publish_revision = graph.revision if revision is None else revision
            snapshot = await unit_of_work.graphs.get_revision(
                workspace_id,
                source_graph_id,
                publish_revision,
            )
            if snapshot is None:
                raise NotFoundError(
                    "Saved graph revision",
                    f"{source_graph_id}@{publish_revision}",
                )
            try:
                definition = GraphModuleDefinition.from_saved_graph_revision(snapshot)
                await self._validate_optional_input_targets(
                    definition,
                    workspace_id=workspace_id,
                    graphs=unit_of_work.graphs,
                )
            except GraphModuleDefinitionError as exc:
                raise ModuleLibraryError(str(exc)) from exc

            module = await unit_of_work.modules.get_by_source_graph(
                workspace_id,
                source_graph_id,
            )
            module_name = (
                name
                if name is not None
                else (module.name if module is not None else definition.name)
            )
            module_description = (
                description
                if description is not None
                else (module.description if module is not None else None)
            )
            if module is None:
                module = Module(
                    workspace_id=workspace_id,
                    source_graph_id=source_graph_id,
                    name=module_name,
                    description=module_description,
                )
                module.apply_publish(
                    revision=publish_revision,
                    name=module_name,
                    description=module_description,
                )
                await unit_of_work.modules.add(module)
            else:
                module.apply_publish(
                    revision=publish_revision,
                    name=module_name,
                    description=module_description,
                )

            existing_release = await unit_of_work.modules.get_release(
                workspace_id,
                module.id,
                publish_revision,
            )
            if existing_release is None:
                release = ModuleRelease(
                    workspace_id=workspace_id,
                    module_id=module.id,
                    revision=publish_revision,
                    source_graph_id=source_graph_id,
                    published_by_user_id=actor.user_id,
                )
                await unit_of_work.modules.add_release(release)
            else:
                release = existing_release
            await unit_of_work.commit()
            return module, release, definition

    async def catalog_definitions(
        self,
        workspace_id: UUID,
    ) -> list[tuple[Module, ModuleRelease, GraphModuleDefinition]]:
        """Definitions for Add node: all releases of listed library modules."""
        async with self._unit_of_work_factory() as unit_of_work:
            modules = await unit_of_work.modules.list_library(workspace_id)
            results: list[tuple[Module, ModuleRelease, GraphModuleDefinition]] = []
            for module in modules:
                releases = await unit_of_work.modules.list_releases(
                    workspace_id,
                    module.id,
                )
                for release in releases:
                    snapshot = await unit_of_work.graphs.get_revision(
                        workspace_id,
                        module.source_graph_id,
                        release.revision,
                    )
                    if snapshot is None:
                        continue
                    try:
                        definition = GraphModuleDefinition.from_saved_graph_revision(
                            snapshot
                        )
                        await self._validate_optional_input_targets(
                            definition,
                            workspace_id=workspace_id,
                            graphs=unit_of_work.graphs,
                        )
                    except GraphModuleDefinitionError:
                        continue
                    results.append((module, release, definition))
            return results

    async def _validate_optional_input_targets(
        self,
        definition: GraphModuleDefinition,
        *,
        workspace_id: UUID,
        graphs: SavedGraphRepositoryPort,
    ) -> None:
        """Validate optional module inputs against their declared targets."""
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
                    try:
                        target_revision = await graphs.get_revision(
                            workspace_id,
                            target_reference.graph_id,
                            target_reference.revision,
                        )
                        if target_revision is None:
                            raise NotFoundError(
                                "Saved graph revision",
                                f"{target_reference.graph_id}@{target_reference.revision}",
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

    async def resolve_definition(
        self,
        reference: GraphModuleReference,
        *,
        workspace_id: UUID,
    ) -> GraphModuleDefinition:
        """Resolve and validate a saved-graph revision as an executable module.

        This is the canonical definition-resolution interface: the HTTP catalog
        and pinned execution both go through it rather than reimplementing the
        nested-revision and optional-input validation rules.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            snapshot = await unit_of_work.graphs.get_revision(
                workspace_id,
                reference.graph_id,
                reference.revision,
            )
            if snapshot is None:
                raise NotFoundError(
                    "Saved graph revision",
                    f"{reference.graph_id}@{reference.revision}",
                )
            definition = GraphModuleDefinition.from_saved_graph_revision(snapshot)
            await self._validate_optional_input_targets(
                definition,
                workspace_id=workspace_id,
                graphs=unit_of_work.graphs,
            )
            return definition


__all__ = ["ModuleLibraryService"]
