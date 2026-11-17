"""Apply each connection's projection and conversion to the values one node reads.

The values themselves arrive from the result store: an ``InputSlot`` holds the
artifact reference an upstream instance produced together with the field
projection and the conversion path its connection declared. Applying them writes
new artifacts -- a projection or a conversion is a materialized value with its
own provenance, which points at the upstream artifact it was derived from and at
the node it is on its way to -- and the results are what the node's inputs
materialize. Ports collect their slots the way their contract says: one value, a
list per incoming connection, or a list in the node's own input-plug order.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.conversions import Conversion
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.nodes import NodeExecutionContext
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext

from grafy_api.runs.contract import InputPortPlan, InputSlot
from grafy_api.runs.errors import NodeComputationError


class EdgeValueResolver:
    """Resolve input slots into the values a node runtime materializes."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWorkPort,
        values: ArtifactValues,
    ) -> None:
        self._uow = unit_of_work
        self._values = values

    async def _read(self, ref: ArtifactRef, workspace_id: UUID) -> object:
        return await self._values.resolve(ref, workspace_id)

    async def _store(
        self,
        key: ArtifactTypeKey,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        return await self._values.write(key, value, context)

    async def assemble_inputs(
        self,
        *,
        slots: Sequence[InputSlot],
        ports: Sequence[InputPortPlan],
        context: NodeExecutionContext,
    ) -> dict[str, object]:
        plans = {plan.name: plan for plan in ports}
        slots_by_port: dict[str, list[InputSlot]] = {}
        for slot in slots:
            slots_by_port.setdefault(slot.to_port, []).append(slot)

        values: dict[str, object] = {}
        for name, port_slots in slots_by_port.items():
            plan = plans.get(name)
            if plan is None:
                raise NodeComputationError(
                    f"Input {name!r} of node {context.node_id!r} has connections "
                    "but is not an input port of its operator"
                )
            if not plan.instance_plugs:
                ordered_slots = port_slots
            else:
                by_plug = {
                    slot.to_plug: slot
                    for slot in port_slots
                    if slot.to_plug is not None
                }
                missing = [plug for plug in plan.plugs if plug not in by_plug]
                if missing:
                    raise NodeComputationError(
                        f"Input {plan.name!r} declares plugs that carry no value: "
                        + ", ".join(repr(plug) for plug in missing)
                    )
                ordered_slots = [by_plug[plug] for plug in plan.plugs]
            resolved = [await self.resolve(slot, context) for slot in ordered_slots]
            if plan.variadic or plan.instance_plugs:
                values[name] = resolved
            elif len(resolved) == 1:
                values[name] = resolved[0]
            else:
                raise NodeComputationError(
                    f"Node {context.node_id!r} input {name!r} accepts one "
                    f"connection, got {len(resolved)}"
                )
        return values

    async def resolve(
        self,
        slot: InputSlot,
        context: NodeExecutionContext,
    ) -> ArtifactOutputValue:
        value = slot.value
        if slot.projection is not None:
            projection = slot.projection
            if isinstance(value, ArtifactRef):
                value = await self._project_ref(value, slot, context, item_index=None)
            else:
                projected_refs = [
                    await self._project_ref(ref, slot, context, item_index=index)
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
                value = ArtifactRefSequence(
                    artifact_type=projection.target.id,
                    schema_version=projection.target.schema_version,
                    item_refs=projected_refs,
                    ordered=value.ordered,
                    index_key=value.index_key,
                    metadata=sequence_metadata,
                )
        if slot.conversion_path:
            conversions = slot.conversion_path
            final_conversion = conversions[-1]
            if isinstance(value, ArtifactRef):
                value = await self._convert_ref(value, slot, context, item_index=None)
            else:
                converted_refs = [
                    await self._convert_ref(ref, slot, context, item_index=index)
                    for index, ref in enumerate(value.item_refs)
                ]
                sequence_metadata = dict(value.metadata)
                sequence_metadata.update(
                    {
                        "source_sequence_id": str(value.sequence_id),
                        **_conversion_path_metadata(conversions),
                    }
                )
                target_key = final_conversion.target.spec.key
                value = ArtifactRefSequence(
                    artifact_type=target_key.id,
                    schema_version=target_key.schema_version,
                    item_refs=converted_refs,
                    ordered=value.ordered,
                    index_key=value.index_key,
                    metadata=sequence_metadata,
                )
        return value

    async def _project_ref(
        self,
        ref: ArtifactRef,
        slot: InputSlot,
        context: NodeExecutionContext,
        *,
        item_index: int | None,
    ) -> ArtifactRef:
        projection = slot.projection
        if projection is None:
            raise NodeComputationError("A resolved projection is required")
        async with self._uow as uow:
            artifact = await uow.artifacts.get(context.workspace_id, ref.artifact_id)
        if artifact is None:
            raise NodeComputationError(
                f"Cannot project missing source artifact {ref.artifact_id} for "
                f"{slot.label}"
            )
        if artifact.ref() != ref:
            raise NodeComputationError(
                f"Cannot project source artifact {ref.artifact_id}: repository "
                "ref does not match the value the connection carries"
            )
        if artifact.inline_payload is None:
            raise NodeComputationError(
                f"Cannot project {'.'.join(projection.path)!r} from artifact "
                f"{ref.artifact_id}: source has no inline JSON payload"
            )

        projected_value: object = artifact.inline_payload
        for segment in projection.path:
            if not isinstance(projected_value, dict):
                raise NodeComputationError(
                    f"Cannot project {'.'.join(projection.path)!r} from artifact "
                    f"{ref.artifact_id}: {segment!r} is not inside a JSON object"
                )
            mapping = cast(dict[object, object], projected_value)
            if segment not in mapping:
                raise NodeComputationError(
                    f"Cannot project {'.'.join(projection.path)!r} from artifact "
                    f"{ref.artifact_id}: field {segment!r} is missing"
                )
            projected_value = mapping[segment]

        return await self._store(
            projection.target,
            projected_value,
            ArtifactWriteContext(
                node_context=replace(context, node_id=slot.source_node_id),
                provenance=MaterializationProvenance(
                    refs_by_input={slot.source_port: (ref,)}
                ),
                item_index=item_index,
                metadata={
                    "source_artifact_id": str(ref.artifact_id),
                    "source_artifact_type": ref.artifact_type,
                    "source_schema_version": ref.schema_version,
                    "source_node_id": slot.source_node_id,
                    "source_port": slot.source_port,
                    "projection_path": list(projection.path),
                    "projection_title": projection.title,
                    "projection_target_artifact_type": projection.target.id,
                    "projection_target_schema_version": (
                        projection.target.schema_version
                    ),
                    "target_node_id": slot.target_node_id,
                    "target_port": slot.to_port,
                },
            ),
        )

    async def _convert_ref(
        self,
        ref: ArtifactRef,
        slot: InputSlot,
        context: NodeExecutionContext,
        *,
        item_index: int | None,
    ) -> ArtifactRef:
        conversions = slot.conversion_path
        if not conversions:
            raise NodeComputationError("A resolved conversion path is required")
        first_conversion = conversions[0]
        final_conversion = conversions[-1]
        item_context = "" if item_index is None else f" at sequence item {item_index}"
        source_key = first_conversion.source.spec.key
        target_key = final_conversion.target.spec.key
        try:
            converted_value: object = await self._read(ref, context.workspace_id)
        except Exception as exc:
            raise NodeComputationError(
                f"Failed to resolve artifact {ref.artifact_id}{item_context} for "
                f"the conversion path on {slot.label}"
            ) from exc

        for step_index, conversion in enumerate(conversions):
            try:
                converted_value = await conversion.convert(cast(Any, converted_value))
            except Exception as exc:
                raise NodeComputationError(
                    f"Failed conversion step {step_index + 1}/{len(conversions)} "
                    f"{conversion.id!r}@{conversion.version} for artifact "
                    f"{ref.artifact_id}{item_context} on {slot.label}"
                ) from exc

        metadata: dict[str, object] = {
            "source_artifact_id": str(ref.artifact_id),
            "source_artifact_type": ref.artifact_type,
            "source_schema_version": ref.schema_version,
            "source_node_id": slot.source_node_id,
            "source_port": slot.source_port,
            **_conversion_path_metadata(conversions),
            "conversion_source_artifact_type": source_key.id,
            "conversion_source_schema_version": source_key.schema_version,
            "conversion_target_artifact_type": target_key.id,
            "conversion_target_schema_version": target_key.schema_version,
            "target_node_id": slot.target_node_id,
            "target_port": slot.to_port,
        }
        try:
            written_ref = await self._store(
                target_key,
                converted_value,
                ArtifactWriteContext(
                    node_context=replace(context, node_id=slot.source_node_id),
                    provenance=MaterializationProvenance(
                        refs_by_input={slot.source_port: (ref,)}
                    ),
                    item_index=item_index,
                    metadata=metadata,
                ),
            )
            if written_ref.key() != target_key:
                raise NodeComputationError(
                    f"Final conversion writer returned {written_ref.artifact_type}@"
                    f"{written_ref.schema_version}, expected "
                    f"{target_key.id}@"
                    f"{target_key.schema_version} for artifact "
                    f"{ref.artifact_id}{item_context} on {slot.label}"
                )
            return written_ref
        except NodeComputationError:
            raise
        except Exception as exc:
            raise NodeComputationError(
                "Failed to materialize final target "
                f"{target_key.id}@"
                f"{target_key.schema_version} for the conversion path "
                f"from artifact {ref.artifact_id}{item_context} on {slot.label}"
            ) from exc


def _conversion_path_metadata(
    conversions: tuple[Conversion[Any, Any], ...],
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "conversion_path": [
            {
                "id": conversion.id,
                "version": conversion.version,
            }
            for conversion in conversions
        ],
        "conversion_titles": [conversion.title for conversion in conversions],
    }
    if len(conversions) == 1:
        conversion = conversions[0]
        metadata.update(
            {
                "conversion_id": conversion.id,
                "conversion_version": conversion.version,
                "conversion_title": conversion.title,
            }
        )
    return metadata


__all__ = ["EdgeValueResolver"]
