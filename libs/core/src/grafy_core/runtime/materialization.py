from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, cast
from uuid import UUID

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.conversions import ArtifactConversionKey
from grafy_core.nodes import (
    InputContract,
    InputPortSpec,
    NodeExecutionContext,
    PortShape,
)
from grafy_core.runtime.edge_transform import (
    EdgeTransform,
    EdgeTransformError,
    apply_edge_transform,
)

if TYPE_CHECKING:
    from grafy_core.runtime.artifact_values import ArtifactValues


class MaterializationError(RuntimeError):
    def __init__(self, port_name: str, message: str) -> None:
        super().__init__(f"Input {port_name!r} {message}")
        self.port_name = port_name


@dataclass(frozen=True, slots=True)
class InputDerivation:
    """Projection path or conversion keys applied to one upstream ref."""

    projection_path: tuple[str, ...] | None = None
    conversion_keys: tuple[ArtifactConversionKey, ...] = ()


def _empty_derivations() -> dict[str, tuple[InputDerivation, ...]]:
    return {}


@dataclass(frozen=True, slots=True)
class MaterializationProvenance:
    refs_by_input: dict[str, tuple[ArtifactRef, ...]]
    derivations_by_input: dict[str, tuple[InputDerivation, ...]] = field(
        default_factory=_empty_derivations
    )

    def refs_for(self, input_name: str) -> tuple[ArtifactRef, ...]:
        return self.refs_by_input.get(input_name, ())


_EXPECTED_PORT_VALUE: Final = {
    (False, PortShape.ONE): "an ArtifactRef",
    (False, PortShape.MANY): (
        "an ArtifactRefSequence (wrap refs in an ArtifactRefSequence)"
    ),
    (True, PortShape.ONE): "a list with one ArtifactRef per incoming edge",
    (True, PortShape.MANY): "a list with one ArtifactRefSequence per incoming edge",
}


class InputMaterializer:
    def __init__(self, values: "ArtifactValues | None" = None) -> None:
        self._values = values

    async def _resolve_value(
        self,
        name: str,
        ref: ArtifactRef,
        value_types: tuple[type[object], ...],
        workspace_id: UUID,
    ) -> object:
        values = self._values
        if values is None or values.declaration_for(ref.key()) is None:
            raise MaterializationError(
                name,
                "has no artifact declaration for "
                f"{ref.artifact_type}@{ref.schema_version}",
            )
        resolved = await values.resolve(ref, workspace_id)
        if type(resolved) not in value_types:
            expected = " or ".join(value_type.__name__ for value_type in value_types)
            raise MaterializationError(
                name,
                f"resolved {type(resolved).__name__}, expected {expected}",
            )
        return resolved

    async def materialize[T: BaseModel](
        self,
        contract: InputContract[T],
        inputs: Mapping[str, object],
        workspace_id: UUID,
        transforms: Mapping[str, Sequence[EdgeTransform]] | None = None,
        node_context: NodeExecutionContext | None = None,
        item_index: int | None = None,
    ) -> tuple[T, MaterializationProvenance]:
        values: dict[str, object] = {}
        refs_by_input: dict[str, tuple[ArtifactRef, ...]] = {}
        derivations_by_input: dict[str, tuple[InputDerivation, ...]] = {}
        execution = node_context or NodeExecutionContext(workspace_id=workspace_id)

        for name in contract.model.model_fields:
            if name in inputs:
                values[name] = inputs[name]

        for name, spec in contract.ports.items():
            if name not in inputs:
                if spec.required:
                    raise MaterializationError(name, "is required")
                continue

            accepted_types = spec.accepted_types
            if not accepted_types:
                raise MaterializationError(
                    name,
                    "has an unresolved artifact type contract",
                )

            value = inputs[name]
            if value is None and spec.allows_none:
                values[name] = None
                continue

            # Normalize every legal input into one canonical form: a list of
            # refs per incoming edge. `carriers` keeps the sequence object an
            # edge came from, so an identity ref port can hand that object back.
            edges: list[list[ArtifactRef]] = []
            carriers: list[ArtifactRefSequence | None] = []
            if spec.instance_plugs:
                if not isinstance(value, list):
                    expected = (
                        "ArtifactRef or ArtifactRefSequence"
                        if spec.preserves_ref_container
                        else "ArtifactRef"
                    )
                    raise MaterializationError(
                        name,
                        f"expected a list with one {expected} per incoming "
                        "plug, got "
                        f"{type(value).__name__}",
                    )
                for item in cast(list[object], value):
                    if isinstance(item, ArtifactRef):
                        edges.append([item])
                        carriers.append(None)
                        continue
                    if isinstance(item, ArtifactRefSequence) and (
                        spec.preserves_ref_container
                    ):
                        edges.append(list(item.item_refs))
                        carriers.append(item)
                        continue
                    expected = (
                        "an ArtifactRef or ArtifactRefSequence"
                        if spec.preserves_ref_container
                        else "an ArtifactRef"
                    )
                    raise MaterializationError(
                        name,
                        f"expected {expected} per incoming plug, got "
                        f"{type(item).__name__}",
                    )
            else:
                match spec.variadic, spec.shape, value:
                    case False, PortShape.ONE, ArtifactRef() as ref:
                        edges = [[ref]]
                        carriers = [None]
                    case False, PortShape.MANY, ArtifactRefSequence() as sequence:
                        edges = [list(sequence.item_refs)]
                        carriers = [sequence]
                    case True, PortShape.ONE, list() | tuple():
                        for item in cast(Sequence[object], value):
                            if not isinstance(item, ArtifactRef):
                                raise MaterializationError(
                                    name,
                                    "expected one ArtifactRef per incoming edge, "
                                    f"got {type(item).__name__}",
                                )
                            edges.append([item])
                            carriers.append(None)
                    case True, PortShape.MANY, list() | tuple():
                        for item in cast(Sequence[object], value):
                            if not isinstance(item, ArtifactRefSequence):
                                raise MaterializationError(
                                    name,
                                    "expected one ArtifactRefSequence per incoming "
                                    f"edge, got {type(item).__name__}",
                                )
                            edges.append(list(item.item_refs))
                            carriers.append(item)
                    case _:
                        expected = _EXPECTED_PORT_VALUE[(spec.variadic, spec.shape)]
                        raise MaterializationError(
                            name,
                            f"expected {expected}, got {type(value).__name__}",
                        )

            if spec.variadic and len(edges) == 0 and spec.required:
                raise MaterializationError(name, "expected at least one incoming edge")

            port_transforms = _port_transforms(name, len(edges), transforms)
            for edge, carrier, transform in zip(
                edges, carriers, port_transforms, strict=True
            ):
                _check_edge_type(
                    name,
                    edge,
                    carrier,
                    transform,
                    accepted_types,
                )
            refs = tuple(ref for edge in edges for ref in edge)
            if len(refs) > 0:
                refs_by_input[name] = refs
            derivations = _derivations(edges, port_transforms)
            if any(
                item.projection_path is not None or item.conversion_keys
                for item in derivations
            ):
                derivations_by_input[name] = tuple(derivations)

            if spec.preserves_ref_container:
                if not any(
                    transform is not None and transform.rewrites
                    for transform in port_transforms
                ):
                    values[name] = value
                    continue
                values[name] = await self._store_ref_edges(
                    name=name,
                    spec=spec,
                    value=cast(object, value),
                    edges=edges,
                    carriers=carriers,
                    transforms=port_transforms,
                    context=execution,
                    item_index=item_index,
                )
                continue

            value_types = spec.value_types
            if len(value_types) == 0:
                raise MaterializationError(
                    name, "does not declare a resolvable Python value type"
                )
            resolved = [
                [
                    await self._port_value(
                        name,
                        ref,
                        transform,
                        value_types,
                        workspace_id,
                        item_index=_item_index(
                            sequenced=carrier is not None,
                            position=position,
                            outer=item_index,
                        ),
                    )
                    for position, ref in enumerate(edge)
                ]
                for edge, carrier, transform in zip(
                    edges, carriers, port_transforms, strict=True
                )
            ]
            match spec.variadic, spec.shape:
                case False, PortShape.ONE:
                    values[name] = resolved[0][0]
                case False, PortShape.MANY:
                    values[name] = resolved[0]
                case True, PortShape.ONE:
                    values[name] = [edge[0] for edge in resolved]
                case True, PortShape.MANY:
                    values[name] = resolved

        return contract.model.model_validate(values), MaterializationProvenance(
            refs_by_input=refs_by_input,
            derivations_by_input=derivations_by_input,
        )

    async def _port_value(
        self,
        name: str,
        ref: ArtifactRef,
        transform: EdgeTransform | None,
        value_types: tuple[type[object], ...],
        workspace_id: UUID,
        *,
        item_index: int | None,
    ) -> object:
        if transform is None or not transform.rewrites:
            return await self._resolve_value(name, ref, value_types, workspace_id)
        loaded = await apply_edge_transform(
            self._require_values(name),
            ref,
            transform,
            workspace_id,
            item_index=item_index,
        )
        if type(loaded) not in value_types:
            expected = " or ".join(value_type.__name__ for value_type in value_types)
            raise MaterializationError(
                name,
                f"resolved {type(loaded).__name__}, expected {expected}",
            )
        return loaded

    def _require_values(self, name: str) -> "ArtifactValues":
        values = self._values
        if values is None:
            raise MaterializationError(name, "has no artifact values to read")
        return values

    async def _store_ref_edges(
        self,
        *,
        name: str,
        spec: InputPortSpec,
        value: object,
        edges: list[list[ArtifactRef]],
        carriers: list[ArtifactRefSequence | None],
        transforms: list[EdgeTransform | None],
        context: NodeExecutionContext,
        item_index: int | None,
    ) -> object:
        reader = self._require_values(name)
        if spec.instance_plugs or spec.variadic:
            items = cast(list[object], value)
            return [
                await _stored_edge(
                    reader,
                    item,
                    edge,
                    carrier,
                    transform,
                    context,
                    port_name=name,
                    item_index=item_index,
                )
                for item, edge, carrier, transform in zip(
                    items, edges, carriers, transforms, strict=True
                )
            ]
        return await _stored_edge(
            reader,
            value,
            edges[0],
            carriers[0],
            transforms[0],
            context,
            port_name=name,
            item_index=item_index,
        )


def _artifact_type_keys_label(keys: Sequence[ArtifactTypeKey]) -> str:
    return ", ".join(f"{key.id}@{key.schema_version}" for key in keys)


def _validate_sequence_key(
    port_name: str,
    sequence: ArtifactRefSequence,
    expected: Sequence[ArtifactTypeKey],
) -> None:
    if ArtifactTypeKey(sequence.artifact_type, sequence.schema_version) in expected:
        return
    raise MaterializationError(
        port_name,
        f"expected {_artifact_type_keys_label(expected)}, got "
        f"{sequence.artifact_type}@{sequence.schema_version}",
    )


def _port_transforms(
    name: str,
    edge_count: int,
    transforms: Mapping[str, Sequence[EdgeTransform]] | None,
) -> list[EdgeTransform | None]:
    if transforms is None:
        return [None] * edge_count
    raw = transforms.get(name)
    if raw is None:
        raise MaterializationError(name, "has no edge transform")
    if len(raw) != edge_count:
        raise MaterializationError(
            name,
            f"expected {edge_count} edge transforms, got {len(raw)}",
        )
    return list(raw)


def _check_edge_type(
    name: str,
    edge: Sequence[ArtifactRef],
    carrier: ArtifactRefSequence | None,
    transform: EdgeTransform | None,
    accepted_types: Sequence[ArtifactTypeKey],
) -> None:
    if transform is not None:
        if transform.delivered not in accepted_types:
            delivered = transform.delivered
            raise MaterializationError(
                name,
                f"expected {_artifact_type_keys_label(accepted_types)}, got "
                f"{delivered.id}@{delivered.schema_version}",
            )
        return
    if carrier is not None:
        _validate_sequence_key(name, carrier, accepted_types)
        return
    for ref in edge:
        if ref.key() not in accepted_types:
            raise MaterializationError(
                name,
                f"expected {_artifact_type_keys_label(accepted_types)}, got "
                f"{ref.artifact_type}@{ref.schema_version}",
            )


def _derivations(
    edges: Sequence[Sequence[ArtifactRef]],
    transforms: Sequence[EdgeTransform | None],
) -> list[InputDerivation]:
    derivations: list[InputDerivation] = []
    for edge, transform in zip(edges, transforms, strict=True):
        derivations.extend([_derivation(transform)] * len(edge))
    return derivations


def _derivation(transform: EdgeTransform | None) -> InputDerivation:
    if transform is None or not transform.rewrites:
        return InputDerivation()
    return InputDerivation(
        projection_path=transform.projection_path,
        conversion_keys=tuple(
            ArtifactConversionKey(id=conversion.id, version=conversion.version)
            for conversion in transform.conversions
        ),
    )


def _item_index(*, sequenced: bool, position: int, outer: int | None) -> int | None:
    if sequenced:
        return position
    return outer


async def write_transformed_output(
    values: "ArtifactValues",
    output: ArtifactRef | ArtifactRefSequence,
    transform: EdgeTransform,
    context: NodeExecutionContext,
    *,
    port_name: str,
) -> ArtifactRef | ArtifactRefSequence:
    """Write a ref port or a graph-boundary edge that still needs a stored artifact."""

    if isinstance(output, ArtifactRefSequence):
        written = [
            await _write_transformed_ref(
                values,
                ref,
                transform,
                context,
                port_name=port_name,
                item_index=index,
            )
            for index, ref in enumerate(output.item_refs)
        ]
        return ArtifactRefSequence(
            artifact_type=transform.delivered.id,
            schema_version=transform.delivered.schema_version,
            item_refs=written,
            ordered=output.ordered,
            index_key=output.index_key,
        )
    return await _write_transformed_ref(
        values,
        output,
        transform,
        context,
        port_name=port_name,
        item_index=context.invocation_index,
    )


async def _stored_edge(
    values: "ArtifactValues",
    original: object,
    edge: Sequence[ArtifactRef],
    carrier: ArtifactRefSequence | None,
    transform: EdgeTransform | None,
    context: NodeExecutionContext,
    *,
    port_name: str,
    item_index: int | None,
) -> object:
    if transform is None or not transform.rewrites:
        return original
    if carrier is not None:
        written = [
            await _write_transformed_ref(
                values,
                ref,
                transform,
                context,
                port_name=port_name,
                item_index=index,
            )
            for index, ref in enumerate(edge)
        ]
        return ArtifactRefSequence(
            artifact_type=transform.delivered.id,
            schema_version=transform.delivered.schema_version,
            item_refs=written,
            ordered=carrier.ordered,
            index_key=carrier.index_key,
        )
    return await _write_transformed_ref(
        values,
        edge[0],
        transform,
        context,
        port_name=port_name,
        item_index=item_index,
    )


async def _write_transformed_ref(
    values: "ArtifactValues",
    ref: ArtifactRef,
    transform: EdgeTransform,
    context: NodeExecutionContext,
    *,
    port_name: str,
    item_index: int | None,
) -> ArtifactRef:
    from grafy_core.runtime.persistence import ArtifactWriteContext

    produced = await apply_edge_transform(
        values,
        ref,
        transform,
        context.workspace_id,
        item_index=item_index,
    )
    derivation = _derivation(transform)
    derivations: dict[str, tuple[InputDerivation, ...]] = {}
    if derivation.projection_path is not None or derivation.conversion_keys:
        derivations[port_name] = (derivation,)
    write_context = ArtifactWriteContext(
        node_context=context,
        provenance=MaterializationProvenance(
            refs_by_input={port_name: (ref,)},
            derivations_by_input=derivations,
        ),
        item_index=item_index,
    )
    if not transform.conversions:
        return await values.write(transform.delivered, produced, write_context)
    target = transform.delivered
    item_context = "" if item_index is None else f" at sequence item {item_index}"
    try:
        written = await values.write(target, produced, write_context)
    except EdgeTransformError:
        raise
    except Exception as exc:
        raise EdgeTransformError(
            "Failed to materialize final target "
            f"{target.id}@{target.schema_version} for the conversion path "
            f"from artifact {ref.artifact_id}{item_context} on {transform.label}"
        ) from exc
    if written.key() != target:
        raise EdgeTransformError(
            f"Final conversion writer returned {written.artifact_type}@"
            f"{written.schema_version}, expected "
            f"{target.id}@{target.schema_version} for artifact "
            f"{ref.artifact_id}{item_context} on {transform.label}"
        )
    return written
