import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol, cast, final, override

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.nodes import (
    NodeExecutionContext,
    OutputContract,
    OutputPortSpec,
    PortShape,
)
from grafy_core.runtime.materialization import MaterializationProvenance


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


class ArtifactOutputWriter(Protocol):
    artifact_type: ArtifactTypeKey

    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef: ...


class ArtifactWriterRegistry:
    def __init__(self, writers: list[ArtifactOutputWriter] | None = None) -> None:
        self._writers: dict[ArtifactTypeKey, ArtifactOutputWriter] = {}
        for writer in writers or []:
            self.register(writer)

    def register(self, writer: ArtifactOutputWriter) -> None:
        if writer.artifact_type in self._writers:
            artifact_type = writer.artifact_type
            raise ValueError(
                f"Output writer already registered for {artifact_type.id}@"
                f"{artifact_type.schema_version}"
            )
        self._writers[writer.artifact_type] = writer

    def writer_for(self, artifact_type: ArtifactTypeKey) -> ArtifactOutputWriter:
        writer = self._writers.get(artifact_type)
        if writer is None:
            message = (
                f"No output writer registered for {artifact_type.id}@"
                f"{artifact_type.schema_version}"
            )
            raise RuntimeError(message)
        return writer


@final
class InlineModelOutputWriter[T: BaseModel](ArtifactOutputWriter):
    """Persists a typed Pydantic payload as an inline JSON artifact."""

    def __init__(
        self,
        *,
        artifact_type: ArtifactTypeKey,
        model: type[T],
        uow: UnitOfWorkPort,
    ) -> None:
        self.artifact_type = artifact_type
        self._model = model
        self._uow = uow

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        payload = self._model.model_validate(value)
        payload_json = cast(JsonObject, payload.model_dump(mode="json", by_alias=True))
        payload_bytes = json.dumps(
            payload_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        provenance: dict[str, object] = {
            input_name: [
                {
                    "artifact_id": str(ref.artifact_id),
                    "artifact_type": ref.artifact_type,
                    "schema_version": ref.schema_version,
                }
                for ref in refs
            ]
            for input_name, refs in context.provenance.refs_by_input.items()
        }
        metadata: JsonObject = {
            "producer_node_id": context.node_context.node_id,
        }
        if provenance:
            metadata["provenance"] = provenance
        metadata.update(context.metadata)
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type="application/json",
            storage_backend="inline",
            inline_payload=payload_json,
            byte_size=len(payload_bytes),
            sha256=sha256(payload_bytes).hexdigest(),
            metadata=metadata,
        )
        async with self._uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact.ref()


class OutputPersister:
    def __init__(self, writer_registry: ArtifactWriterRegistry) -> None:
        self._writer_registry = writer_registry

    async def persist(
        self,
        contract: OutputContract[Any],
        context: NodeExecutionContext,
        output: object,
        provenance: MaterializationProvenance,
        metadata: JsonObject | None = None,
    ) -> PersistedNodeOutput | BaseModel:
        validated_output = contract.model.model_validate(output)
        values = _model_values(validated_output)

        for name, spec in contract.ports.items():
            if name not in values:
                if spec.required:
                    raise RuntimeError(f"Missing required output {name!r}")
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

        writer = self._writer_registry.writer_for(spec.produces)
        if spec.shape == PortShape.MANY:
            if items is None:
                raise RuntimeError(f"Output {spec.name!r} expected a sequence")
            item_refs = [
                await writer.write(
                    item,
                    ArtifactWriteContext(
                        node_context=context.node_context,
                        provenance=context.provenance,
                        item_index=index,
                    ),
                )
                for index, item in enumerate(items)
            ]
            return ArtifactRefSequence.from_key(
                key=spec.produces,
                item_refs=item_refs,
            )

        return await writer.write(cast(object, value), context)


def _model_values(value: BaseModel) -> dict[str, object]:
    return {name: getattr(value, name) for name in value.__class__.model_fields}
