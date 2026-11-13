from uuid import UUID

from grafy_api.services.errors import WorkbenchOperationError


class GeoRangeNotSatisfiableError(ValueError):
    def __init__(
        self,
        *,
        total_size: int,
        etag: str,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            reason or f"Requested byte range is not satisfiable for {total_size} bytes"
        )
        self.total_size = total_size
        self.etag = etag


class ArtifactResponseTooLargeError(WorkbenchOperationError):
    def __init__(
        self,
        *,
        artifact_id: UUID,
        byte_size: int,
        max_byte_size: int,
    ) -> None:
        super().__init__(
            f"Artifact {artifact_id} requires a {byte_size}-byte buffered "
            f"response, exceeding the {max_byte_size}-byte response limit"
        )
        self.byte_size = byte_size
        self.max_byte_size = max_byte_size


__all__ = [
    "ArtifactResponseTooLargeError",
    "GeoRangeNotSatisfiableError",
]
