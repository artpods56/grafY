"""Exact reference resolution for application workflows."""

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from grafy_core.artifacts import ArtifactObject, ArtifactRef, ArtifactRefSequence
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
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
    """Resolve exact references, without cache-integrity hashing."""

    def __init__(self, uow: UnitOfWorkPort) -> None:
        self._uow = uow

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
            async with self._uow as uow:
                artifacts = await uow.artifacts.get_many(workspace_id, artifact_ids)
        return ArtifactAvailabilityBatch(artifacts)


class ArtifactAvailabilityBatch:
    """Rows read for one application operation only."""

    def __init__(self, artifacts: Mapping[UUID, ArtifactObject]) -> None:
        self.artifacts = MappingProxyType(dict(artifacts))

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
