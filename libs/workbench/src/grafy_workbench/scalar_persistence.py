"""Adapt runtime scalars to the stable inline ``{\"value\": ...}`` envelope."""

from collections.abc import Callable
from typing import Protocol, cast, override
from uuid import UUID

from pydantic import BaseModel

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriteContext,
    InlineModelOutputWriter,
)
from grafy_core.runtime.resolvers import InlineModelResolver, ResolutionError, Resolver


class _ScalarPayload[T](Protocol):
    @property
    def value(self) -> T: ...


class ScalarOutputWriter(ArtifactOutputWriter):
    """Wrap and optionally normalize a scalar before inline model persistence."""

    def __init__(
        self,
        *,
        artifact_type: ArtifactTypeKey,
        model: type[BaseModel],
        uow: UnitOfWorkPort,
        normalize: Callable[[object], object] | None = None,
    ) -> None:
        self.artifact_type = artifact_type
        self._normalize = normalize
        self._writer = InlineModelOutputWriter(
            artifact_type=artifact_type,
            model=model,
            uow=uow,
        )

    @override
    async def write(self, value: object, context: ArtifactWriteContext) -> ArtifactRef:
        if self._normalize is not None:
            value = self._normalize(value)
        return await self._writer.write({"value": value}, context)


class ScalarResolver[T](Resolver[T]):
    """Load an inline model, check its scalar value, and unwrap the envelope."""

    def __init__(
        self,
        *,
        source: ArtifactTypeKey,
        target: type[T],
        model: type[BaseModel],
        uow: UnitOfWorkPort,
        check: Callable[[T, ArtifactRef], object] | None = None,
    ) -> None:
        self.source = source
        self.target: type[object] = target
        self._check = check
        self._resolver = InlineModelResolver(source=source, target=model, uow=uow)

    @override
    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> T:
        payload = cast(
            _ScalarPayload[T], await self._resolver.resolve(ref, workspace_id)
        )
        value = payload.value
        if self._check is not None:
            try:
                _ = self._check(value, ref)
            except ValueError as exc:
                raise ResolutionError(
                    f"Failed to resolve artifact {ref.artifact_id} as "
                    f"{self.source.id}@{self.source.schema_version} scalar value"
                ) from exc
        return value
