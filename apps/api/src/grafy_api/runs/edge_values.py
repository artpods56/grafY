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

from pydantic import BaseModel, ConfigDict, TypeAdapter

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.conversions import ArtifactConversion
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.nodes import NodeExecutionContext
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext, ArtifactWriterRegistry
from grafy_core.runtime.resolvers import ResolverRegistry

from grafy_api.runs.contract import InputPortPlan, InputSlot
from grafy_api.runs.errors import NodeComputationError


class EdgeValueResolver:
    """Resolve input slots into the values a node runtime materializes."""

    def __init__(
        self,
        *,
        resolvers: ResolverRegistry,
        writers: ArtifactWriterRegistry,
        unit_of_work: UnitOfWorkPort,
    ) -> None:
        self._resolvers = resolvers
        self._writers = writers
        self._unit_of_work = unit_of_work

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
            resolved = [
                await self.resolve(slot, context)
                for slot in _in_port_order(plan, port_slots)
            ]
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
            value = await self._project_value(value, slot, context)
        if slot.conversion_path:
            value = await self._convert_value(value, slot, context)
        return value

    async def _project_value(
        self,
        value: ArtifactOutputValue,
        slot: InputSlot,
        context: NodeExecutionContext,
    ) -> ArtifactOutputValue:
        projection = slot.projection
        if projection is None:
            return value
        if isinstance(value, ArtifactRef):
            return await self._project_ref(value, slot, context, item_index=None)

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
        slot: InputSlot,
        context: NodeExecutionContext,
        *,
        item_index: int | None,
    ) -> ArtifactRef:
        projection = slot.projection
        if projection is None:
            raise NodeComputationError("A resolved projection is required")
        async with self._unit_of_work as unit_of_work:
            artifact = await unit_of_work.artifacts.get(
                context.workspace_id, ref.artifact_id
            )
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

        writer = self._writers.writer_for(projection.target)
        return await writer.write(
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

    async def _convert_value(
        self,
        value: ArtifactOutputValue,
        slot: InputSlot,
        context: NodeExecutionContext,
    ) -> ArtifactOutputValue:
        conversions = slot.conversion_path
        if not conversions:
            return value
        final_conversion = conversions[-1]
        if isinstance(value, ArtifactRef):
            return await self._convert_ref(value, slot, context, item_index=None)

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
        try:
            source_value = await self._resolvers.resolve(
                ref=ref,
                target=first_conversion.source_type,
                workspace_id=context.workspace_id,
            )
            converted_value: object = _validated_conversion_value(
                source_value,
                first_conversion.source_type,
            )
        except Exception as exc:
            raise NodeComputationError(
                f"Failed to resolve artifact {ref.artifact_id}{item_context} for "
                f"the conversion path on {slot.label}"
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
                raise NodeComputationError(
                    f"Failed conversion step {step_index + 1}/{len(conversions)} "
                    f"{conversion.key.id!r}@{conversion.key.version} for artifact "
                    f"{ref.artifact_id}{item_context} on {slot.label}"
                ) from exc

        metadata: dict[str, object] = {
            "source_artifact_id": str(ref.artifact_id),
            "source_artifact_type": ref.artifact_type,
            "source_schema_version": ref.schema_version,
            "source_node_id": slot.source_node_id,
            "source_port": slot.source_port,
            **_conversion_path_metadata(conversions),
            "conversion_source_artifact_type": first_conversion.source.id,
            "conversion_source_schema_version": first_conversion.source.schema_version,
            "conversion_target_artifact_type": final_conversion.target.id,
            "conversion_target_schema_version": final_conversion.target.schema_version,
            "target_node_id": slot.target_node_id,
            "target_port": slot.to_port,
        }
        try:
            writer = self._writers.writer_for(final_conversion.target)
            written_ref = await writer.write(
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
            if written_ref.key() != final_conversion.target:
                raise NodeComputationError(
                    f"Final conversion writer returned {written_ref.artifact_type}@"
                    f"{written_ref.schema_version}, expected "
                    f"{final_conversion.target.id}@"
                    f"{final_conversion.target.schema_version} for artifact "
                    f"{ref.artifact_id}{item_context} on {slot.label}"
                )
            return written_ref
        except NodeComputationError:
            raise
        except Exception as exc:
            raise NodeComputationError(
                "Failed to materialize final target "
                f"{final_conversion.target.id}@"
                f"{final_conversion.target.schema_version} for the conversion path "
                f"from artifact {ref.artifact_id}{item_context} on {slot.label}"
            ) from exc


def _in_port_order(
    plan: InputPortPlan,
    slots: Sequence[InputSlot],
) -> Sequence[InputSlot]:
    """Order a plug port's values by the node's own plug order."""

    if not plan.instance_plugs:
        return slots
    by_plug = {slot.to_plug: slot for slot in slots if slot.to_plug is not None}
    missing = [plug for plug in plan.plugs if plug not in by_plug]
    if missing:
        raise NodeComputationError(
            f"Input {plan.name!r} declares plugs that carry no value: "
            + ", ".join(repr(plug) for plug in missing)
        )
    return [by_plug[plug] for plug in plan.plugs]


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


__all__ = ["EdgeValueResolver"]
