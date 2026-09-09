from hashlib import sha256
from io import BytesIO
from typing import cast, final, override
from uuid import UUID

from grafy_core.artifacts import ArtifactObject, ArtifactRef, JsonObject
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.domain.errors import NotFoundError
from grafy_core.ports.storage import FileMetadata, FileStoragePort, SaveFileCommand
from grafy_core.runtime.persistence import ArtifactOutputWriter, ArtifactWriteContext
from grafy_core.runtime.resolvers import (
    ArtifactContractError,
    ResolutionError,
    Resolver,
)
from grafy_core.runtime.table_storage import iter_table_chunks, load_table_artifact
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableChunkDescriptor,
    TableManifest,
)


@final
class TableArtifactWriter(ArtifactOutputWriter):
    def __init__(
        self,
        *,
        storage: FileStoragePort,
        uow: UnitOfWorkPort,
        bucket: str,
        storage_backend: str,
    ) -> None:
        self.artifact_type = TABLE_DATA.key
        self._storage = storage
        self._uow = uow
        self._bucket = bucket
        self._storage_backend = storage_backend

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        table = Table.model_validate(value)
        logical_content = table.model_dump_json().encode("utf-8")
        logical_hash = sha256(logical_content).hexdigest()
        chunks: list[TableChunkDescriptor] = []
        stored_byte_size = 0
        for chunk in iter_table_chunks(table):
            offset = chunk.offset
            content = chunk.model_dump_json().encode("utf-8")
            content_hash = sha256(content).hexdigest()
            storage_path = (
                f"workspaces/{context.node_context.workspace_id}/"
                f"{TABLE_DATA.key.id}/v{TABLE_DATA.key.schema_version}/chunks/"
                f"{content_hash}.json"
            )
            metadata: FileMetadata = {
                "artifact_kind": TABLE_DATA.key.id,
                "sha256": content_hash,
            }
            if context.node_context.node_id is not None:
                metadata["job_id"] = context.node_context.node_id
            try:
                stored = await self._storage.save(
                    SaveFileCommand(
                        bucket=self._bucket,
                        path=storage_path,
                        stream=BytesIO(content),
                        content_type="application/json",
                        metadata=metadata,
                        allow_overwrite=True,
                    )
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to persist table rows {offset} through "
                    f"{offset + len(chunk.rows) - 1} for node "
                    f"{context.node_context.node_id!r} at "
                    f"{self._bucket}/{storage_path}"
                ) from exc
            stored_byte_size += stored.byte_size
            chunks.append(
                TableChunkDescriptor(
                    offset=offset,
                    row_count=len(chunk.rows),
                    object_key=stored.path,
                    byte_size=stored.byte_size,
                    sha256=stored.sha256,
                )
            )

        manifest = TableManifest(
            columns=table.columns,
            row_count=len(table.rows),
            chunks=chunks,
        )
        manifest_content = manifest.model_dump_json().encode("utf-8")
        manifest_hash = sha256(manifest_content).hexdigest()
        manifest_path = (
            f"workspaces/{context.node_context.workspace_id}/"
            f"{TABLE_DATA.key.id}/v{TABLE_DATA.key.schema_version}/manifests/"
            f"{manifest_hash}.json"
        )
        try:
            stored_manifest = await self._storage.save(
                SaveFileCommand(
                    bucket=self._bucket,
                    path=manifest_path,
                    stream=BytesIO(manifest_content),
                    content_type="application/json",
                    metadata={
                        "artifact_kind": TABLE_DATA.key.id,
                        "sha256": manifest_hash,
                    },
                    allow_overwrite=True,
                )
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to persist table manifest for node "
                f"{context.node_context.node_id!r} at "
                f"{self._bucket}/{manifest_path}"
            ) from exc

        provenance: JsonObject = {
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
        artifact_metadata: JsonObject = dict(context.metadata)
        artifact_metadata.update(
            {
                "producer_node_id": context.node_context.node_id,
                "storage_format": manifest.format,
                "row_count": manifest.row_count,
                "column_count": len(manifest.columns),
                "chunk_count": len(manifest.chunks),
                "logical_byte_size": len(logical_content),
                "storage_byte_size": stored_byte_size + stored_manifest.byte_size,
                "manifest_byte_size": stored_manifest.byte_size,
                "manifest_sha256": stored_manifest.sha256,
            }
        )
        if provenance:
            artifact_metadata["provenance"] = provenance
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=TABLE_DATA.key.id,
            schema_version=TABLE_DATA.key.schema_version,
            content_type="application/json",
            storage_backend=self._storage_backend,
            bucket=stored_manifest.bucket,
            object_key=stored_manifest.path,
            byte_size=len(logical_content),
            sha256=logical_hash,
            metadata=artifact_metadata,
        )
        async with self._uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact.ref()


@final
class TableArtifactResolver(Resolver[Table]):
    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
    ) -> None:
        self.source = TABLE_DATA.key
        self.target = cast(type[object], Table)
        self._uow = uow
        self._storage = storage

    @override
    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> Table:
        if ref.key() != self.source:
            raise ArtifactContractError(
                f"Table resolver expected {self.source.id}@"
                f"{self.source.schema_version}, got {ref.artifact_type}@"
                f"{ref.schema_version} for {ref.artifact_id}"
            )
        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact", str(ref.artifact_id))
        if artifact.ref() != ref:
            raise ArtifactContractError(
                f"Artifact repository returned a different artifact ref for "
                f"{ref.artifact_id}"
            )
        try:
            return await load_table_artifact(artifact, self._storage)
        except (ArtifactContractError, ResolutionError):
            raise
        except Exception as exc:
            raise ResolutionError(
                f"Failed to resolve table artifact {ref.artifact_id}"
            ) from exc


__all__ = ["TableArtifactResolver", "TableArtifactWriter"]
