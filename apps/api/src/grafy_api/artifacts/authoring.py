import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, TypeAdapter, ValidationError

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeSpec,
    JsonObject,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.artifact_values import (
    ArtifactFiles,
    ArtifactValues,
    EncodedArtifact,
    StoredArtifact,
    encode_inline_payload,
)
from grafy_core.runtime.resolvers import ResolutionError

from grafy_api.catalog import artifact_payload_schema, is_artifact_authorable


class InvalidArtifactPayloadError(ValueError):
    """The requested artifact does not satisfy an authorable contract."""


_REFERENCE_LIST = TypeAdapter(list[ArtifactRef])


def _payload_references(
    spec: ArtifactTypeSpec, payload: JsonObject
) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for contract in spec.references:
        value: object = payload
        for segment in contract.path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = cast(Mapping[object, object], value).get(segment)
        if value is None:
            continue
        path = ".".join(contract.path)
        try:
            found = (
                [ArtifactRef.model_validate(value)]
                if contract.shape == "one"
                else _REFERENCE_LIST.validate_python(value)
            )
        except ValidationError as exc:
            raise InvalidArtifactPayloadError(
                f"Invalid artifact reference at {path}"
            ) from exc
        for ref in found:
            if ref.key() != contract.target:
                raise InvalidArtifactPayloadError(
                    f"Reference at {path} must be "
                    f"{contract.target.id}@{contract.target.schema_version}"
                )
        refs.extend(found)
    return refs


class ArtifactAuthoringService:
    """Validate a JSON document and append an artifact in its Workspace."""

    def __init__(
        self,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec],
        values: ArtifactValues,
        *,
        bucket: str,
        storage_backend: str,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._artifact_types = artifact_types
        self._values = values
        self._bucket = bucket
        self._storage_backend = storage_backend

    async def create(
        self,
        workspace_id: UUID,
        *,
        artifact_type: str,
        schema_version: int,
        payload: JsonObject,
        author_id: UUID,
        authored_by: Literal["user", "agent"],
        derived_from_artifact_id: UUID | None = None,
        title: str | None = None,
    ) -> tuple[ArtifactObject, datetime]:
        spec = self._artifact_types.get((artifact_type, schema_version))
        label = f"{artifact_type}@{schema_version}"
        if spec is None or not is_artifact_authorable(spec):
            raise InvalidArtifactPayloadError(f"{label} cannot be authored as JSON")

        try:
            # Reject non-finite numbers and invalid Unicode before writing to storage.
            _ = json.dumps(payload, allow_nan=False, ensure_ascii=False).encode("utf-8")
            validate = cast(
                Callable[[object], None],
                Draft202012Validator(
                    artifact_payload_schema(spec), format_checker=FormatChecker()
                ).validate,
            )
            validate(payload)
        except JsonSchemaValidationError as exc:
            raise InvalidArtifactPayloadError(
                f"Invalid {label} payload at {exc.json_path}: {exc.message}"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise InvalidArtifactPayloadError(
                f"Invalid JSON payload for {label}"
            ) from exc

        refs = _payload_references(spec, payload)
        required_ids = {ref.artifact_id for ref in refs}
        if derived_from_artifact_id is not None:
            required_ids.add(derived_from_artifact_id)

        created_at = datetime.now(UTC)
        metadata: JsonObject = {
            "authored_by": authored_by,
            "authored_by_user_id": str(author_id),
            "created_at": created_at.isoformat(),
        }
        if title is not None:
            metadata["title"] = title
        if derived_from_artifact_id is not None:
            metadata["derived_from_artifact_id"] = str(derived_from_artifact_id)

        artifact = ArtifactObject(
            workspace_id=workspace_id,
            artifact_type=artifact_type,
            schema_version=schema_version,
            storage_backend="inline",
            content_type="application/json",
            metadata=metadata,
        )
        async with self._uow as uow:
            if required_ids:
                targets = await uow.artifacts.get_many(workspace_id, required_ids)
                for artifact_id in required_ids - targets.keys():
                    raise NotFoundError("Artifact", str(artifact_id))
                for ref in refs:
                    target = targets[ref.artifact_id].ref()
                    if target.key() != ref.key() or (
                        ref.content_hash is not None
                        and target.content_hash != ref.content_hash
                    ):
                        raise InvalidArtifactPayloadError(
                            f"Reference to artifact {ref.artifact_id} does not "
                            "match its stored type or content hash"
                        )
            encoded = await self._encode(spec, artifact, payload)
            if encoded.stored is not None:
                artifact.storage_backend = self._storage_backend
                artifact.bucket = encoded.stored.bucket
                artifact.object_key = encoded.stored.path
            artifact.inline_payload = encoded.inline_payload
            artifact.content_type = encoded.content_type
            artifact.byte_size = encoded.byte_size
            artifact.sha256 = encoded.sha256
            artifact.metadata.update(encoded.metadata)
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact, created_at

    async def _encode(
        self, spec: ArtifactTypeSpec, artifact: ArtifactObject, payload: JsonObject
    ) -> EncodedArtifact:
        label = f"{spec.key.id}@{spec.key.schema_version}"
        declaration = self._values.declaration_for(spec.key)
        if spec.bundle.format == "inline-json":
            artifact.inline_payload = payload
            if declaration is not None:
                try:
                    _ = await declaration.resolve(
                        StoredArtifact(artifact, self._storage)
                    )
                except (ResolutionError, ValueError) as exc:
                    raise InvalidArtifactPayloadError(
                        f"Invalid {label} payload: {exc}"
                    ) from exc
            return encode_inline_payload(payload)

        if declaration is None or not issubclass(declaration.value_type, BaseModel):
            raise InvalidArtifactPayloadError(f"{label} has no JSON writer")
        try:
            value = declaration.value_type.model_validate(payload)
        except ValidationError as exc:
            raise InvalidArtifactPayloadError(
                f"Invalid {label} payload: {exc}"
            ) from exc
        return await declaration.write(
            value, ArtifactFiles(self._storage, self._bucket, artifact.workspace_id)
        )
