from collections.abc import Callable
from typing import cast
from uuid import UUID

from pydantic import ValidationError

from grafy_core.application.identity import authorize_workspace
from grafy_core.domain.errors import (
    ConcurrentWriteError,
    GraphFolderNameConflictError,
    NotFoundError,
    SavedGraphRevisionConflictError,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceCapability,
)
from grafy_core.domain.node_secrets import (
    InvalidNodeSecretDependenciesError,
    JsonValue,
    node_secret_dependency_sha256,
)
from grafy_core.domain.materialized_outputs import (
    materializations_for_compatible_nodes,
)
from grafy_core.domain.saved_graphs import (
    GraphBrowserItem,
    GraphFolder,
    GraphOrganization,
    SavedGraph,
    SavedGraphDocument,
    SavedGraphRevision,
    UserGraphState,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.materialized_outputs import (
    MaterializedNodeOutputsRepositoryPort,
)
from grafy_core.ports.saved_graphs import SavedGraphUnitOfWorkPort


class SavedGraphService:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], SavedGraphUnitOfWorkPort],
        plugin_registry: PluginRegistry,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._plugin_registry = plugin_registry

    async def create(
        self,
        *,
        workspace_id: UUID,
        created_by_user_id: UUID | None,
        name: str,
        document: SavedGraphDocument,
    ) -> SavedGraph:
        graph = SavedGraph(
            workspace_id=workspace_id,
            created_by_user_id=created_by_user_id,
            name=name,
            document=document,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.graphs.add(graph)
            await unit_of_work.graphs.add_revision(graph.snapshot())
            await unit_of_work.commit()
        return graph

    async def get(self, workspace_id: UUID, graph_id: UUID) -> SavedGraph:
        async with self._unit_of_work_factory() as unit_of_work:
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
        if graph is None:
            raise NotFoundError("Saved graph", str(graph_id))
        return graph

    async def get_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        revision: int,
    ) -> SavedGraphRevision:
        async with self._unit_of_work_factory() as unit_of_work:
            snapshot = await unit_of_work.graphs.get_revision(
                workspace_id,
                graph_id,
                revision,
            )
        if snapshot is None:
            raise NotFoundError("Saved graph revision", f"{graph_id}@{revision}")
        return snapshot

    async def list_revisions(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[SavedGraphRevision]:
        async with self._unit_of_work_factory() as unit_of_work:
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            return await unit_of_work.graphs.list_revisions(workspace_id, graph_id)

    async def list_accessible(self, actor: ActorContext) -> list[GraphBrowserItem]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.graphs.list_accessible(actor.user_id)

    async def create_folder(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        name: str,
    ) -> GraphFolder:
        folder = GraphFolder(workspace_id=workspace_id, name=name)
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_GRAPH,
            )
            existing = await unit_of_work.graphs.get_folder_by_name(
                workspace_id,
                folder.name,
            )
            if existing is not None:
                raise GraphFolderNameConflictError(
                    workspace_id=workspace_id,
                    name=folder.name,
                )
            await unit_of_work.graphs.add_folder(folder)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    workspace_id=workspace_id,
                    operation="graph.folder.create",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="graph_folder",
                    resource_id=str(folder.id),
                )
            )
            await unit_of_work.commit()
        return folder

    async def list_folders(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
    ) -> list[GraphFolder]:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.VIEW_GRAPH,
            )
            return await unit_of_work.graphs.list_folders(workspace_id)

    async def list(self, workspace_id: UUID) -> list[SavedGraph]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.graphs.list(workspace_id)

    async def rename_folder(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        folder_id: UUID,
        name: str,
    ) -> GraphFolder:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_GRAPH,
            )
            folder = await unit_of_work.graphs.get_folder(workspace_id, folder_id)
            if folder is None:
                raise NotFoundError("Graph folder", str(folder_id))
            normalized_name = GraphFolder(
                workspace_id=workspace_id,
                name=name,
            ).name
            existing = await unit_of_work.graphs.get_folder_by_name(
                workspace_id,
                normalized_name,
            )
            if existing is not None and existing.id != folder.id:
                raise GraphFolderNameConflictError(
                    workspace_id=workspace_id,
                    name=normalized_name,
                )
            folder.rename(normalized_name)
            await unit_of_work.graphs.save_folder(folder)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    workspace_id=workspace_id,
                    operation="graph.folder.rename",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="graph_folder",
                    resource_id=str(folder.id),
                )
            )
            await unit_of_work.commit()
        return folder

    async def delete_folder(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_GRAPH,
            )
            folder = await unit_of_work.graphs.get_folder(workspace_id, folder_id)
            if folder is None:
                raise NotFoundError("Graph folder", str(folder_id))
            await unit_of_work.graphs.unfile_graphs_in_folder(
                workspace_id,
                folder_id,
            )
            await unit_of_work.graphs.remove_folder(folder)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    workspace_id=workspace_id,
                    operation="graph.folder.delete",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="graph_folder",
                    resource_id=str(folder.id),
                )
            )
            await unit_of_work.commit()

    async def assign_folder(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        graph_id: UUID,
        folder_id: UUID | None,
    ) -> GraphOrganization:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_GRAPH,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            if folder_id is not None:
                folder = await unit_of_work.graphs.get_folder(workspace_id, folder_id)
                if folder is None:
                    raise NotFoundError("Graph folder", str(folder_id))
            organization = await unit_of_work.graphs.get_organization(
                workspace_id=workspace_id,
                graph_id=graph_id,
            )
            if organization is None:
                organization = GraphOrganization(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                )
            organization.assign_folder(folder_id)
            await unit_of_work.graphs.save_organization(organization)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    workspace_id=workspace_id,
                    operation="graph.folder.assign",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="saved_graph",
                    resource_id=str(graph.id),
                )
            )
            await unit_of_work.commit()
        return organization

    async def archive(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> GraphOrganization:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_GRAPH,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            organization = await unit_of_work.graphs.get_organization(
                workspace_id=workspace_id,
                graph_id=graph_id,
            )
            if organization is None:
                organization = GraphOrganization(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                )
            organization.archive()
            await unit_of_work.graphs.save_organization(organization)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    workspace_id=workspace_id,
                    operation="graph.archive",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="saved_graph",
                    resource_id=str(graph.id),
                )
            )
            await unit_of_work.commit()
        return organization

    async def restore(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> GraphOrganization:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_GRAPH,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            organization = await unit_of_work.graphs.get_organization(
                workspace_id=workspace_id,
                graph_id=graph_id,
            )
            if organization is None:
                organization = GraphOrganization(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                )
            organization.restore()
            await unit_of_work.graphs.save_organization(organization)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    workspace_id=workspace_id,
                    operation="graph.restore",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="saved_graph",
                    resource_id=str(graph.id),
                )
            )
            await unit_of_work.commit()
        return organization

    async def set_starred(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        graph_id: UUID,
        starred: bool,
    ) -> UserGraphState:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.VIEW_GRAPH,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            state = await unit_of_work.graphs.get_user_state(
                workspace_id=workspace_id,
                graph_id=graph_id,
                user_id=actor.user_id,
            )
            if state is None:
                state = UserGraphState(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    user_id=actor.user_id,
                )
            state.set_starred(starred)
            await unit_of_work.graphs.save_user_state(state)
            await unit_of_work.commit()
        return state

    async def record_open(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> UserGraphState:
        async with self._unit_of_work_factory() as unit_of_work:
            await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.VIEW_GRAPH,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            state = await unit_of_work.graphs.get_user_state(
                workspace_id=workspace_id,
                graph_id=graph_id,
                user_id=actor.user_id,
            )
            if state is None:
                state = UserGraphState(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    user_id=actor.user_id,
                )
            state.record_open()
            await unit_of_work.graphs.save_user_state(state)
            await unit_of_work.commit()
        return state

    async def replace(
        self,
        graph_id: UUID,
        *,
        workspace_id: UUID,
        name: str,
        document: SavedGraphDocument,
        expected_revision: int,
    ) -> SavedGraph:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.graphs.lock_revision(
                workspace_id,
                graph_id,
                expected_revision,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            await self.apply_replacement_in_unit_of_work(
                unit_of_work,
                graph,
                name=name,
                document=document,
                expected_revision=expected_revision,
                physically_remove_orphaned_secrets=True,
            )
            try:
                await unit_of_work.commit()
            except ConcurrentWriteError as exc:
                raise SavedGraphRevisionConflictError(
                    graph_id=graph_id,
                    expected_revision=expected_revision,
                    actual_revision=None,
                ) from exc
        return graph

    async def apply_replacement_in_unit_of_work(
        self,
        unit_of_work: SavedGraphUnitOfWorkPort,
        graph: SavedGraph,
        *,
        name: str,
        document: SavedGraphDocument,
        expected_revision: int,
        physically_remove_orphaned_secrets: bool,
    ) -> SavedGraph:
        """Apply replace + secret reconciliation without committing.

        Checkpoint coordination owns the surrounding unit of work. Editors must
        not physically delete owner-managed secret rows through checkpointing,
        so callers set ``physically_remove_orphaned_secrets=False`` there.
        """
        graph.ensure_revision(expected_revision)
        previous_revision = graph.revision
        previous_document = graph.document
        await self._reconcile_node_secrets(
            unit_of_work,
            workspace_id=graph.workspace_id,
            graph_id=graph.id,
            document=document,
            physically_remove_orphaned_secrets=physically_remove_orphaned_secrets,
        )
        graph.replace(
            name=name,
            document=document,
            expected_revision=expected_revision,
        )
        await unit_of_work.graphs.add_revision(graph.snapshot())
        await self._carry_forward_compatible_materializations(
            unit_of_work,
            workspace_id=graph.workspace_id,
            graph_id=graph.id,
            previous_revision=previous_revision,
            previous_document=previous_document,
            next_document=document,
            next_revision=graph.revision,
        )
        return graph

    async def _carry_forward_compatible_materializations(
        self,
        unit_of_work: SavedGraphUnitOfWorkPort,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        previous_revision: int,
        previous_document: SavedGraphDocument,
        next_document: SavedGraphDocument,
        next_revision: int,
    ) -> None:
        materialized_outputs = getattr(unit_of_work, "materialized_outputs", None)
        if not isinstance(materialized_outputs, MaterializedNodeOutputsRepositoryPort):
            return
        previous = await materialized_outputs.list_for_graph(
            workspace_id,
            graph_id,
            previous_revision,
        )
        if not previous:
            return
        for materialization in materializations_for_compatible_nodes(
            previous_document=previous_document,
            next_document=next_document,
            previous_materializations=previous,
            next_revision=next_revision,
        ):
            await materialized_outputs.upsert(materialization)

    async def _reconcile_node_secrets(
        self,
        unit_of_work: SavedGraphUnitOfWorkPort,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        document: SavedGraphDocument,
        physically_remove_orphaned_secrets: bool,
    ) -> None:
        if not physically_remove_orphaned_secrets:
            return
        registrations = {
            registration.key: registration
            for registration in self._plugin_registry.nodes
        }
        valid_secret_bindings: set[tuple[str, str, str, int, str]] = set()
        dormant_secret_nodes: set[tuple[str, str, int]] = set()
        for node in document.nodes:
            registration = registrations.get((node.operator_id, node.operator_version))
            if registration is None:
                dormant_secret_nodes.add(
                    (node.id, node.operator_id, node.operator_version)
                )
                continue
            try:
                config = registration.node_class.config_contract.model.model_validate(
                    node.config_dict()
                ).model_dump(mode="json")
            except ValidationError:
                continue
            for declaration in registration.secret_inputs:
                try:
                    dependencies = {
                        dependency: cast(JsonValue, config[dependency])
                        for dependency in declaration.config_dependencies
                    }
                    dependency_sha256 = node_secret_dependency_sha256(dependencies)
                except (KeyError, InvalidNodeSecretDependenciesError):
                    continue
                valid_secret_bindings.add(
                    (
                        node.id,
                        declaration.name,
                        node.operator_id,
                        node.operator_version,
                        dependency_sha256,
                    )
                )

        stored_secrets = await unit_of_work.node_secrets.list_for_graph(
            workspace_id,
            graph_id,
        )
        for secret in stored_secrets:
            binding = (
                secret.node_id,
                secret.name,
                secret.operator_id,
                secret.operator_version,
                secret.dependency_sha256,
            )
            if binding in valid_secret_bindings:
                continue
            dormant_node = (
                secret.node_id,
                secret.operator_id,
                secret.operator_version,
            )
            if dormant_node in dormant_secret_nodes:
                continue
            await unit_of_work.node_secrets.remove(
                workspace_id,
                graph_id,
                secret.node_id,
                secret.name,
            )

    async def delete(
        self,
        graph_id: UUID,
        *,
        workspace_id: UUID,
        expected_revision: int,
    ) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.graphs.lock_revision(
                workspace_id,
                graph_id,
                expected_revision,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            graph.ensure_revision(expected_revision)
            await unit_of_work.graphs.remove(workspace_id, graph)
            try:
                await unit_of_work.commit()
            except ConcurrentWriteError as exc:
                raise SavedGraphRevisionConflictError(
                    graph_id=graph_id,
                    expected_revision=graph.revision,
                    actual_revision=None,
                ) from exc
