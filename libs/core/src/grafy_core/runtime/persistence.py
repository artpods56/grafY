from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
)
from grafy_core.nodes import (
    NodeExecutionContext,
    OutputContract,
    OutputPortSpec,
    PortShape,
)
from grafy_core.runtime.materialization import MaterializationProvenance

if TYPE_CHECKING:
    from grafy_core.runtime.artifact_values import ArtifactValues


@dataclass(frozen=True, slots=True)
class ArtifactWriteContext:
    node_context: NodeExecutionContext
    provenance: MaterializationProvenance
    item_index: int | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PersistedNodeOutput:
    values: dict[str, object]
    cache_hits: int = 0
    cache_misses: int = 0

    def __post_init__(self) -> None:
        if self.cache_hits < 0 or self.cache_misses < 0:
            raise ValueError("Node output cache counters must not be negative")

    def __getitem__(self, name: str) -> object:
        return self.values[name]

    def __getattr__(self, name: str) -> object:
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class OutputPersister:
    def __init__(self, values: "ArtifactValues | None" = None) -> None:
        self._values = values

    async def _write(
        self,
        key: ArtifactTypeKey,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        values = self._values
        if values is None or values.declaration_for(key) is None:
            raise RuntimeError(
                f"No artifact declaration for {key.id}@{key.schema_version}"
            )
        return await values.write(key, value, context)

    async def persist(
        self,
        contract: OutputContract[Any],
        context: NodeExecutionContext,
        output: object,
        provenance: MaterializationProvenance,
        metadata: JsonObject | None = None,
    ) -> PersistedNodeOutput | BaseModel:
        return await self.persist_validated(
            contract, context, contract.model.model_validate(output), provenance, metadata
        )

    async def persist_validated(
        self,
        contract: OutputContract[Any],
        context: NodeExecutionContext,
        validated_output: BaseModel,
        provenance: MaterializationProvenance,
        metadata: JsonObject | None = None,
    ) -> PersistedNodeOutput | BaseModel:
        values = _model_values(validated_output)

        for name, spec in contract.ports.items():
            if spec.kind == "service":
                # A service output is the live object the node returned. It is
                # never written, and it does not become part of the stored result.
                values.pop(name, None)
                continue
            if name not in values:
                if spec.required:
                    raise RuntimeError(f"Missing required output {name!r}")
                continue
            if values[name] is None:
                # An optional None is omitted, not stored as a null artifact. The
                # computation may still record why in unsupported_outputs metadata.
                if spec.required:
                    raise RuntimeError(f"Missing required output {name!r}")
                values.pop(name, None)
                continue

            values[name] = await self._persist_value(
                spec,
                values[name],
                ArtifactWriteContext(
                    node_context=context,
                    provenance=provenance,
                    item_index=context.invocation_index,
                    metadata={} if metadata is None else metadata,
                ),
            )

        if len(contract.ports) == 0:
            return validated_output
        return PersistedNodeOutput(values=values)

    async def _persist_value(
        self,
        spec: OutputPortSpec,
        value: object,
        context: ArtifactWriteContext,
    ) -> object:
        if not isinstance(spec.produces, ArtifactTypeKey):
            raise RuntimeError(
                f"Output {spec.name!r} has an unresolved artifact type contract"
            )
        if isinstance(value, ArtifactRef):
            if value.key() != spec.produces:
                raise RuntimeError(
                    f"Output {spec.name!r} expected {spec.produces.id}@"
                    f"{spec.produces.schema_version}, got {value.artifact_type}@"
                    f"{value.schema_version}"
                )
            if spec.shape is not PortShape.ONE:
                raise RuntimeError(
                    f"Output {spec.name!r} expected an ArtifactRefSequence, "
                    "got ArtifactRef"
                )
            return value
        if isinstance(value, ArtifactRefSequence):
            if (
                value.artifact_type != spec.produces.id
                or value.schema_version != spec.produces.schema_version
            ):
                raise RuntimeError(
                    f"Output {spec.name!r} expected {spec.produces.id}@"
                    f"{spec.produces.schema_version}, got {value.artifact_type}@"
                    f"{value.schema_version}"
                )
            if spec.shape is not PortShape.MANY:
                raise RuntimeError(
                    f"Output {spec.name!r} expected an ArtifactRef, got "
                    "ArtifactRefSequence"
                )
            return value

        items: list[object] | None = None
        if isinstance(value, Sequence) and not isinstance(
            value, str | bytes | bytearray
        ):
            items = list(cast(Sequence[object], value))

        if items is not None and all(isinstance(item, ArtifactRef) for item in items):
            refs = cast(list[ArtifactRef], items)
            for ref in refs:
                if ref.key() != spec.produces:
                    raise RuntimeError(
                        f"Output {spec.name!r} expected {spec.produces.id}@"
                        f"{spec.produces.schema_version}, got {ref.artifact_type}@"
                        f"{ref.schema_version}"
                    )
            if spec.shape == PortShape.MANY:
                return ArtifactRefSequence.from_key(
                    key=spec.produces,
                    item_refs=refs,
                )
            if len(refs) == 1:
                return refs[0]
            raise RuntimeError(
                f"Output {spec.name!r} expected one ArtifactRef, got {len(refs)}"
            )

        if spec.shape == PortShape.MANY:
            if items is None:
                raise RuntimeError(f"Output {spec.name!r} expected a sequence")
            item_refs = [
                await self._write(
                    spec.produces,
                    item,
                    ArtifactWriteContext(
                        node_context=context.node_context,
                        provenance=context.provenance,
                        item_index=index,
                        # The node's own metadata describes who produced this port's
                        # output, and it describes each item equally. Dropping it here
                        # left sequence items without an implementation identity, so
                        # every read that asks "was this written by the current build?"
                        # answered no.
                        metadata=context.metadata,
                    ),
                )
                for index, item in enumerate(items)
            ]
            return ArtifactRefSequence.from_key(
                key=spec.produces,
                item_refs=item_refs,
            )

        return await self._write(spec.produces, cast(object, value), context)


def _model_values(value: BaseModel) -> dict[str, object]:
    return {name: getattr(value, name) for name in value.__class__.model_fields}
