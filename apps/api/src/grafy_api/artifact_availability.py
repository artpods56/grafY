"""Exact reference resolution and storage availability for application workflows."""

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    json_collections_artifact_is_accessible,
)
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    UnitOfWorkPort,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.table_storage import table_artifact_is_accessible
from grafy_core.table_contracts import TABLE_DATA
from grafy_api.services.errors import WorkbenchOperationError


class ArtifactReferenceError(WorkbenchOperationError):
    """An exact reference failed, with identity available to boundary renderers."""

    def __init__(
        self,
        ref: ArtifactRef,
        *,
        reason: Literal["missing", "mismatch"],
        context: str,
        sequence_index: int | None,
    ) -> None:
        self.reference = ref
        self.reason = reason
        self.sequence_index = sequence_index
        item_context = (
            "" if sequence_index is None else f" sequence item {sequence_index}"
        )
        if reason == "missing":
            message = (
                f"{context}{item_context} references missing artifact {ref.artifact_id}"
            )
        else:
            message = (
                f"{context}{item_context} does not match the repository ref "
                f"for artifact {ref.artifact_id}"
            )
        super().__init__(message)


class ArtifactAvailability:
    """Check reference identity and presence, without cache-integrity hashing."""

    def __init__(self, unit_of_work: UnitOfWorkPort, storage: FileStoragePort) -> None:
        self._unit_of_work = unit_of_work
        self._storage = storage

    async def load(
        self,
        workspace_id: UUID,
        values: Iterable[ArtifactOutputValue],
    ) -> "ArtifactAvailabilityBatch":
        artifact_ids: set[UUID] = set()
        for value in values:
            refs = (
                value.item_refs if isinstance(value, ArtifactRefSequence) else (value,)
            )
            artifact_ids.update(ref.artifact_id for ref in refs)
        artifacts: dict[UUID, ArtifactObject] = {}
        if artifact_ids:
            async with self._unit_of_work as unit_of_work:
                artifacts = await unit_of_work.artifacts.get_many(
                    workspace_id, artifact_ids
                )
        return ArtifactAvailabilityBatch(artifacts, self._storage)


class ArtifactAvailabilityBatch:
    """Rows and memoized presence checks for one application operation only."""

    def __init__(
        self, artifacts: Mapping[UUID, ArtifactObject], storage: FileStoragePort
    ) -> None:
        self.artifacts = MappingProxyType(dict(artifacts))
        self._storage = storage
        self._accessible: dict[UUID, bool] = {}

    def resolve_refs(
        self,
        value: ArtifactOutputValue | Sequence[ArtifactRef],
        *,
        context: str,
    ) -> tuple[ArtifactObject, ...]:
        if isinstance(value, ArtifactRefSequence):
            refs = value.item_refs
        elif isinstance(value, ArtifactRef):
            refs = (value,)
        else:
            refs = value
        resolved: list[ArtifactObject] = []
        for index, ref in enumerate(refs):
            artifact = self.artifacts.get(ref.artifact_id)
            if artifact is None or artifact.ref() != ref:
                raise ArtifactReferenceError(
                    ref,
                    reason="missing" if artifact is None else "mismatch",
                    context=context,
                    sequence_index=index
                    if isinstance(value, ArtifactRefSequence)
                    else None,
                )
            resolved.append(artifact)
        return tuple(resolved)

    async def is_accessible(self, value: ArtifactOutputValue) -> bool:
        refs = value.item_refs if isinstance(value, ArtifactRefSequence) else (value,)
        for ref in refs:
            artifact = self.artifacts.get(ref.artifact_id)
            if artifact is None or artifact.ref() != ref:
                return False
            if not await self.artifact_is_accessible(artifact):
                return False
        return True

    async def artifact_is_accessible(self, artifact: ArtifactObject) -> bool:
        cached = self._accessible.get(artifact.id)
        if cached is not None:
            return cached
        if (
            artifact.artifact_type == TABLE_DATA.key.id
            and artifact.schema_version == TABLE_DATA.key.schema_version
        ):
            accessible = await table_artifact_is_accessible(artifact, self._storage)
        elif artifact.metadata.get("storage_format") == JSON_COLLECTIONS_STORAGE_FORMAT:
            accessible = await json_collections_artifact_is_accessible(
                artifact, self._storage
            )
        elif artifact.inline_payload is not None:
            accessible = True
        elif artifact.bucket is None or artifact.object_key is None:
            accessible = False
        else:
            accessible = (
                await self._storage.stat(artifact.bucket, artifact.object_key)
                is not None
            )
        self._accessible[artifact.id] = accessible
        return accessible
