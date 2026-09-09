from typing import Protocol, cast, final, override
from uuid import UUID

from pydantic import BaseModel

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.domain.errors import NotFoundError


class ResolutionError(RuntimeError):
    pass


class UnknownResolverError(ResolutionError):
    pass


class ArtifactContractError(ResolutionError):
    pass


class Resolver[T](Protocol):
    source: ArtifactTypeKey
    target: type[object]

    async def resolve(
        self,
        ref: ArtifactRef,
        workspace_id: UUID,
    ) -> T: ...


class ResolverRegistry:
    def __init__(self, resolvers: list[Resolver[object]] | None = None) -> None:
        self._resolvers: dict[tuple[ArtifactTypeKey, type[object]], Resolver[object]]
        self._resolvers = {}
        for resolver in resolvers or []:
            self.register(resolver)

    def register(self, resolver: Resolver[object]) -> None:
        key = (resolver.source, resolver.target)
        if key in self._resolvers:
            raise ValueError(
                f"Resolver already registered for {resolver.source.id}@"
                f"{resolver.source.schema_version} as {resolver.target}"
            )
        self._resolvers[key] = resolver

    async def resolve[T](
        self,
        ref: ArtifactRef,
        target: type[T],
        workspace_id: UUID,
    ) -> T:
        resolver = self._resolvers.get((ref.key(), target))
        if resolver is None:
            message = (
                f"No resolver registered for {ref.artifact_type}@"
                f"{ref.schema_version} as {target}"
            )
            raise UnknownResolverError(message)
        return cast(T, await resolver.resolve(ref, workspace_id))


@final
class InlineModelResolver[T: BaseModel](Resolver[T]):
    """Materializes an inline JSON artifact as its declared Pydantic model."""

    def __init__(
        self,
        *,
        source: ArtifactTypeKey,
        target: type[T],
        uow: UnitOfWorkPort,
    ) -> None:
        self.source = source
        self.target = cast(type[object], target)
        self._model = target
        self._uow = uow

    @override
    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> T:
        if ref.key() != self.source:
            message = (
                f"Inline model resolver expected {self.source.id}@"
                f"{self.source.schema_version}, got {ref.artifact_type}@"
                f"{ref.schema_version} for {ref.artifact_id}"
            )
            raise ArtifactContractError(message)

        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact", str(ref.artifact_id))
        if artifact.ref() != ref:
            message = f"Artifact repository returned a different artifact ref for {ref.artifact_id}"
            raise ArtifactContractError(message)
        if artifact.inline_payload is None:
            message = f"Artifact {ref.artifact_id} does not have an inline JSON payload"
            raise ArtifactContractError(message)

        try:
            return self._model.model_validate(artifact.inline_payload)
        except Exception as exc:
            message = (
                f"Failed to resolve artifact {ref.artifact_id} as "
                f"{self._model.__module__}.{self._model.__qualname__}"
            )
            raise ResolutionError(message) from exc
