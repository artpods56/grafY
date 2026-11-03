from typing import Protocol, final
from uuid import UUID

from grafy_core.domain.invocation_cache import InvocationCacheEntry


class InvocationCachePort(Protocol):
    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> InvocationCacheEntry | None: ...

    async def put_if_absent(self, entry: InvocationCacheEntry) -> bool: ...

    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool: ...


@final
class DisabledInvocationCache(InvocationCachePort):
    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> InvocationCacheEntry | None:
        del workspace_id, key_sha256
        return None

    async def put_if_absent(self, entry: InvocationCacheEntry) -> bool:
        del entry
        return False

    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        del workspace_id, key_sha256, generation
        return False


__all__ = [
    "DisabledInvocationCache",
    "InvocationCachePort",
]
