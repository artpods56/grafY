import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from grafy_core.artifact_collections import JSON_COLLECTIONS_STORAGE_FORMAT
from grafy_core.artifacts import ArtifactExportFormat, ArtifactObject, ArtifactTypeSpec
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort, FileStreamProtocol
from grafy_core.runtime.table_storage import iter_table_csv, load_table_artifact
from grafy_core.spatial_storage import load_feature_collection
from grafy_core.table_contracts import TABLE_DATA

from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)

from grafy_api.artifacts.errors import ArtifactResponseTooLargeError
from grafy_api.artifacts.geo import (
    GEO_FEATURE_COLLECTION_ARTIFACT_TYPE,
    feature_count,
)
from grafy_api.artifacts.models import (
    GeoFeatureCollectionPayload,
    GeoFeatureManifestMetadata,
)


ARTIFACT_RESPONSE_CHUNK_SIZE = 1 * 1_024 * 1_024
BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES = 64 * 1_024 * 1_024


@dataclass(frozen=True, slots=True)
class ArtifactContentRead:
    body: bytes | FileStreamProtocol | Callable[[], AsyncIterator[bytes]]
    content_length: int | None

    async def chunks(self) -> AsyncIterator[bytes]:
        body = self.body
        if isinstance(body, bytes):
            if body:
                yield body
            return
        if isinstance(body, Callable):
            async for chunk in body():
                if chunk:
                    yield chunk
            return
        try:
            while chunk := await asyncio.to_thread(
                body.read,
                ARTIFACT_RESPONSE_CHUNK_SIZE,
            ):
                yield chunk
        finally:
            await asyncio.to_thread(body.close)


class ArtifactContentService:
    """Loads persisted artifact bytes, streams, and download exports."""

    def __init__(
        self,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec] | None = None,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._artifact_types = artifact_types or {}

    def export_formats(self, artifact: ArtifactObject) -> list[ArtifactExportFormat]:
        """Formats this artifact can be downloaded as.

        `json` is available for any JSON-representable artifact (inline payload
        or `application/json` content); additional formats come from the type's
        `export_formats` declaration.
        """

        formats: list[ArtifactExportFormat] = []
        if (
            artifact.inline_payload is not None
            or artifact.content_type == "application/json"
        ):
            formats.append(
                ArtifactExportFormat(
                    format="json",
                    content_type="application/json",
                    filename="artifact.json",
                )
            )
        spec = self._artifact_types.get(
            (artifact.artifact_type, artifact.schema_version)
        )
        if spec is not None:
            formats.extend(spec.export_formats)
        return formats

    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        async with self._uow as uow:
            return await uow.artifacts.get(workspace_id, artifact_id)

    async def load_content(self, artifact: ArtifactObject) -> bytes:
        if (
            artifact.artifact_type == TABLE_DATA.key.id
            and artifact.schema_version == TABLE_DATA.key.schema_version
        ):
            try:
                table = await load_table_artifact(artifact, self._storage)
            except Exception as exc:
                raise ArtifactContentUnavailableError(
                    f"Could not load complete table artifact {artifact.id}"
                ) from exc
            return table.model_dump_json().encode("utf-8")
        if (
            artifact.artifact_type == GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
            and artifact.schema_version == 1
            and artifact.metadata.get("storage_format")
            == JSON_COLLECTIONS_STORAGE_FORMAT
        ):
            count = feature_count(artifact)
            try:
                loaded = await load_feature_collection(
                    artifact,
                    self._storage,
                    feature_count=count,
                    metadata_type=GeoFeatureManifestMetadata,
                    payload_type=GeoFeatureCollectionPayload,
                )
                return loaded.content
            except ArtifactContentUnavailableError:
                raise
            except Exception as exc:
                raise ArtifactContentUnavailableError(
                    f"Could not reconstruct complete feature artifact {artifact.id}"
                ) from exc
        if artifact.inline_payload is not None:
            return (
                json.dumps(
                    artifact.inline_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
        stream = await self._open_stored_content(artifact)
        try:
            return stream.read()
        finally:
            stream.close()

    async def open_content(self, artifact: ArtifactObject) -> ArtifactContentRead:
        streams_stored_payload_directly = (
            artifact.inline_payload is None
            and not (
                artifact.artifact_type == TABLE_DATA.key.id
                and artifact.schema_version == TABLE_DATA.key.schema_version
            )
            and not (
                artifact.artifact_type == GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
                and artifact.schema_version == 1
                and artifact.metadata.get("storage_format")
                == JSON_COLLECTIONS_STORAGE_FORMAT
            )
        )
        if streams_stored_payload_directly:
            if artifact.bucket is None or artifact.object_key is None:
                raise ArtifactContentUnavailableError(
                    f"Artifact {artifact.id} has no stored payload"
                )
            try:
                stored = await self._storage.stat(
                    bucket=artifact.bucket,
                    path=artifact.object_key,
                )
            except Exception as exc:
                raise ArtifactContentUnavailableError(
                    f"Could not inspect artifact {artifact.id} at "
                    f"{artifact.bucket}/{artifact.object_key}"
                ) from exc
            if stored is None:
                raise ArtifactContentUnavailableError(
                    f"Artifact {artifact.id} is missing from "
                    f"{artifact.bucket}/{artifact.object_key}"
                )
            if (
                artifact.byte_size is not None
                and stored.byte_size != artifact.byte_size
            ):
                raise ArtifactContentUnavailableError(
                    f"Artifact {artifact.id} contains {stored.byte_size} bytes, "
                    f"expected {artifact.byte_size}"
                )
            return ArtifactContentRead(
                body=await self._open_stored_content(artifact),
                content_length=stored.byte_size,
            )
        if (
            artifact.byte_size is not None
            and artifact.byte_size > BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES
        ):
            raise ArtifactResponseTooLargeError(
                artifact_id=artifact.id,
                byte_size=artifact.byte_size,
                max_byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
            )
        content = await self.load_content(artifact)
        if len(content) > BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES:
            raise ArtifactResponseTooLargeError(
                artifact_id=artifact.id,
                byte_size=len(content),
                max_byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
            )
        return ArtifactContentRead(body=content, content_length=len(content))

    async def load_download(
        self,
        artifact: ArtifactObject,
        format: str,
    ) -> tuple[ArtifactContentRead, str]:
        """Render the artifact into a download format.

        Returns a chunked content read and its content type. Raises
        `WorkbenchOperationError` for an unsupported format and
        `ArtifactContentUnavailableError` when content cannot be opened.
        """

        supported = [entry.format for entry in self.export_formats(artifact)]
        if format not in supported:
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} does not support download format "
                f"{format!r}; supported: {supported or 'none'}"
            )
        if format == "json":
            return await self.open_content(artifact), "application/json"
        if format == "txt":
            if (
                artifact.byte_size is not None
                and artifact.byte_size > BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES
            ):
                raise ArtifactResponseTooLargeError(
                    artifact_id=artifact.id,
                    byte_size=artifact.byte_size,
                    max_byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
                )
            text: str | None = None
            if artifact.inline_payload is not None:
                payload = artifact.inline_payload
                if isinstance(payload.get("value"), str):
                    text = cast(str, payload["value"])
                elif isinstance(payload.get("markdown"), str):
                    text = cast(str, payload["markdown"])
            if text is None:
                raise WorkbenchOperationError(
                    f"Artifact {artifact.id} cannot be downloaded as bare text"
                )
            content = text.encode("utf-8")
            if len(content) > BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES:
                raise ArtifactResponseTooLargeError(
                    artifact_id=artifact.id,
                    byte_size=len(content),
                    max_byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
                )
            return (
                ArtifactContentRead(body=content, content_length=len(content)),
                "text/plain; charset=utf-8",
            )
        if format == "csv":
            if (
                artifact.artifact_type != TABLE_DATA.key.id
                or artifact.schema_version != TABLE_DATA.key.schema_version
            ):
                raise WorkbenchOperationError(
                    f"Artifact {artifact.id} is not a table.data@1 artifact"
                )
            return (
                ArtifactContentRead(
                    body=lambda: iter_table_csv(artifact, self._storage),
                    content_length=None,
                ),
                "text/csv; charset=utf-8",
            )
        raise WorkbenchOperationError(
            f"Artifact {artifact.id} does not support download format {format!r}"
        )

    async def _open_stored_content(
        self,
        artifact: ArtifactObject,
    ) -> FileStreamProtocol:
        if artifact.bucket is None or artifact.object_key is None:
            raise ArtifactContentUnavailableError(
                f"Artifact {artifact.id} has no stored payload"
            )
        try:
            return await self._storage.load(
                bucket=artifact.bucket,
                path=artifact.object_key,
            )
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load artifact {artifact.id} from "
                f"{artifact.bucket}/{artifact.object_key}"
            ) from exc


__all__ = [
    "ARTIFACT_RESPONSE_CHUNK_SIZE",
    "ArtifactContentRead",
    "ArtifactContentService",
    "BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES",
]
