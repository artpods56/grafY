from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.domain.saved_graphs import SavedGraphRevision
from grafy_core.ports.materialized_outputs import WorkbenchUnitOfWorkPort

from grafy_api.artifact_availability import ArtifactAvailability

from grafy_api.execution.errors import GraphExecutionError

if TYPE_CHECKING:
    from grafy_api.execution.models import GraphExecutionResult


class MaterializationService:
    """Owns persisted graph-output snapshots and submitted pinned outputs."""

    def __init__(
        self,
        unit_of_work: WorkbenchUnitOfWorkPort,
        availability: ArtifactAvailability,
        saved_graphs: SavedGraphService | None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._availability = availability
        self._saved_graphs = saved_graphs

    async def saved_graph_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
    ) -> SavedGraphRevision:
        if graph_revision < 1:
            raise GraphExecutionError("Graph revision must be positive")
        if self._saved_graphs is None:
            raise GraphExecutionError(
                "Saved graph context is not configured for this workbench"
            )
        return await self._saved_graphs.get_revision(
            workspace_id,
            graph_id,
            graph_revision,
        )

    async def validate_latest_pins(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
        submitted_pins: Mapping[tuple[str, str], ArtifactOutputValue],
    ) -> None:
        if not submitted_pins:
            return
        async with self._unit_of_work as unit_of_work:
            materializations = await unit_of_work.materialized_outputs.list_for_graph(
                workspace_id,
                graph_id,
                graph_revision,
            )
        by_node = {
            materialization.node_id: materialization
            for materialization in materializations
        }

        batch = await self._availability.load(
            workspace_id,
            (
                value
                for materialization in materializations
                for port, value in materialization.outputs.items()
                if (materialization.node_id, port) in submitted_pins
            ),
        )

        for (from_node, from_port), submitted_value in submitted_pins.items():
            materialization = by_node.get(from_node)
            materialized_value = (
                materialization.outputs.get(from_port)
                if materialization is not None
                else None
            )
            if materialized_value is None or not await batch.is_accessible(
                materialized_value
            ):
                raise GraphExecutionError(
                    f"Cannot reuse upstream output {from_node!r}.{from_port!r}: "
                    "there is no accessible materialized artifact for this graph "
                    "revision. Run the upstream node too or choose "
                    "'Run with dependencies'."
                )
            if submitted_value != materialized_value:
                raise GraphExecutionError(
                    f"Pinned output {from_node!r}.{from_port!r} is not the latest "
                    f"materialized output for graph {graph_id} revision "
                    f"{graph_revision}. Refresh the graph materializations and "
                    "try again, or choose 'Run with dependencies'."
                )

    async def resolve_pinned_outputs(
        self,
        workspace_id: UUID,
        pinned_outputs: Mapping[tuple[str, str], ArtifactOutputValue],
    ) -> dict[str, dict[str, ArtifactOutputValue]]:
        batch = await self._availability.load(workspace_id, pinned_outputs.values())
        outputs: dict[str, dict[str, ArtifactOutputValue]] = {}
        for (from_node, from_port), value in pinned_outputs.items():
            context = f"Pinned output {from_node!r}.{from_port!r}"
            resolved = batch.resolve_refs(
                value,
                context=context,
            )
            for artifact in resolved:
                if not await batch.artifact_is_accessible(artifact):
                    raise GraphExecutionError(f"{context} is not accessible")
            outputs.setdefault(from_node, {})[from_port] = value
        return outputs

    async def persist_execution(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
        execution: "GraphExecutionResult",
    ) -> None:
        successful_results = [
            node_result
            for node_result in execution.node_results
            if node_result.status == "succeeded"
        ]
        if not successful_results:
            return
        async with self._unit_of_work as unit_of_work:
            for node_result in successful_results:
                await unit_of_work.materialized_outputs.upsert(
                    MaterializedNodeOutputs(
                        workspace_id=workspace_id,
                        graph_id=graph_id,
                        graph_revision=graph_revision,
                        node_id=node_result.node_id,
                        workflow_run_id=execution.workflow_run_id,
                        outputs=dict(node_result.outputs),
                        materialized_at=datetime.now(UTC),
                    )
                )
            await unit_of_work.commit()

    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
    ) -> list[MaterializedNodeOutputs]:
        await self.saved_graph_revision(workspace_id, graph_id, graph_revision)
        async with self._unit_of_work as unit_of_work:
            return await unit_of_work.materialized_outputs.list_for_graph(
                workspace_id,
                graph_id,
                graph_revision,
            )
