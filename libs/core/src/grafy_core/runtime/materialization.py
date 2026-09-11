from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.nodes import InputContract, PortShape
from grafy_core.runtime.resolvers import ResolverRegistry


class MaterializationError(RuntimeError):
    def __init__(self, port_name: str, message: str) -> None:
        super().__init__(f"Input {port_name!r} {message}")
        self.port_name = port_name


@dataclass(frozen=True, slots=True)
class MaterializationProvenance:
    refs_by_input: dict[str, tuple[ArtifactRef, ...]]

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
    def __init__(self, resolver_registry: ResolverRegistry) -> None:
        self._resolver_registry = resolver_registry

    async def materialize[T: BaseModel](
        self,
        contract: InputContract[T],
        inputs: Mapping[str, object],
        workspace_id: UUID,
    ) -> tuple[T, MaterializationProvenance]:
        values: dict[str, object] = {}
        refs_by_input: dict[str, tuple[ArtifactRef, ...]] = {}

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
            # refs per incoming edge. Everything below reads from `edges` and
            # never re-inspects the raw value.
            edges: list[list[ArtifactRef]]
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
                edges = []
                for item in cast(list[object], value):
                    if isinstance(item, ArtifactRef):
                        edges.append([item])
                        continue
                    if isinstance(item, ArtifactRefSequence) and (
                        spec.preserves_ref_container
                    ):
                        _validate_sequence_key(name, item, accepted_types)
                        edges.append(list(item.item_refs))
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
                    case False, PortShape.MANY, ArtifactRefSequence() as sequence:
                        _validate_sequence_key(name, sequence, accepted_types)
                        edges = [list(sequence.item_refs)]
                    case True, PortShape.ONE, list() | tuple():
                        edges = []
                        for item in cast(Sequence[object], value):
                            if not isinstance(item, ArtifactRef):
                                raise MaterializationError(
                                    name,
                                    f"expected one ArtifactRef per incoming edge, "
                                    f"got {type(item).__name__}",
                                )
                            edges.append([item])
                    case True, PortShape.MANY, list() | tuple():
                        edges = []
                        for item in cast(Sequence[object], value):
                            if not isinstance(item, ArtifactRefSequence):
                                raise MaterializationError(
                                    name,
                                    f"expected one ArtifactRefSequence per incoming "
                                    f"edge, got {type(item).__name__}",
                                )
                            _validate_sequence_key(name, item, accepted_types)
                            edges.append(list(item.item_refs))
                    case _:
                        expected = _EXPECTED_PORT_VALUE[(spec.variadic, spec.shape)]
                        raise MaterializationError(
                            name,
                            f"expected {expected}, got {type(value).__name__}",
                        )

            if spec.variadic and len(edges) == 0 and spec.required:
                raise MaterializationError(name, "expected at least one incoming edge")

            refs = tuple(ref for edge in edges for ref in edge)
            for ref in refs:
                if ref.key() not in accepted_types:
                    raise MaterializationError(
                        name,
                        f"expected {_artifact_type_keys_label(accepted_types)}, got "
                        f"{ref.artifact_type}@{ref.schema_version}",
                    )
            if len(refs) > 0:
                refs_by_input[name] = refs

            if spec.preserves_ref_container:
                values[name] = value
                continue

            target = spec.target_type
            if target is None:
                raise MaterializationError(
                    name, "does not declare a resolvable Python value type"
                )
            resolved = [
                [
                    await self._resolver_registry.resolve(
                        ref=ref,
                        target=target,
                        workspace_id=workspace_id,
                    )
                    for ref in edge
                ]
                for edge in edges
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
