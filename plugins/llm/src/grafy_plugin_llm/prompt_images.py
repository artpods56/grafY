import base64
from hashlib import sha256
from typing import final
from uuid import UUID

from grafy_core.artifacts import ArtifactRef
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.ports.storage import FileStoragePort


class PromptImageDataError(RuntimeError):
    pass


@final
class PromptImageDataLoader:
    """Loads verified raster artifacts into bounded provider data URLs."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        provider_title: str,
        max_image_bytes: int,
        max_total_image_bytes: int,
        supported_content_types: frozenset[str],
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._provider_title = provider_title
        self._max_image_bytes = max_image_bytes
        self._max_total_image_bytes = max_total_image_bytes
        self._supported_content_types = supported_content_types

    async def data_url(
        self,
        ref: ArtifactRef,
        *,
        workspace_id: UUID,
        remaining_total_bytes: int,
    ) -> tuple[str, int]:
        if ref.key() != RASTER_IMAGE.key:
            raise PromptImageDataError(
                f"Prompt image ref {ref.artifact_id} must reference "
                f"{RASTER_IMAGE.key.id}@{RASTER_IMAGE.key.schema_version}, "
                f"got {ref.artifact_type}@{ref.schema_version}"
            )

        try:
            async with self._uow as uow:
                artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        except Exception as exc:
            raise PromptImageDataError(
                f"Failed to look up prompt image artifact {ref.artifact_id}"
            ) from exc

        if artifact is None:
            raise PromptImageDataError(
                f"Prompt image artifact {ref.artifact_id} was not found"
            )
        if artifact.ref() != ref:
            raise PromptImageDataError(
                "Artifact repository returned a different ref for prompt image "
                f"{ref.artifact_id}"
            )
        if artifact.bucket is None or artifact.object_key is None:
            raise PromptImageDataError(
                f"Prompt image artifact {ref.artifact_id} does not have a "
                "storage object"
            )
        if artifact.content_type not in self._supported_content_types:
            raise PromptImageDataError(
                f"Prompt image artifact {ref.artifact_id} has unsupported content "
                f"type {artifact.content_type!r} for {self._provider_title}"
            )
        if (
            artifact.byte_size is not None
            and artifact.byte_size > self._max_image_bytes
        ):
            raise PromptImageDataError(
                f"Prompt image artifact {ref.artifact_id} exceeds the "
                f"{self._max_image_bytes}-byte per-image limit"
            )
        if (
            artifact.byte_size is not None
            and artifact.byte_size > remaining_total_bytes
        ):
            raise PromptImageDataError(
                f"Prompt images exceed the {self._max_total_image_bytes}-byte "
                f"aggregate limit at artifact {ref.artifact_id}"
            )

        try:
            stream = await self._storage.load(
                bucket=artifact.bucket,
                path=artifact.object_key,
            )
            try:
                read_limit = min(
                    self._max_image_bytes,
                    remaining_total_bytes,
                )
                image_bytes = stream.read(read_limit + 1)
            finally:
                stream.close()
        except Exception as exc:
            raise PromptImageDataError(
                f"Failed to load prompt image artifact {ref.artifact_id} from "
                f"{artifact.bucket}/{artifact.object_key}"
            ) from exc

        actual_size = len(image_bytes)
        if actual_size > self._max_image_bytes:
            raise PromptImageDataError(
                f"Prompt image artifact {ref.artifact_id} exceeds the "
                f"{self._max_image_bytes}-byte per-image limit"
            )
        if actual_size > remaining_total_bytes:
            raise PromptImageDataError(
                f"Prompt images exceed the {self._max_total_image_bytes}-byte "
                f"aggregate limit at artifact {ref.artifact_id}"
            )
        if artifact.byte_size is not None and actual_size != artifact.byte_size:
            raise PromptImageDataError(
                f"Prompt image artifact {ref.artifact_id} size mismatch: metadata "
                f"declares {artifact.byte_size} bytes, storage returned {actual_size}"
            )
        actual_sha256 = sha256(image_bytes).hexdigest()
        expected_hashes = {
            expected
            for expected in (artifact.sha256, ref.content_hash)
            if expected is not None
        }
        if any(expected != actual_sha256 for expected in expected_hashes):
            raise PromptImageDataError(
                f"Prompt image artifact {ref.artifact_id} SHA-256 mismatch"
            )

        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{artifact.content_type};base64,{encoded}", actual_size
