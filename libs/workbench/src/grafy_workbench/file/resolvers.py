"""Read a stored ``file.*`` artifact as its encoded bytes.

A canonical conversion may start at a file format, so the edge needs a runtime
value for it. The bytes are the whole contract: nothing here interprets them.
"""

from typing import final, override
from uuid import UUID

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.file_artifacts import load_file_artifact
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.resolvers import Resolver


@final
class FileBytesResolver(Resolver[bytes]):
    def __init__(
        self,
        *,
        source: ArtifactTypeKey,
        storage: FileStoragePort,
        uow: UnitOfWorkPort,
    ) -> None:
        self.source = source
        self.target: type[object] = bytes
        self._storage = storage
        self._uow = uow

    @override
    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> bytes:
        file = await load_file_artifact(
            storage=self._storage,
            uow=self._uow,
            workspace_id=workspace_id,
            ref=ref,
        )
        return file.content


__all__ = ["FileBytesResolver"]
