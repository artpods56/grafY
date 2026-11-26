"""One declaration per stored artifact type.

A declaration names the stored type, the Python class, and how that class is
loaded and stored. ``ArtifactValues`` is the only object that opens a row,
checks its ref, and inserts the stored object.
"""

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort, SaveFileCommand, StoredFile
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.runtime.resolvers import ArtifactContractError, ResolutionError


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    row: ArtifactObject
    storage: FileStoragePort


@dataclass(frozen=True, slots=True)
class ArtifactFiles:
    storage: FileStoragePort
    bucket: str
    workspace_id: UUID
    node_id: str | None = None

    async def save(
        self,
        spec: ArtifactTypeSpec,
        content: bytes,
        *,
        content_type: str,
        suffix: str,
    ) -> StoredFile:
        digest = sha256(content).hexdigest()
        return await self.storage.save(
            SaveFileCommand(
                bucket=self.bucket,
                path=(
                    f"workspaces/{self.workspace_id}/{spec.key.id}/"
                    f"v{spec.key.schema_version}/{digest}{suffix}"
                ),
                stream=BytesIO(content),
                content_type=content_type,
                metadata={"artifact_kind": spec.key.id, "sha256": digest},
                allow_overwrite=True,
            )
        )


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class EncodedArtifact:
    content_type: str
    byte_size: int
    sha256: str
    inline_payload: JsonObject | None = None
    stored: StoredFile | None = None
    metadata: JsonObject = field(default_factory=_empty_json_object)


@dataclass(frozen=True, slots=True)
class Artifact[T]:
    spec: ArtifactTypeSpec
    value_type: type[T]
    resolve: Callable[[StoredArtifact], Awaitable[T]]
    write: Callable[[T, ArtifactFiles], Awaitable[EncodedArtifact]]


def encode_inline_model(payload: BaseModel) -> EncodedArtifact:
    """Hash the canonical JSON of one inline payload model."""

    return encode_inline_payload(
        cast(JsonObject, payload.model_dump(mode="json", by_alias=True))
    )


def encode_inline_payload(payload: JsonObject) -> EncodedArtifact:
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return EncodedArtifact(
        content_type="application/json",
        byte_size=len(payload_bytes),
        sha256=sha256(payload_bytes).hexdigest(),
        inline_payload=payload,
    )


def _require_inline_payload(stored: StoredArtifact) -> JsonObject:
    payload = stored.row.inline_payload
    if payload is None:
        raise ArtifactContractError(
            f"Artifact {stored.row.id} does not have an inline JSON payload"
        )
    return payload


def _resolution_error(stored: StoredArtifact, model: type[BaseModel]) -> str:
    return (
        f"Failed to resolve artifact {stored.row.id} as "
        f"{model.__module__}.{model.__qualname__}"
    )


def inline_model_artifact[T: BaseModel](
    spec: ArtifactTypeSpec,
    model: type[T],
) -> Artifact[T]:
    """A pydantic model stored as its own inline JSON object."""

    async def resolve(stored: StoredArtifact) -> T:
        payload = _require_inline_payload(stored)
        try:
            return model.model_validate(payload)
        except Exception as exc:
            raise ResolutionError(_resolution_error(stored, model)) from exc

    async def write(value: T, _files: ArtifactFiles) -> EncodedArtifact:
        return encode_inline_model(value)

    return Artifact(
        spec=spec,
        value_type=model,
        resolve=resolve,
        write=write,
    )


def scalar_artifact[T](
    spec: ArtifactTypeSpec,
    value_type: type[T],
    model: type[BaseModel],
) -> Artifact[T]:
    """An unwrapped scalar stored in the ``{"value": ...}`` envelope."""

    async def resolve(stored: StoredArtifact) -> T:
        payload = _require_inline_payload(stored)
        try:
            parsed = model.model_validate(payload)
        except Exception as exc:
            raise ResolutionError(_resolution_error(stored, model)) from exc
        value = cast(T, getattr(parsed, "value"))
        if type(value) is not value_type:
            raise ArtifactContractError(
                f"Artifact {stored.row.id} {spec.key.id}@"
                f"{spec.key.schema_version} value is "
                f"{_class_name(type(value))}, expected {_class_name(value_type)}"
            )
        return value

    async def write(value: T, _files: ArtifactFiles) -> EncodedArtifact:
        return encode_inline_model(model.model_validate({"value": value}))

    return Artifact(
        spec=spec,
        value_type=value_type,
        resolve=resolve,
        write=write,
    )


def _class_name(value_type: type[object]) -> str:
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _provenance(context: ArtifactWriteContext) -> JsonObject:
    derivations_by_input = context.provenance.derivations_by_input
    recorded: JsonObject = {}
    for input_name, refs in context.provenance.refs_by_input.items():
        derivations = derivations_by_input.get(input_name, ())
        entries: list[object] = []
        for index, ref in enumerate(refs):
            entry: dict[str, object] = {
                "artifact_id": str(ref.artifact_id),
                "artifact_type": ref.artifact_type,
                "schema_version": ref.schema_version,
            }
            if index < len(derivations):
                derivation = derivations[index]
                if derivation.projection_path is not None:
                    entry["projection_path"] = list(derivation.projection_path)
                if derivation.conversion_keys:
                    entry["conversion_keys"] = [
                        {"id": key.id, "version": key.version}
                        for key in derivation.conversion_keys
                    ]
            entries.append(entry)
        recorded[input_name] = entries
    return recorded


class ArtifactValues:
    """Declarations plus the one unit of work that loads and stores them."""

    def __init__(
        self,
        declarations: Sequence[Artifact[Any]],
        *,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        bucket: str,
        storage_backend: str,
    ) -> None:
        by_key: dict[ArtifactTypeKey, Artifact[Any]] = {}
        by_type: dict[type[object], Artifact[Any]] = {}
        for declaration in declarations:
            key = declaration.spec.key
            existing = by_key.get(key)
            if existing is not None:
                raise ValueError(
                    f"Duplicate artifact declaration for {key.id}@{key.schema_version}"
                )
            typed = by_type.get(declaration.value_type)
            if typed is not None:
                raise ValueError(
                    f"Artifact value class {_class_name(declaration.value_type)} "
                    "is declared for both "
                    f"{typed.spec.key.id}@{typed.spec.key.schema_version} and "
                    f"{key.id}@{key.schema_version}"
                )
            by_key[key] = declaration
            by_type[declaration.value_type] = declaration
        self._by_key = by_key
        self._uow = uow
        self._storage = storage
        self._bucket = bucket
        self._storage_backend = storage_backend

    def declaration_for(self, key: ArtifactTypeKey) -> Artifact[Any] | None:
        return self._by_key.get(key)

    async def open(self, ref: ArtifactRef, workspace_id: UUID) -> StoredArtifact:
        async with self._uow as uow:
            row = await uow.artifacts.get(workspace_id, ref.artifact_id)
        if row is None:
            raise NotFoundError("Artifact", str(ref.artifact_id))
        if row.ref() != ref:
            raise ArtifactContractError(
                "Artifact repository returned a different artifact ref for "
                f"{ref.artifact_id}"
            )
        return StoredArtifact(row=row, storage=self._storage)

    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> object:
        declaration = self._by_key.get(ref.key())
        if declaration is None:
            raise KeyError(
                f"No artifact declaration for {ref.artifact_type}@{ref.schema_version}"
            )
        stored = await self.open(ref, workspace_id)
        return await declaration.resolve(stored)

    async def write(
        self,
        key: ArtifactTypeKey,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        declaration = self._by_key.get(key)
        if declaration is None:
            raise KeyError(f"No artifact declaration for {key.id}@{key.schema_version}")
        if type(value) is not declaration.value_type:
            raise TypeError(
                f"Cannot write {_class_name(type(value))} as "
                f"{key.id}@{key.schema_version}, expected "
                f"{_class_name(declaration.value_type)}"
            )
        files = ArtifactFiles(
            storage=self._storage,
            bucket=self._bucket,
            workspace_id=context.node_context.workspace_id,
            node_id=context.node_context.node_id,
        )
        encoded = await declaration.write(cast(Any, value), files)
        metadata: JsonObject = dict(context.metadata)
        metadata["producer_node_id"] = context.node_context.node_id
        provenance = _provenance(context)
        if provenance:
            metadata["provenance"] = provenance
        metadata.update(encoded.metadata)
        stored = encoded.stored
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=key.id,
            schema_version=key.schema_version,
            content_type=encoded.content_type,
            storage_backend=("inline" if stored is None else self._storage_backend),
            bucket=None if stored is None else stored.bucket,
            object_key=None if stored is None else stored.path,
            inline_payload=encoded.inline_payload,
            byte_size=encoded.byte_size,
            sha256=encoded.sha256,
            metadata=metadata,
        )
        async with self._uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact.ref()
