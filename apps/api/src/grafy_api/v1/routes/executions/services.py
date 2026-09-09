import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from grafy_core.artifacts import ArtifactObject, ArtifactRef, ArtifactRefSequence
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.table_contracts import TABLE_DATA

from grafy_api.v1.routes.artifacts.models import (
    ArtifactExportFormatResponse,
    ArtifactSummaryResponse,
)
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.artifact_availability import (
    ArtifactAvailability,
    ArtifactAvailabilityBatch,
)

from .models import (
    GraphMaterializationsResponse,
    RunExecutionResponse,
    RunNodeResponse,
    RunPortOutputResponse,
    RunResponse,
)

if TYPE_CHECKING:
    from grafy_api.execution.manager import RunExecutionSnapshot
    from grafy_api.execution.models import GraphExecutionResult


INLINE_SUMMARY_TEXT_BYTE_LIMIT = 64 * 1_024


class RunResultPresenter:
    """Maps graph execution and materialization results to HTTP response models."""

    def __init__(
        self, artifacts: ArtifactService, availability: ArtifactAvailability
    ) -> None:
        self._artifacts = artifacts
        self._availability = availability

    async def run_response(
        self,
        workspace_id: UUID,
        execution: "GraphExecutionResult",
    ) -> RunResponse:
        batch = await self._availability.load(
            workspace_id,
            (
                value
                for node in execution.node_results
                for value in node.outputs.values()
            ),
        )
        return RunResponse(
            status=execution.status,
            node_runs=[
                RunNodeResponse(
                    node_id=node_result.node_id,
                    status=node_result.status,
                    error=node_result.error,
                    outputs=[
                        self._port_output_response(
                            batch,
                            port_name,
                            value,
                        )
                        for port_name, value in node_result.outputs.items()
                    ],
                )
                for node_result in execution.node_results
            ],
        )

    async def execution_response(
        self,
        execution: "RunExecutionSnapshot",
    ) -> RunExecutionResponse:
        result = None
        if execution.result is not None:
            result = await self.run_response(
                execution.workspace_id,
                execution.result,
            )
        return RunExecutionResponse(
            execution_id=execution.execution_id,
            status=execution.status,
            active_node_id=execution.active_node_id,
            result=result,
            error=execution.error,
            queue_position=execution.queue_position,
        )

    async def materializations_response(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
        materializations: Sequence[MaterializedNodeOutputs],
    ) -> GraphMaterializationsResponse:
        batch = await self._availability.load(
            workspace_id,
            (value for item in materializations for value in item.outputs.values()),
        )
        node_runs: list[RunNodeResponse] = []
        for materialization in materializations:
            accessible_outputs: list[RunPortOutputResponse] = []
            for port_name, value in materialization.outputs.items():
                if await batch.is_accessible(value):
                    accessible_outputs.append(
                        self._port_output_response(
                            batch,
                            port_name,
                            value,
                        )
                    )
            if materialization.outputs and not accessible_outputs:
                continue
            node_runs.append(
                RunNodeResponse(
                    node_id=materialization.node_id,
                    status="succeeded",
                    error=None,
                    outputs=accessible_outputs,
                )
            )
        return GraphMaterializationsResponse(
            graph_id=graph_id,
            graph_revision=graph_revision,
            node_runs=node_runs,
        )

    async def port_output_response(
        self,
        workspace_id: UUID,
        port_name: str,
        value: ArtifactOutputValue,
    ) -> RunPortOutputResponse:
        batch = await self._availability.load(workspace_id, [value])
        return self._port_output_response(batch, port_name, value)

    def _port_output_response(
        self,
        batch: ArtifactAvailabilityBatch,
        port_name: str,
        value: ArtifactOutputValue,
    ) -> RunPortOutputResponse:
        if isinstance(value, ArtifactRefSequence):
            refs = list(value.item_refs)
            kind: Literal["single", "sequence"] = "sequence"
        else:
            refs = [value]
            kind = "single"
        return RunPortOutputResponse(
            port=port_name,
            kind=kind,
            value=value,
            artifacts=[
                self.artifact_summary(ref, batch.artifacts.get(ref.artifact_id))
                for ref in refs
            ],
        )

    def artifact_summary(
        self,
        ref: ArtifactRef,
        artifact: ArtifactObject | None,
    ) -> ArtifactSummaryResponse:
        if artifact is None:
            return ArtifactSummaryResponse(
                artifact_id=ref.artifact_id,
                artifact_type=ref.artifact_type,
                schema_version=ref.schema_version,
                content_type="application/octet-stream",
            )
        text: str | None = None
        include_inline_text = (
            artifact.inline_payload is not None
            and artifact.artifact_type != TABLE_DATA.key.id
            and artifact.byte_size is not None
            and artifact.byte_size <= INLINE_SUMMARY_TEXT_BYTE_LIMIT
        )
        if include_inline_text and artifact.inline_payload is not None:
            payload_text = artifact.inline_payload.get("text")
            if isinstance(payload_text, str):
                text = payload_text
            payload_markdown = artifact.inline_payload.get("markdown")
            if text is None and isinstance(payload_markdown, str):
                text = payload_markdown
            if text is None:
                if set(artifact.inline_payload) == {"value"}:
                    text = json.dumps(
                        artifact.inline_payload["value"],
                        ensure_ascii=False,
                    )
                else:
                    text = json.dumps(
                        artifact.inline_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
        return ArtifactSummaryResponse(
            artifact_id=artifact.id,
            artifact_type=artifact.artifact_type,
            schema_version=artifact.schema_version,
            content_type=artifact.content_type,
            byte_size=artifact.byte_size,
            sha256=artifact.sha256,
            text=text,
            content_url=f"./artifacts/{artifact.id}/content",
            download_formats=[
                ArtifactExportFormatResponse.from_export_format(export_format)
                for export_format in self._artifacts.export_formats(artifact)
            ],
            metadata=artifact.metadata,
        )


__all__ = ["RunResultPresenter"]
