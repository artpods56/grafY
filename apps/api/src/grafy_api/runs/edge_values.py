"""Describe each connection's projection and conversion for the materializer.

The values themselves arrive from the result store: an ``InputSlot`` holds the
artifact reference an upstream instance produced together with the field
projection and the conversion path its connection declared. The resolver keeps
that reference. It also returns an ``EdgeTransform`` the materializer applies
when it loads the value. A port typed as a ref, and an edge that crosses a
Graph boundary, still write the converted artifact. Ports collect their slots
the way their contract says: one value, a list per incoming connection, or a
list in the node's own input-plug order.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.nodes import NodeExecutionContext
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.edge_transform import EdgeTransform
from grafy_core.runtime.materialization import write_transformed_output

from grafy_api.runs.contract import InputPortPlan, InputSlot
from grafy_api.runs.errors import NodeComputationError


@dataclass(frozen=True, slots=True)
class AssembledInputs:
    """Refs in port order, plus one transform per incoming edge."""

    values: dict[str, object]
    transforms: dict[str, tuple[EdgeTransform, ...]]


class EdgeValueResolver:
    """Keep each input slot's ref and describe the transform that follows it."""

    def __init__(self, *, values: ArtifactValues) -> None:
        self._values = values

    def describe(self, slot: InputSlot) -> tuple[ArtifactOutputValue, EdgeTransform]:
        return slot.value, _transform(slot)

    async def store(
        self,
        value: ArtifactOutputValue,
        transform: EdgeTransform,
        context: NodeExecutionContext,
        *,
        port_name: str,
    ) -> ArtifactOutputValue:
        if not transform.rewrites:
            return value
        return await write_transformed_output(
            self._values,
            value,
            transform,
            context,
            port_name=port_name,
        )

    async def assemble_inputs(
        self,
        *,
        slots: Sequence[InputSlot],
        ports: Sequence[InputPortPlan],
        context: NodeExecutionContext,
    ) -> AssembledInputs:
        plans = {plan.name: plan for plan in ports}
        slots_by_port: dict[str, list[InputSlot]] = {}
        for slot in slots:
            slots_by_port.setdefault(slot.to_port, []).append(slot)

        values: dict[str, object] = {}
        transforms: dict[str, tuple[EdgeTransform, ...]] = {}
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
            described = [self.describe(slot) for slot in ordered_slots]
            resolved = [value for value, _transform in described]
            transforms[name] = tuple(transform for _value, transform in described)
            if plan.variadic or plan.instance_plugs:
                values[name] = resolved
            elif len(resolved) == 1:
                values[name] = resolved[0]
            else:
                raise NodeComputationError(
                    f"Node {context.node_id!r} input {name!r} accepts one "
                    f"connection, got {len(resolved)}"
                )
        return AssembledInputs(values=values, transforms=transforms)


def _transform(slot: InputSlot) -> EdgeTransform:
    if slot.conversion_path:
        delivered = slot.conversion_path[-1].target.spec.key
    elif slot.projection is not None:
        delivered = slot.projection.target
    else:
        delivered = _value_key(slot.value)
    path = None if slot.projection is None else tuple(slot.projection.path)
    return EdgeTransform(
        projection_path=path,
        conversions=slot.conversion_path,
        delivered=delivered,
        label=slot.label,
    )


def _value_key(value: ArtifactOutputValue) -> ArtifactTypeKey:
    return ArtifactTypeKey(value.artifact_type, value.schema_version)


__all__ = ["AssembledInputs", "EdgeValueResolver"]
