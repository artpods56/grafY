from hashlib import sha256
from io import BytesIO

from grafy_core.artifacts import JsonObject
from grafy_core.ports.storage import FileMetadata, SaveFileCommand
from grafy_core.runtime.artifact_values import (
    Artifact,
    ArtifactFiles,
    EncodedArtifact,
    StoredArtifact,
)
from grafy_core.runtime.resolvers import ArtifactContractError, ResolutionError
from grafy_core.runtime.table_storage import iter_table_chunks, load_table_artifact
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableChunkDescriptor,
    TableManifest,
)


def table_artifact() -> Artifact[Table]:
    async def resolve(stored: StoredArtifact) -> Table:
        try:
            return await load_table_artifact(stored.row, stored.storage)
        except (ArtifactContractError, ResolutionError):
            raise
        except Exception as exc:
            raise ResolutionError(
                f"Failed to resolve table artifact {stored.row.id}"
            ) from exc

    async def write(value: Table, files: ArtifactFiles) -> EncodedArtifact:
        logical_content = value.model_dump_json().encode("utf-8")
        logical_hash = sha256(logical_content).hexdigest()
        chunks: list[TableChunkDescriptor] = []
        stored_byte_size = 0
        for chunk in iter_table_chunks(value):
            offset = chunk.offset
            content = chunk.model_dump_json().encode("utf-8")
            content_hash = sha256(content).hexdigest()
            storage_path = (
                f"workspaces/{files.workspace_id}/"
                f"{TABLE_DATA.key.id}/v{TABLE_DATA.key.schema_version}/chunks/"
                f"{content_hash}.json"
            )
            metadata: FileMetadata = {
                "artifact_kind": TABLE_DATA.key.id,
                "sha256": content_hash,
            }
            if files.node_id is not None:
                metadata["job_id"] = files.node_id
            try:
                stored = await files.storage.save(
                    SaveFileCommand(
                        bucket=files.bucket,
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
                    f"{files.node_id!r} at {files.bucket}/{storage_path}"
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
            columns=value.columns,
            row_count=len(value.rows),
            chunks=chunks,
        )
        manifest_content = manifest.model_dump_json().encode("utf-8")
        manifest_hash = sha256(manifest_content).hexdigest()
        manifest_path = (
            f"workspaces/{files.workspace_id}/"
            f"{TABLE_DATA.key.id}/v{TABLE_DATA.key.schema_version}/manifests/"
            f"{manifest_hash}.json"
        )
        try:
            stored_manifest = await files.storage.save(
                SaveFileCommand(
                    bucket=files.bucket,
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
                f"Failed to persist table manifest for node {files.node_id!r} at "
                f"{files.bucket}/{manifest_path}"
            ) from exc
        encoded_metadata: JsonObject = {
            "storage_format": manifest.format,
            "row_count": manifest.row_count,
            "column_count": len(manifest.columns),
            "chunk_count": len(manifest.chunks),
            "logical_byte_size": len(logical_content),
            "storage_byte_size": stored_byte_size + stored_manifest.byte_size,
            "manifest_byte_size": stored_manifest.byte_size,
            "manifest_sha256": stored_manifest.sha256,
        }
        return EncodedArtifact(
            content_type="application/json",
            byte_size=len(logical_content),
            sha256=logical_hash,
            stored=stored_manifest,
            metadata=encoded_metadata,
        )

    return Artifact(
        spec=TABLE_DATA,
        value_type=Table,
        resolve=resolve,
        write=write,
    )


__all__ = ["table_artifact"]
