from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID, uuid4

from grafy_core.application.graph_creation import stage_checkpointed_graph
from grafy_core.domain.collaboration import (
    sanitize_document_for_cross_workspace_copy,
)
from grafy_core.domain.errors import (
    CollaborationCommandRejectedError,
    NotFoundError,
)
from grafy_core.application.identity import authorize_workspace, authorize_workspaces
from grafy_core.domain.identity import ActorContext, WorkspaceCapability
from grafy_core.domain.module_library import (
    Module,
    ModuleLibraryError,
    ModulePublicationState,
    ModuleRelease,
)
from grafy_core.domain.modules import (
    GraphModuleDefinition,
    GraphModuleDefinitionError,
    GraphModuleReference,
    GraphModuleReferenceError,
)
from grafy_core.domain.saved_graphs import SavedGraph, SavedGraphRevision
from grafy_core.ports.module_library import ModuleLibraryUnitOfWorkPort
from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort
from grafy_core.plugins import PluginRegistry, UnknownOperatorError


class _SavedGraphRevisionReader(Protocol):
    async def get_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        revision: int,
    ) -> SavedGraphRevision | None: ...


class ModuleLibraryService:
    """Publish and steward modules in a workspace library."""

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

    async def list_all(self, workspace_id: UUID) -> list[Module]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.modules.list_modules(workspace_id)

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

    async def deprecate(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        module_id: UUID,
    ) -> Module:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.MANAGE_MODULE_LIBRARY,
            )
            module = await unit_of_work.modules.get(workspace_id, module_id)
            if module is None:
                raise NotFoundError("Module", str(module_id))
            module.deprecate()
            await unit_of_work.commit()
            return module

    async def withdraw(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        module_id: UUID,
    ) -> Module:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.MANAGE_MODULE_LIBRARY,
            )
            module = await unit_of_work.modules.get(workspace_id, module_id)
            if module is None:
                raise NotFoundError("Module", str(module_id))
            module.withdraw()
            await unit_of_work.commit()
            return module

    async def import_release(
        self,
        *,
        actor: ActorContext,
        source_workspace_id: UUID,
        source_module_id: UUID,
        source_revision: int | None,
        destination_workspace_id: UUID,
        name: str | None = None,
    ) -> tuple[SavedGraph, Module, ModuleRelease, GraphModuleDefinition]:
        """Copy a module release by value into another workspace library."""
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspaces(
                unit_of_work.identity,
                actor=actor,
                requirements=(
                    (source_workspace_id, WorkspaceCapability.VIEW_GRAPH),
                    (destination_workspace_id, WorkspaceCapability.CREATE_GRAPH),
                ),
            )
            source_module = await unit_of_work.modules.get(
                source_workspace_id,
                source_module_id,
            )
            if source_module is None:
                raise NotFoundError("Module", str(source_module_id))
            if not source_module.is_listed_in_library:
                raise ModuleLibraryError(
                    "Withdrawn modules cannot be imported into another workspace"
                )
            revision = (
                source_module.current_library_release
                if source_revision is None
                else source_revision
            )
            if revision is None:
                raise ModuleLibraryError("Module has no library release to import")
            release = await unit_of_work.modules.get_release(
                source_workspace_id,
                source_module_id,
                revision,
            )
            if release is None:
                raise NotFoundError(
                    "Module release",
                    f"{source_module_id}@{revision}",
                )
            snapshot = await unit_of_work.graphs.get_revision(
                source_workspace_id,
                source_module.source_graph_id,
                revision,
            )
            if snapshot is None:
                raise NotFoundError(
                    "Saved graph revision",
                    f"{source_module.source_graph_id}@{revision}",
                )
            try:
                copied_document = sanitize_document_for_cross_workspace_copy(
                    snapshot.document
                )
            except CollaborationCommandRejectedError as exc:
                raise ModuleLibraryError(str(exc)) from exc

            copied_name = (
                name.strip()
                if name is not None and name.strip() != ""
                else source_module.name
            )
            graph = SavedGraph(
                workspace_id=destination_workspace_id,
                created_by_user_id=actor.user_id,
                name=copied_name,
                document=copied_document,
                id=uuid4(),
            )
            await stage_checkpointed_graph(
                graph,
                graphs=unit_of_work.graphs,
                collaboration=unit_of_work.collaboration,
            )

            try:
                definition = GraphModuleDefinition.from_saved_graph(graph)
            except GraphModuleDefinitionError as exc:
                raise ModuleLibraryError(str(exc)) from exc

            module = Module(
                workspace_id=destination_workspace_id,
                source_graph_id=graph.id,
                name=copied_name,
                description=source_module.description,
            )
            module.apply_publish(revision=graph.revision)
            await unit_of_work.modules.add(module)
            dest_release = ModuleRelease(
                workspace_id=destination_workspace_id,
                module_id=module.id,
                revision=graph.revision,
                source_graph_id=graph.id,
                published_by_user_id=actor.user_id,
            )
            await unit_of_work.modules.add_release(dest_release)
            await unit_of_work.commit()
            return graph, module, dest_release, definition

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
        await validate_optional_input_targets(
            definition,
            workspace_id=workspace_id,
            graphs=graphs,
            plugin_registry=self._plugin_registry,
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


async def _resolve_revision_or_none(
    graphs: _SavedGraphRevisionReader,
    workspace_id: UUID,
    graph_id: UUID,
    revision: int,
) -> SavedGraphRevision | None:
    """Fetch a saved-graph revision tolerating both return-None and raise
    ``NotFoundError`` providers (repository port vs application service)."""

    try:
        snapshot = await graphs.get_revision(
            workspace_id,
            graph_id,
            revision,
        )
    except NotFoundError:
        return None
    return snapshot


async def validate_optional_input_targets(
    definition: GraphModuleDefinition,
    *,
    workspace_id: UUID,
    graphs: _SavedGraphRevisionReader,
    plugin_registry: PluginRegistry,
) -> None:
    """Validate that every optional public input's target is satisfiable.

    Shared by the module library service and the HTTP catalog so both resolve
    definitions through the same canonical rules: nested graph-module targets
    must resolve to a required input, and operator targets must declare the
    edge's input port.
    """

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
                    target_revision = await _resolve_revision_or_none(
                        graphs,
                        workspace_id,
                        target_reference.graph_id,
                        target_reference.revision,
                    )
                    if target_revision is None:
                        raise NotFoundError(
                            "Saved graph revision",
                            f"{target_reference.graph_id}@{target_reference.revision}",
                        )
                    target_definition = GraphModuleDefinition.from_saved_graph_revision(
                        target_revision
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
                    registration = plugin_registry.node_registration(
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


__all__ = ["ModuleLibraryService", "ModulePublicationState"]
