"""Resolve compiled graph edges into one node's runtime inputs."""

from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, TypeAdapter

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
)
from grafy_core.conversions import ArtifactConversion
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.nodes import NodeExecutionContext
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import (
    ArtifactWriteContext,
    ArtifactWriterRegistry,
)
from grafy_core.runtime.resolvers import ResolverRegistry

from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.models import (
    CompiledEdge,
    CompiledNode,
)


class EdgeValueResolver:
    """Apply compiled edge transformations and assemble runtime inputs."""

    def __init__(
        self,
        *,
        resolvers: ResolverRegistry,
        writers: ArtifactWriterRegistry,
        artifacts: ArtifactService,
    ) -> None:
        self._resolvers = resolvers
        self._writers = writers
        self._artifacts = artifacts

    async def assemble_inputs(
        self,
        compiled_node: CompiledNode,
        incoming_edges: Sequence[CompiledEdge],
        outputs: Mapping[str, Mapping[str, ArtifactOutputValue]],
        workflow_run_id: UUID,
        workspace_id: UUID,
    ) -> dict[str, object]:
        values: dict[str, object] = {}
        node_request = compiled_node.request
        # Phase-local adjacency index: group the node's incoming edges by input
        # port once instead of rescanning per port.
        incoming_by_port: dict[str, list[CompiledEdge]] = {}
        for edge in incoming_edges:
            if edge.request.to_node != node_request.id:
                continue
            incoming_by_port.setdefault(edge.request.to_port, []).append(edge)
        for name, spec in compiled_node.resolved_contracts.input_contract.ports.items():
            port_edges = incoming_by_port.get(name, [])
            incoming_by_plug = {
                edge.request.to_plug: edge
                for edge in port_edges
                if edge.request.to_plug is not None
            }
            if spec.instance_plugs:
                matching_edges = [
                    incoming_by_plug[plug.id]
                    for plug in node_request.input_plugs
                    if plug.port == name
                ]
            else:
                matching_edges = port_edges

            port_values: list[ArtifactOutputValue] = []
            for edge in matching_edges:
                edge_request = edge.request
                source_ports = outputs.get(edge_request.from_node)
                if source_ports is None or edge_request.from_port not in source_ports:
                    raise GraphExecutionError(
                        f"Node {node_request.id!r} input {name!r} references "
                        f"missing output {edge_request.from_node!r}."
                        f"{edge_request.from_port!r}"
                    )
                value = source_ports[edge_request.from_port]
                if edge.projection is not None:
                    value = await self._project_value(
                        value,
                        edge,
                        workflow_run_id,
                        workspace_id,
                    )
                if edge.conversion_path:
                    value = await self._convert_value(
                        value,
                        edge,
                        workflow_run_id,
                        workspace_id,
                    )
                port_values.append(value)

            if spec.instance_plugs or spec.variadic:
                values[name] = port_values
            elif len(port_values) == 1:
                values[name] = port_values[0]
            elif len(port_values) > 1:
                raise GraphExecutionError(
                    f"Node {node_request.id!r} input {name!r} accepts one "
                    f"connection, got {len(port_values)}"
                )
        return values

    async def _project_value(
        self,
        value: ArtifactOutputValue,
        edge: CompiledEdge,
        workflow_run_id: UUID,
        workspace_id: UUID,
    ) -> ArtifactOutputValue:
        projection = edge.projection
        if projection is None:
            return value
        if isinstance(value, ArtifactRef):
            return await self._project_ref(
                value,
                edge,
                workflow_run_id,
                workspace_id,
                item_index=None,
            )

        projected_refs = [
            await self._project_ref(
                ref,
                edge,
                workflow_run_id,
                workspace_id,
                item_index=index,
            )
            for index, ref in enumerate(value.item_refs)
        ]
        sequence_metadata = dict(value.metadata)
        sequence_metadata.update(
            {
                "source_sequence_id": str(value.sequence_id),
                "projection_path": list(projection.path),
                "projection_title": projection.title,
            }
        )
        return ArtifactRefSequence(
            artifact_type=projection.target.id,
            schema_version=projection.target.schema_version,
            item_refs=projected_refs,
            ordered=value.ordered,
            index_key=value.index_key,
            metadata=sequence_metadata,
        )

    async def _project_ref(
        self,
        ref: ArtifactRef,
        edge: CompiledEdge,
        workflow_run_id: UUID,
        workspace_id: UUID,
        *,
        item_index: int | None,
    ) -> ArtifactRef:
        projection = edge.projection
        if projection is None:
            raise GraphExecutionError("A compiled projection is required")
        artifact = await self._artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None:
            raise GraphExecutionError(
                f"Cannot project missing source artifact {ref.artifact_id} for "
                f"edge {edge.request.from_node!r}.{edge.request.from_port!r} -> "
                f"{edge.request.to_node!r}.{edge.request.to_port!r}"
            )
        if artifact.ref() != ref:
            raise GraphExecutionError(
                f"Cannot project source artifact {ref.artifact_id}: repository "
                "ref does not match edge output ref"
            )
        if artifact.inline_payload is None:
            raise GraphExecutionError(
                f"Cannot project {'.'.join(projection.path)!r} from artifact "
                f"{ref.artifact_id}: source has no inline JSON payload"
            )

        projected_value: object = artifact.inline_payload
        for segment in projection.path:
            if not isinstance(projected_value, dict):
                raise GraphExecutionError(
                    f"Cannot project {'.'.join(projection.path)!r} from artifact "
                    f"{ref.artifact_id}: {segment!r} is not inside a JSON object"
                )
            mapping = cast(dict[object, object], projected_value)
            if segment not in mapping:
                raise GraphExecutionError(
                    f"Cannot project {'.'.join(projection.path)!r} from artifact "
                    f"{ref.artifact_id}: field {segment!r} is missing"
                )
            projected_value = mapping[segment]

        writer = self._writers.writer_for(projection.target)
        return await writer.write(
            projected_value,
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workflow_run_id=workflow_run_id,
                    node_run_id=uuid4(),
                    workspace_id=workspace_id,
                    node_id=edge.request.from_node,
                ),
                provenance=MaterializationProvenance(
                    refs_by_input={edge.request.from_port: (ref,)}
                ),
                item_index=item_index,
                metadata={
                    "source_artifact_id": str(ref.artifact_id),
                    "source_artifact_type": ref.artifact_type,
                    "source_schema_version": ref.schema_version,
                    "source_node_id": edge.request.from_node,
                    "source_port": edge.request.from_port,
                    "projection_path": list(projection.path),
                    "projection_title": projection.title,
                    "projection_target_artifact_type": projection.target.id,
                    "projection_target_schema_version": (
                        projection.target.schema_version
                    ),
                    "target_node_id": edge.request.to_node,
                    "target_port": edge.request.to_port,
                },
            ),
        )

    async def _convert_value(
        self,
        value: ArtifactOutputValue,
        edge: CompiledEdge,
        workflow_run_id: UUID,
        workspace_id: UUID,
    ) -> ArtifactOutputValue:
        conversions = edge.conversion_path
        if not conversions:
            return value
        final_conversion = conversions[-1]
        if isinstance(value, ArtifactRef):
            return await self._convert_ref(
                value,
                edge,
                workflow_run_id,
                workspace_id,
                item_index=None,
            )

        converted_refs = [
            await self._convert_ref(
                ref,
                edge,
                workflow_run_id,
                workspace_id,
                item_index=index,
            )
            for index, ref in enumerate(value.item_refs)
        ]
        sequence_metadata = dict(value.metadata)
        sequence_metadata.update(
            {
                "source_sequence_id": str(value.sequence_id),
                **_conversion_path_metadata(conversions),
            }
        )
        return ArtifactRefSequence(
            artifact_type=final_conversion.target.id,
            schema_version=final_conversion.target.schema_version,
            item_refs=converted_refs,
            ordered=value.ordered,
            index_key=value.index_key,
            metadata=sequence_metadata,
        )

    async def _convert_ref(
        self,
        ref: ArtifactRef,
        edge: CompiledEdge,
        workflow_run_id: UUID,
        workspace_id: UUID,
        *,
        item_index: int | None,
    ) -> ArtifactRef:
        conversions = edge.conversion_path
        if not conversions:
            raise GraphExecutionError("A compiled conversion path is required")
        first_conversion = conversions[0]
        final_conversion = conversions[-1]
        item_context = "" if item_index is None else f" at sequence item {item_index}"
        try:
            source_value = await self._resolvers.resolve(
                ref=ref,
                target=first_conversion.source_type,
                workspace_id=workspace_id,
            )
            converted_value: object = _validated_conversion_value(
                source_value,
                first_conversion.source_type,
            )
        except Exception as exc:
            raise GraphExecutionError(
                f"Failed to resolve artifact {ref.artifact_id}{item_context} for "
                "conversion path on edge "
                f"{edge.request.from_node!r}.{edge.request.from_port!r} -> "
                f"{edge.request.to_node!r}.{edge.request.to_port!r}"
            ) from exc

        for step_index, conversion in enumerate(conversions):
            try:
                step_input = _validated_conversion_value(
                    converted_value,
                    conversion.source_type,
                )
                converted_value = _validated_conversion_value(
                    conversion.convert(step_input),
                    conversion.target_type,
                )
            except Exception as exc:
                raise GraphExecutionError(
                    f"Failed conversion step {step_index + 1}/{len(conversions)} "
                    f"{conversion.key.id!r}@{conversion.key.version} for artifact "
                    f"{ref.artifact_id}{item_context} on edge "
                    f"{edge.request.from_node!r}.{edge.request.from_port!r} -> "
                    f"{edge.request.to_node!r}.{edge.request.to_port!r}"
                ) from exc

        metadata: dict[str, object] = {
            "source_artifact_id": str(ref.artifact_id),
            "source_artifact_type": ref.artifact_type,
            "source_schema_version": ref.schema_version,
            "source_node_id": edge.request.from_node,
            "source_port": edge.request.from_port,
            **_conversion_path_metadata(conversions),
            "conversion_source_artifact_type": first_conversion.source.id,
            "conversion_source_schema_version": first_conversion.source.schema_version,
            "conversion_target_artifact_type": final_conversion.target.id,
            "conversion_target_schema_version": final_conversion.target.schema_version,
            "target_node_id": edge.request.to_node,
            "target_port": edge.request.to_port,
        }
        try:
            writer = self._writers.writer_for(final_conversion.target)
            written_ref = await writer.write(
                converted_value,
                ArtifactWriteContext(
                    node_context=NodeExecutionContext(
                        workflow_run_id=workflow_run_id,
                        node_run_id=uuid4(),
                        workspace_id=workspace_id,
                        node_id=edge.request.from_node,
                    ),
                    provenance=MaterializationProvenance(
                        refs_by_input={edge.request.from_port: (ref,)}
                    ),
                    item_index=item_index,
                    metadata=metadata,
                ),
            )
            if written_ref.key() != final_conversion.target:
                raise GraphExecutionError(
                    f"Final conversion writer returned {written_ref.artifact_type}@"
                    f"{written_ref.schema_version}, expected "
                    f"{final_conversion.target.id}@"
                    f"{final_conversion.target.schema_version} for artifact "
                    f"{ref.artifact_id}{item_context} on edge "
                    f"{edge.request.from_node!r}.{edge.request.from_port!r} -> "
                    f"{edge.request.to_node!r}.{edge.request.to_port!r}"
                )
            return written_ref
        except GraphExecutionError:
            raise
        except Exception as exc:
            raise GraphExecutionError(
                "Failed to materialize final target "
                f"{final_conversion.target.id}@"
                f"{final_conversion.target.schema_version} for conversion path "
                f"from artifact {ref.artifact_id}{item_context} on edge "
                f"{edge.request.from_node!r}.{edge.request.from_port!r} -> "
                f"{edge.request.to_node!r}.{edge.request.to_port!r}"
            ) from exc


def _conversion_path_metadata(
    conversions: tuple[ArtifactConversion[Any, Any], ...],
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "conversion_path": [
            {
                "id": conversion.key.id,
                "version": conversion.key.version,
            }
            for conversion in conversions
        ],
        "conversion_titles": [conversion.title for conversion in conversions],
    }
    if len(conversions) == 1:
        conversion = conversions[0]
        metadata.update(
            {
                "conversion_id": conversion.key.id,
                "conversion_version": conversion.key.version,
                "conversion_title": conversion.title,
            }
        )
    return metadata


def _validated_conversion_value[ValueT](
    value: object,
    target: type[ValueT],
) -> ValueT:
    if issubclass(target, BaseModel):
        if not isinstance(value, target):
            raise TypeError(
                f"Expected {target.__module__}.{target.__qualname__}, got "
                f"{type(value).__module__}.{type(value).__qualname__}"
            )
        raw_value = value.model_dump(mode="python", round_trip=True)
        return target.model_validate(raw_value, strict=True)
    return TypeAdapter(
        target,
        config=ConfigDict(arbitrary_types_allowed=True),
    ).validate_python(value, strict=True)
